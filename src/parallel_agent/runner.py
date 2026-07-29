from __future__ import annotations

import importlib.util
import json
import os
import pickle
import platform
import random
import statistics
import time
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


def _ray_map(
    workload: ModuleType,
    items: Sequence[Any],
    workers: int,
    chunk_count: int,
) -> tuple[Any, int]:
    try:
        import ray
    except ImportError as exc:
        raise RuntimeError(
            "Ray is not installed. Use Python 3.11/3.12 and run "
            "`python -m pip install -e .`."
        ) from exc

    if not ray.is_initialized():
        ray_temp = (Path.cwd() / "work" / "ray").resolve()
        ray_temp.mkdir(parents=True, exist_ok=True)
        ray.init(
            num_cpus=workers,
            include_dashboard=False,
            ignore_reinit_error=True,
            logging_level="ERROR",
            _temp_dir=str(ray_temp),
        )

    @ray.remote
    def run_chunk(chunk: list[Any]) -> list[Any]:
        return [workload.unit(item) for item in chunk]

    chunks = split_evenly(items, chunk_count)
    refs = [run_chunk.remote(chunk) for chunk in chunks]
    nested = ray.get(refs)
    flat = [value for chunk_values in nested for value in chunk_values]
    return workload.combine(flat), len(chunks)


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


def _pilot_item_time(workload: ModuleType, items: Sequence[Any]) -> float:
    sample = list(items[: min(5, len(items))])
    if not sample:
        return 0.0
    started = time.perf_counter()
    for item in sample:
        workload.unit(item)
    return (time.perf_counter() - started) / len(sample)


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
    item_time = _pilot_item_time(workload, items)

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

    with measured(cpu_interval) as measurement:
        if mode == "serial" or selected_mode == "serial_fallback":
            result = _serial(workload, items)
        elif backend == "ray":
            result, task_count = _ray_map(workload, items, workers, chunks)
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
        if backend == "multiprocessing":
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
) -> dict[str, Any]:
    workload = load_workload(workload_path)
    items = workload.make_input(size, seed)
    golden = _serial(workload, items)
    raw: list[RunMetrics] = []
    calibrations: dict[int, BackendCalibration] = {}
    planning_started = time.perf_counter()
    if backend == "multiprocessing" and any(
        mode in {"naive", "optimized"} for mode in modes
    ):
        for candidate_workers in worker_candidates(workers):
            calibrations[candidate_workers] = calibrate_process_backend(
                candidate_workers
            )
    planning_seconds = time.perf_counter() - planning_started
    item_time = _pilot_item_time(workload, items)
    serialized_bytes, serialization_seconds = _serialization_profile(items)
    optimized_plan = (
        choose_execution_plan(
            item_count=len(items),
            item_runtime_seconds=item_time,
            calibrations=calibrations,
            serialization_seconds=serialization_seconds,
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

    report = {
        "benchmark": workload.NAME,
        "size": len(items),
        "workers": workers,
        "backend": backend,
        "randomize_order": randomize_order,
        "execution_order": execution_order,
        "planning_seconds": planning_seconds,
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
