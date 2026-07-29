from __future__ import annotations

import importlib.util
import json
import os
import pickle
import platform
import random
import statistics
import tempfile
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from pathlib import Path
from types import ModuleType
from typing import Any, Sequence

import psutil

from .chunking import estimate_chunk_count, split_evenly
from .models import RunMetrics
from .optimizer import (
    BackendCalibration,
    ExecutionPlan,
    choose_execution_plan,
    worker_candidates,
)
from .profiler import ResourceSamples, measured


for _thread_env in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_thread_env, "1")

_RAY_STARTUP_SECONDS = 0.0


def load_workload(path: str | Path) -> ModuleType:
    file_path = Path(path).resolve()
    spec = importlib.util.spec_from_file_location(
        f"benchmark_{file_path.parent.name}", file_path
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot import workload from {file_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    required = {"NAME", "make_input", "unit", "combine", "equivalent"}
    missing = sorted(name for name in required if not hasattr(module, name))
    if missing:
        raise ValueError(f"Workload is missing: {', '.join(missing)}")
    return module


def _serial(workload: ModuleType, items: Sequence[Any]) -> Any:
    return workload.combine([workload.unit(item) for item in items])


def ray_temp_directory() -> Path:
    """Return a short absolute root for Ray-generated session sockets."""
    return (Path(tempfile.gettempdir()) / "pa_ray").resolve()


def ensure_ray_initialized(
    workers: int, address: str | None = None
) -> float:
    """Connect to Ray or start it locally, returning observed startup cost."""
    global _RAY_STARTUP_SECONDS
    try:
        import ray
    except ImportError as exc:
        raise RuntimeError(
            "Ray is not installed. Use Python 3.11/3.12 and run "
            "`python -m pip install -e .`."
        ) from exc
    if ray.is_initialized():
        return _RAY_STARTUP_SECONDS
    started = time.perf_counter()
    if address:
        ray.init(
            address=address,
            include_dashboard=False,
            ignore_reinit_error=True,
            logging_level="ERROR",
        )
    else:
        ray_temp = ray_temp_directory()
        ray_temp.mkdir(parents=True, exist_ok=True)
        ray.init(
            num_cpus=workers,
            include_dashboard=False,
            ignore_reinit_error=True,
            logging_level="ERROR",
            _temp_dir=str(ray_temp),
        )
    _RAY_STARTUP_SECONDS = time.perf_counter() - started
    return _RAY_STARTUP_SECONDS


def calibrate_ray_backend(
    workers: int,
    task_samples: int = 32,
    address: str | None = None,
) -> BackendCalibration:
    """Measure warm Ray submission/get overhead using identity tasks."""
    import ray

    ensure_ray_initialized(workers, address)
    remote_identity = ray.remote(_identity)
    ray.get([remote_identity.remote(value) for value in range(workers)])
    started = time.perf_counter()
    values = ray.get(
        [remote_identity.remote(value) for value in range(task_samples)]
    )
    elapsed = time.perf_counter() - started
    assert values == list(range(task_samples))
    return BackendCalibration(
        workers=workers,
        startup_seconds=0.0,
        task_overhead_seconds=elapsed / task_samples,
    )


def _ray_map(
    workload: ModuleType,
    items: Sequence[Any],
    workers: int,
    chunk_count: int,
) -> tuple[Any, int, list[list[Any]], list[str]]:
    try:
        import ray
    except ImportError as exc:
        raise RuntimeError(
            "Ray is not installed. Use Python 3.11/3.12 and run "
            "`python -m pip install -e .`."
        ) from exc

    ensure_ray_initialized(workers)
    run_chunk = ray.remote(_run_ray_chunk)
    chunks = split_evenly(items, chunk_count)
    refs = [
        run_chunk.remote(workload.unit, chunk)
        for chunk in chunks
    ]
    task_results = ray.get(refs)
    nested = [values for values, _node_id in task_results]
    execution_node_ids = [
        node_id for _values, node_id in task_results
    ]
    flat = [value for chunk_values in nested for value in chunk_values]
    return (
        workload.combine(flat),
        len(chunks),
        nested,
        execution_node_ids,
    )


def _run_ray_chunk(
    unit_function: Any, chunk: list[Any]
) -> tuple[list[Any], str]:
    """Execute a chunk without requiring workload files on worker nodes."""
    import ray

    values = [unit_function(item) for item in chunk]
    node_id = str(ray.get_runtime_context().get_node_id())
    return values, node_id


def _run_process_chunk(workload_path: str, chunk: list[Any]) -> list[Any]:
    workload = load_workload(workload_path)
    return [workload.unit(item) for item in chunk]


def _identity(value: int) -> int:
    return value


def _warm_worker(value: int) -> int:
    time.sleep(0.01)
    return value


def calibrate_process_backend(workers: int, task_samples: int = 32) -> BackendCalibration:
    started = time.perf_counter()
    with ProcessPoolExecutor(max_workers=workers) as pool:
        list(pool.map(_warm_worker, range(workers)))
        startup = time.perf_counter() - started
        overhead_started = time.perf_counter()
        values = list(pool.map(_identity, range(task_samples)))
        assert values == list(range(task_samples))
        overhead = (time.perf_counter() - overhead_started) / task_samples
    return BackendCalibration(workers, startup, overhead)


def ray_cluster_metadata(
    requested_address: str | None,
) -> dict[str, Any]:
    """Return auditable cluster evidence without claiming single-node scaling."""
    import ray

    alive_nodes = [node for node in ray.nodes() if node.get("Alive")]
    addresses = sorted(
        {
            str(node.get("NodeManagerAddress"))
            for node in alive_nodes
            if node.get("NodeManagerAddress")
        }
    )
    resources = ray.cluster_resources()
    return {
        "requested_address": requested_address or "local",
        "alive_nodes": len(alive_nodes),
        "physical_node_count": len(addresses),
        "multi_node": len(addresses) >= 2,
        "cluster_resources": resources,
        "total_cpu": float(resources.get("CPU", 0.0)),
        "total_gpu": float(resources.get("GPU", 0.0)),
        "nodes": [
            {
                "node_id": node.get("NodeID"),
                "node_manager_address": node.get(
                    "NodeManagerAddress"
                ),
                "resources": node.get("Resources", {}),
            }
            for node in alive_nodes
        ],
    }


def _process_map_with_pool(
    pool: ProcessPoolExecutor,
    workload: ModuleType,
    items: Sequence[Any],
    workers: int,
    chunk_count: int,
) -> tuple[Any, int, list[list[Any]]]:
    chunks = split_evenly(items, chunk_count)
    workload_path = str(Path(workload.__file__).resolve())
    nested = list(
        pool.map(
            _run_process_chunk,
            [workload_path] * len(chunks),
            chunks,
        )
    )
    flat = [value for chunk_values in nested for value in chunk_values]
    return workload.combine(flat), len(chunks), nested


def _serialization_profile(values: Sequence[Any]) -> tuple[int, float]:
    started = time.perf_counter()
    total_bytes = sum(
        len(pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL))
        for value in values
    )
    return total_bytes, time.perf_counter() - started


def _pilot_item_profile(
    workload: ModuleType, items: Sequence[Any], max_samples: int = 16
) -> tuple[float, float, int]:
    """Estimate mean item cost and variation from stratified input samples."""
    if not items:
        return 0.0, 0.0, 0
    sample_count = min(max_samples, len(items))
    if sample_count == 1:
        indices = [0]
    else:
        indices = sorted(
            {
                round(index * (len(items) - 1) / (sample_count - 1))
                for index in range(sample_count)
            }
        )
    durations: list[float] = []
    for index in indices:
        started = time.perf_counter()
        workload.unit(items[index])
        durations.append(time.perf_counter() - started)
    mean = statistics.fmean(durations)
    coefficient_of_variation = (
        statistics.pstdev(durations) / mean
        if len(durations) > 1 and mean > 0
        else 0.0
    )
    return mean, coefficient_of_variation, len(durations)


def _pilot_item_time(workload: ModuleType, items: Sequence[Any]) -> float:
    """Compatibility helper for callers that only need the mean pilot cost."""
    return _pilot_item_profile(workload, items)[0]


def _percentile(values: Sequence[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("Cannot calculate percentile of empty values")
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def run_once(
    workload: ModuleType,
    items: Sequence[Any],
    mode: str,
    workers: int,
    golden: Any,
    backend: str = "multiprocessing",
    cpu_interval: float = 0.05,
    task_overhead_seconds: float = 0.001,
    backend_startup_seconds: float = 0.0,
    min_expected_speedup: float = 1.05,
    execution_plan: ExecutionPlan | None = None,
) -> tuple[RunMetrics, Any]:
    selected_mode = mode
    notes: list[str] = []
    chunks = 1
    task_count = 1
    item_time, item_cv, pilot_samples = _pilot_item_profile(workload, items)

    if mode == "naive":
        chunks = len(items)
    elif mode == "optimized":
        if execution_plan is not None:
            workers = execution_plan.workers
            chunks = execution_plan.chunks
            selected_mode = execution_plan.selected_mode
        else:
            chunks = estimate_chunk_count(
                len(items), workers, item_time, task_overhead_seconds
            )
        notes.append(f"pilot_item_ms={item_time * 1000:.3f}")
        notes.append(f"pilot_item_cv={item_cv:.3f}")
        notes.append(f"pilot_samples={pilot_samples}")
        predicted_serial = (
            execution_plan.predicted_serial_seconds
            if execution_plan
            else item_time * len(items)
        )
        predicted_parallel = (
            execution_plan.predicted_total_seconds
            if execution_plan
            else (
                predicted_serial / max(workers, 1)
                + backend_startup_seconds
                + chunks * task_overhead_seconds
            )
        )
        notes.extend(
            [
                f"predicted_serial_ms={predicted_serial * 1000:.3f}",
                f"predicted_parallel_ms={predicted_parallel * 1000:.3f}",
            ]
        )
        if execution_plan is None and (
            predicted_parallel * min_expected_speedup >= predicted_serial
        ):
            selected_mode = "serial_fallback"
            chunks = 1
            task_count = 1
            notes.append("benefit_gate=rejected_parallelism")
    elif mode != "serial":
        raise ValueError(f"Unknown mode: {mode}")

    pool: ProcessPoolExecutor | None = None
    cold_start = 0.0
    input_bytes = 0
    input_serialization = 0.0
    output_bytes = 0
    output_serialization = 0.0
    execution_node_counts: dict[str, int] = {}
    parallel_chunks = (
        split_evenly(items, chunks)
        if mode != "serial" and selected_mode != "serial_fallback"
        else []
    )
    if parallel_chunks:
        input_bytes, input_serialization = _serialization_profile(parallel_chunks)
    if (
        backend == "multiprocessing"
        and mode != "serial"
        and selected_mode != "serial_fallback"
    ):
        start = time.perf_counter()
        pool = ProcessPoolExecutor(max_workers=workers)
        list(pool.map(_warm_worker, range(workers)))
        cold_start = time.perf_counter() - start

    uses_parallel_backend = (
        mode != "serial" and selected_mode != "serial_fallback"
    )
    with measured(
        cpu_interval, include_children=uses_parallel_backend
    ) as measurement:
        if mode == "serial" or selected_mode == "serial_fallback":
            result = _serial(workload, items)
        elif backend == "ray":
            result, task_count, task_outputs, execution_node_ids = _ray_map(
                workload, items, workers, chunks
            )
            execution_node_counts = dict(Counter(execution_node_ids))
        elif backend == "multiprocessing":
            assert pool is not None
            result, task_count, task_outputs = _process_map_with_pool(
                pool, workload, items, workers, chunks
            )
        else:
            raise ValueError(f"Unknown backend: {backend}")
    if pool is not None:
        pool.shutdown(wait=True)
    if mode != "serial" and selected_mode != "serial_fallback":
        if backend in {"multiprocessing", "ray"}:
            output_bytes, output_serialization = _serialization_profile(task_outputs)
        else:
            output_bytes, output_serialization = _serialization_profile([result])

    resources = measurement["resources"]
    assert isinstance(resources, ResourceSamples)
    metric = RunMetrics(
        benchmark=workload.NAME,
        mode=mode,
        size=len(items),
        workers=(
            1
            if mode == "serial" or selected_mode == "serial_fallback"
            else workers
        ),
        chunks=chunks,
        runtime_seconds=float(measurement["runtime_seconds"]),
        cpu_mean_percent=resources.cpu_mean,
        cpu_peak_percent=resources.cpu_peak,
        peak_rss_bytes=resources.rss_peak,
        task_count=task_count,
        correct=workload.equivalent(golden, result),
        selected_mode=selected_mode,
        cold_start_seconds=cold_start,
        total_runtime_seconds=cold_start + float(measurement["runtime_seconds"]),
        task_overhead_seconds=task_overhead_seconds,
        input_serialized_bytes=input_bytes,
        input_serialization_seconds=input_serialization,
        output_serialized_bytes=output_bytes,
        output_serialization_seconds=output_serialization,
        execution_node_counts=execution_node_counts,
        notes=notes,
    )
    return metric, result


def benchmark(
    workload_path: str | Path,
    size: int,
    workers: int,
    modes: Sequence[str],
    repeats: int,
    warmups: int,
    seed: int,
    output: str | Path | None = None,
    backend: str = "multiprocessing",
    randomize_order: bool = True,
    ray_address: str | None = None,
) -> dict[str, Any]:
    if ray_address and backend != "ray":
        raise ValueError("ray_address requires backend='ray'")
    workload = load_workload(workload_path)
    items = workload.make_input(size, seed)
    golden = _serial(workload, items)
    uses_parallel_mode = any(
        mode in {"naive", "optimized"} for mode in modes
    )
    raw: list[RunMetrics] = []
    calibrations: dict[int, BackendCalibration] = {}
    backend_startup_seconds = 0.0
    planning_started = time.perf_counter()
    if backend == "multiprocessing" and uses_parallel_mode:
        for candidate_workers in worker_candidates(workers):
            calibrations[candidate_workers] = calibrate_process_backend(
                candidate_workers
            )
    elif backend == "ray" and uses_parallel_mode:
        backend_startup_seconds = ensure_ray_initialized(
            workers, ray_address
        )
        calibrations[workers] = calibrate_ray_backend(
            workers, address=ray_address
        )
    planning_seconds = time.perf_counter() - planning_started
    item_time, item_cv, pilot_samples = _pilot_item_profile(workload, items)
    serialized_bytes, serialization_seconds = _serialization_profile(items)
    optimized_plan = (
        choose_execution_plan(
            item_count=len(items),
            item_runtime_seconds=item_time,
            calibrations=calibrations,
            serialization_seconds=serialization_seconds,
            item_runtime_coefficient_of_variation=item_cv,
        )
        if calibrations and "optimized" in modes
        else None
    )

    mode_settings: dict[str, tuple[int, float]] = {}
    for mode in modes:
        mode_workers = (
            optimized_plan.workers
            if mode == "optimized" and optimized_plan is not None
            else workers
        )
        mode_overhead = calibrations.get(
            mode_workers, BackendCalibration(mode_workers, 0.0, 0.001)
        ).task_overhead_seconds
        mode_settings[mode] = (mode_workers, mode_overhead)
        for _ in range(warmups):
            metric, _ = run_once(
                workload,
                items,
                mode,
                workers,
                golden,
                backend=backend,
                task_overhead_seconds=mode_overhead,
                execution_plan=optimized_plan if mode == "optimized" else None,
            )
            if not metric.correct:
                raise AssertionError(f"{workload.NAME}/{mode} failed warmup correctness")

    execution_order = [mode for _ in range(repeats) for mode in modes]
    if randomize_order:
        random.Random(seed + len(items) * 1009).shuffle(execution_order)
    for mode in execution_order:
        _, mode_overhead = mode_settings[mode]
        metric, _ = run_once(
            workload,
            items,
            mode,
            workers,
            golden,
            backend=backend,
            task_overhead_seconds=mode_overhead,
            execution_plan=optimized_plan if mode == "optimized" else None,
        )
        raw.append(metric)

    summaries: dict[str, dict[str, Any]] = {}
    serial_median = statistics.median(
        metric.runtime_seconds for metric in raw if metric.mode == "serial"
    )
    for mode in modes:
        rows = [metric for metric in raw if metric.mode == mode]
        runtime = statistics.median(row.runtime_seconds for row in rows)
        runtime_values = [row.runtime_seconds for row in rows]
        total_values = [row.total_runtime_seconds for row in rows]
        effective_workers = int(statistics.median(row.workers for row in rows))
        summaries[mode] = {
            "runtime_median_seconds": runtime,
            "runtime_q1_seconds": _percentile(runtime_values, 0.25),
            "runtime_q3_seconds": _percentile(runtime_values, 0.75),
            "runtime_iqr_seconds": (
                _percentile(runtime_values, 0.75)
                - _percentile(runtime_values, 0.25)
            ),
            "cold_start_median_seconds": statistics.median(
                row.cold_start_seconds for row in rows
            ),
            "total_runtime_median_seconds": statistics.median(
                total_values
            ),
            "total_runtime_q1_seconds": _percentile(total_values, 0.25),
            "total_runtime_q3_seconds": _percentile(total_values, 0.75),
            "total_runtime_iqr_seconds": (
                _percentile(total_values, 0.75)
                - _percentile(total_values, 0.25)
            ),
            "speedup": serial_median / runtime,
            "total_speedup": serial_median
            / statistics.median(row.total_runtime_seconds for row in rows),
            "parallel_efficiency": (
                serial_median / runtime / effective_workers
                if mode != "serial"
                else 1.0
            ),
            "parallel_overhead_core_seconds": (
                effective_workers * runtime - serial_median
                if mode != "serial"
                else 0.0
            ),
            "parallel_overhead_ratio": (
                (effective_workers * runtime - serial_median)
                / serial_median
                if mode != "serial" and serial_median > 0
                else 0.0
            ),
            "correct": all(row.correct for row in rows),
            "cpu_mean_percent": statistics.fmean(
                row.cpu_mean_percent for row in rows
            ),
            "task_count": int(statistics.median(row.task_count for row in rows)),
            "workers": effective_workers,
            "input_serialized_bytes": int(
                statistics.median(row.input_serialized_bytes for row in rows)
            ),
            "input_serialization_seconds": statistics.median(
                row.input_serialization_seconds for row in rows
            ),
            "output_serialized_bytes": int(
                statistics.median(row.output_serialized_bytes for row in rows)
            ),
            "output_serialization_seconds": statistics.median(
                row.output_serialization_seconds for row in rows
            ),
            "serialization_to_runtime_ratio": (
                statistics.median(
                    row.input_serialization_seconds
                    + row.output_serialization_seconds
                    for row in rows
                )
                / runtime
                if runtime > 0
                else 0.0
            ),
            "selected_modes": sorted(
                {row.selected_mode or row.mode for row in rows}
            ),
        }
        uses_parallel_backend = any(
            row.mode != "serial"
            and row.selected_mode != "serial_fallback"
            for row in rows
        )
        first_use_total = (
            statistics.median(total_values)
            + (backend_startup_seconds if uses_parallel_backend else 0.0)
        )
        summaries[mode]["first_use_total_runtime_seconds"] = first_use_total
        summaries[mode]["first_use_speedup"] = (
            serial_median / first_use_total if first_use_total > 0 else 0.0
        )
        summaries[mode]["first_use_parallel_overhead_core_seconds"] = (
            effective_workers * first_use_total - serial_median
            if mode != "serial"
            else 0.0
        )
        summaries[mode]["first_use_parallel_overhead_ratio"] = (
            (
                effective_workers * first_use_total - serial_median
            )
            / serial_median
            if mode != "serial" and serial_median > 0
            else 0.0
        )

    ray_cluster: dict[str, Any] | None = None
    if backend == "ray" and uses_parallel_mode:
        ray_cluster = ray_cluster_metadata(ray_address)
        execution_counts = Counter()
        for metric in raw:
            execution_counts.update(metric.execution_node_counts)
        ray_cluster.update(
            {
                "executed_node_ids": sorted(execution_counts),
                "executed_node_count": len(execution_counts),
                "executed_on_multiple_nodes": len(execution_counts) >= 2,
                "task_executions_by_node": dict(execution_counts),
            }
        )
    report = {
        "benchmark": workload.NAME,
        "size": len(items),
        "workers": workers,
        "backend": backend,
        "randomize_order": randomize_order,
        "execution_order": execution_order,
        "planning_seconds": planning_seconds,
        "pilot_profile": {
            "mean_item_runtime_seconds": item_time,
            "item_runtime_coefficient_of_variation": item_cv,
            "samples": pilot_samples,
        },
        "backend_startup_seconds": backend_startup_seconds,
        "ray_cluster": ray_cluster,
        "dataset_serialized_bytes": serialized_bytes,
        "dataset_serialization_seconds": serialization_seconds,
        "calibrations": {
            str(key): asdict(value) for key, value in calibrations.items()
        },
        "optimized_plan": asdict(optimized_plan) if optimized_plan else None,
        "environment": {
            "platform": platform.platform(),
            "processor": platform.processor(),
            "cpu_physical": psutil.cpu_count(logical=False),
            "cpu_logical": psutil.cpu_count(logical=True),
            "memory_bytes": psutil.virtual_memory().total,
            "python": os.sys.version,
            "thread_limits": {
                name: os.environ.get(name)
                for name in (
                    "OMP_NUM_THREADS",
                    "MKL_NUM_THREADS",
                    "OPENBLAS_NUM_THREADS",
                )
            },
        },
        "summary": summaries,
        "runs": [asdict(metric) for metric in raw],
    }
    if output:
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    return report
