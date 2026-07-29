from __future__ import annotations

import csv
import importlib.util
import json
import pickle
import random
import statistics
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


_WORKLOAD: Any | None = None


@dataclass(frozen=True)
class FusionProfile:
    fanout: int
    sample_items: int
    producer_seconds: float
    consumer_seconds: float
    serialization_seconds: float
    intermediate_bytes: int
    duplicate_compute_seconds: float
    communication_proxy_seconds: float
    selected_strategy: str
    reason: str


def _load_workload(path: str | Path) -> Any:
    source = Path(path).resolve()
    module_name = f"fusion_workload_{abs(hash(str(source)))}"
    spec = importlib.util.spec_from_file_location(module_name, source)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load workload: {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    required = {
        "FANOUT",
        "make_input",
        "produce",
        "consume_a",
        "consume_b",
        "combine",
        "equivalent",
    }
    missing = sorted(name for name in required if not hasattr(module, name))
    if missing:
        raise ValueError("fusion workload missing: " + ", ".join(missing))
    if int(module.FANOUT) not in {1, 2}:
        raise ValueError("FANOUT must be 1 or 2")
    return module


def _init_worker(path: str) -> None:
    global _WORKLOAD
    _WORKLOAD = _load_workload(path)


def _require_workload() -> Any:
    if _WORKLOAD is None:
        raise RuntimeError("fusion worker was not initialized")
    return _WORKLOAD


def _produce_chunk(items: list[Any]) -> list[Any]:
    workload = _require_workload()
    return [workload.produce(item) for item in items]


def _consume_a_chunk(items: list[Any]) -> list[Any]:
    workload = _require_workload()
    return [workload.consume_a(item) for item in items]


def _consume_b_chunk(items: list[Any]) -> list[Any]:
    workload = _require_workload()
    return [workload.consume_b(item) for item in items]


def _fused_a_chunk(items: list[Any]) -> list[Any]:
    workload = _require_workload()
    return [workload.consume_a(workload.produce(item)) for item in items]


def _fused_b_chunk(items: list[Any]) -> list[Any]:
    workload = _require_workload()
    return [workload.consume_b(workload.produce(item)) for item in items]


def _partition(items: list[Any], chunks: int) -> list[list[Any]]:
    count = max(1, min(chunks, len(items)))
    base, remainder = divmod(len(items), count)
    result: list[list[Any]] = []
    start = 0
    for index in range(count):
        width = base + (1 if index < remainder else 0)
        result.append(items[start : start + width])
        start += width
    return result


def _flatten(groups: list[list[Any]]) -> list[Any]:
    return [item for group in groups for item in group]


def profile_fusion(
    source_path: str | Path,
    *,
    size: int,
    seed: int,
    sample_items: int = 4,
) -> FusionProfile:
    workload = _load_workload(source_path)
    items = list(workload.make_input(size, seed))[: max(1, sample_items)]
    produced: list[Any] = []
    producer_started = time.perf_counter()
    for item in items:
        produced.append(workload.produce(item))
    producer_seconds = time.perf_counter() - producer_started

    consumer_started = time.perf_counter()
    for value in produced:
        workload.consume_a(value)
        if int(workload.FANOUT) == 2:
            workload.consume_b(value)
    consumer_seconds = time.perf_counter() - consumer_started

    serialization_started = time.perf_counter()
    intermediate_bytes = 0
    for value in produced:
        encoded = pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)
        intermediate_bytes += len(encoded)
        pickle.loads(encoded)
    serialization_seconds = time.perf_counter() - serialization_started

    fanout = int(workload.FANOUT)
    duplicate_compute_seconds = max(0, fanout - 1) * producer_seconds
    communication_proxy_seconds = fanout * serialization_seconds
    if fanout == 1:
        selected = "fused"
        reason = (
            "The intermediate has one consumer, so fusion removes "
            "materialization without duplicating producer computation."
        )
    elif duplicate_compute_seconds <= communication_proxy_seconds:
        selected = "fused"
        reason = (
            "Estimated duplicated producer work is no greater than the "
            "serialization proxy."
        )
    else:
        selected = "unfused"
        reason = (
            "The intermediate is reused by multiple consumers and producer "
            "duplication costs more than the serialization proxy."
        )
    return FusionProfile(
        fanout=fanout,
        sample_items=len(items),
        producer_seconds=producer_seconds,
        consumer_seconds=consumer_seconds,
        serialization_seconds=serialization_seconds,
        intermediate_bytes=intermediate_bytes,
        duplicate_compute_seconds=duplicate_compute_seconds,
        communication_proxy_seconds=communication_proxy_seconds,
        selected_strategy=selected,
        reason=reason,
    )


def execute_fusion_strategy(
    source_path: str | Path,
    *,
    strategy: str,
    size: int,
    seed: int,
    workers: int,
    chunks: int,
    profile: FusionProfile | None = None,
    pool: Any | None = None,
) -> dict[str, Any]:
    if strategy not in {"serial", "unfused", "fixed_fused", "aware"}:
        raise ValueError("unknown fusion strategy")
    source = Path(source_path).resolve()
    workload = _load_workload(source)
    items = list(workload.make_input(size, seed))
    item_chunks = _partition(items, chunks)
    actual_strategy = (
        profile.selected_strategy
        if strategy == "aware" and profile is not None
        else "fused"
        if strategy == "fixed_fused"
        else strategy
    )
    started = time.perf_counter()
    intermediate_bytes = 0
    if actual_strategy == "serial":
        intermediate = [workload.produce(item) for item in items]
        outputs_a = [workload.consume_a(value) for value in intermediate]
        outputs_b = (
            [workload.consume_b(value) for value in intermediate]
            if int(workload.FANOUT) == 2
            else None
        )
        task_count = 1
    else:
        def run_with_pool(active_pool: Any) -> tuple[
            list[Any], list[Any] | None, int, int
        ]:
            if actual_strategy == "unfused":
                intermediate = _flatten(
                    active_pool.map(_produce_chunk, item_chunks)
                )
                transfer_bytes = sum(
                    len(pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL))
                    for value in intermediate
                ) * int(workload.FANOUT)
                intermediate_chunks = _partition(intermediate, chunks)
                first_outputs = _flatten(
                    active_pool.map(_consume_a_chunk, intermediate_chunks)
                )
                second_outputs = (
                    _flatten(
                        active_pool.map(
                            _consume_b_chunk, intermediate_chunks
                        )
                    )
                    if int(workload.FANOUT) == 2
                    else None
                )
                submitted = len(item_chunks) * (
                    1 + int(workload.FANOUT)
                )
            else:
                first_outputs = _flatten(
                    active_pool.map(_fused_a_chunk, item_chunks)
                )
                second_outputs = (
                    _flatten(
                        active_pool.map(_fused_b_chunk, item_chunks)
                    )
                    if int(workload.FANOUT) == 2
                    else None
                )
                submitted = len(item_chunks) * int(workload.FANOUT)
                transfer_bytes = 0
            return (
                first_outputs,
                second_outputs,
                submitted,
                transfer_bytes,
            )

        if pool is None:
            import multiprocessing

            context = multiprocessing.get_context("spawn")
            with context.Pool(
                processes=max(1, workers),
                initializer=_init_worker,
                initargs=(str(source),),
            ) as owned_pool:
                (
                    outputs_a,
                    outputs_b,
                    task_count,
                    intermediate_bytes,
                ) = run_with_pool(owned_pool)
        else:
            (
                outputs_a,
                outputs_b,
                task_count,
                intermediate_bytes,
            ) = run_with_pool(pool)
    result = workload.combine(outputs_a, outputs_b)
    elapsed = time.perf_counter() - started
    return {
        "requested_strategy": strategy,
        "actual_strategy": actual_strategy,
        "runtime_seconds": elapsed,
        "result": result,
        "task_count": task_count,
        "intermediate_transfer_bytes": intermediate_bytes,
    }


def run_task_fusion_experiment(
    config_path: str | Path,
    *,
    output_dir: str | Path,
) -> dict[str, Any]:
    import yaml

    config = yaml.safe_load(
        Path(config_path).read_text(encoding="utf-8")
    )
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    repeats = int(config.get("repeats", 5))
    warmups = int(config.get("warmups", 1))
    workers = int(config.get("workers", 4))
    chunks = int(config.get("chunks", workers * 2))
    seed = int(config.get("seed", 42))
    rows: list[dict[str, Any]] = []
    for name, entry in config["workloads"].items():
        source = Path(entry["path"]).resolve()
        size = int(entry["size"])
        profile = profile_fusion(source, size=size, seed=seed)
        workload = _load_workload(source)
        serial_reference = execute_fusion_strategy(
            source,
            strategy="serial",
            size=size,
            seed=seed,
            workers=workers,
            chunks=chunks,
            profile=profile,
        )
        strategies = ["unfused", "fixed_fused", "aware"]
        import multiprocessing

        context = multiprocessing.get_context("spawn")
        pool_started = time.perf_counter()
        with context.Pool(
            processes=max(1, workers),
            initializer=_init_worker,
            initargs=(str(source),),
        ) as pool:
            for _ in range(warmups):
                for strategy in strategies:
                    execute_fusion_strategy(
                        source,
                        strategy=strategy,
                        size=size,
                        seed=seed,
                        workers=workers,
                        chunks=chunks,
                        profile=profile,
                        pool=pool,
                    )
            pool_ready_seconds = time.perf_counter() - pool_started
            schedule = [
                strategy for _ in range(repeats) for strategy in strategies
            ]
            random.Random(seed + len(rows)).shuffle(schedule)
            measurements: dict[str, list[dict[str, Any]]] = {
                strategy: [] for strategy in strategies
            }
            for strategy in schedule:
                run = execute_fusion_strategy(
                    source,
                    strategy=strategy,
                    size=size,
                    seed=seed,
                    workers=workers,
                    chunks=chunks,
                    profile=profile,
                    pool=pool,
                )
                run["correct"] = workload.equivalent(
                    serial_reference["result"], run["result"]
                )
                measurements[strategy].append(run)
        for strategy in strategies:
            group = measurements[strategy]
            runtimes = [float(run["runtime_seconds"]) for run in group]
            median_runtime = statistics.median(runtimes)
            rows.append(
                {
                    "workload": name,
                    "strategy": strategy,
                    "actual_strategy": group[0]["actual_strategy"],
                    "fanout": profile.fanout,
                    "correct": all(bool(run["correct"]) for run in group),
                    "runtime_median_seconds": median_runtime,
                    "speedup_over_unfused": 0.0,
                    "task_count": group[0]["task_count"],
                    "intermediate_transfer_bytes": group[0][
                        "intermediate_transfer_bytes"
                    ],
                    "profile_intermediate_bytes": (
                        profile.intermediate_bytes
                    ),
                    "profile_producer_seconds": profile.producer_seconds,
                    "profile_serialization_seconds": (
                        profile.serialization_seconds
                    ),
                    "decision_reason": (
                        profile.reason if strategy == "aware" else ""
                    ),
                }
            )
        unfused_runtime = next(
            float(row["runtime_median_seconds"])
            for row in rows
            if row["workload"] == name and row["strategy"] == "unfused"
        )
        for row in rows:
            if row["workload"] == name:
                row["speedup_over_unfused"] = (
                    unfused_runtime / float(row["runtime_median_seconds"])
                )
        workload_report = {
            "workload": name,
            "source": str(source),
            "size": size,
            "profile": asdict(profile),
            "serial_reference": serial_reference,
            "execution_order": schedule,
            "pool_warmup_seconds": pool_ready_seconds,
            "measurements": measurements,
        }
        (destination / f"{name}_report.json").write_text(
            json.dumps(workload_report, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    summary_path = destination / "task_fusion_summary.csv"
    with summary_path.open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    overall = {
        "workloads": len(config["workloads"]),
        "repeats": repeats,
        "all_correct": all(bool(row["correct"]) for row in rows),
        "aware_choices": {
            row["workload"]: row["actual_strategy"]
            for row in rows
            if row["strategy"] == "aware"
        },
    }
    (destination / "task_fusion_overall.json").write_text(
        json.dumps(overall, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return {"rows": rows, "overall": overall}


def plot_task_fusion_experiment(
    summary_csv: str | Path,
    *,
    output_dir: str | Path,
) -> Path:
    import matplotlib.pyplot as plt
    import numpy as np

    with Path(summary_csv).open(
        "r", encoding="utf-8-sig", newline=""
    ) as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError("task fusion summary is empty")
    workloads = list(dict.fromkeys(row["workload"] for row in rows))
    strategies = ["unfused", "fixed_fused", "aware"]
    labels = ["Unfused", "Fixed fusion", "Communication-aware"]
    colors = ["#9CA3AF", "#F59E0B", "#2563EB"]
    x = np.arange(len(workloads))
    width = 0.24
    fig, axes = plt.subplots(
        1, 2, figsize=(12.8, 5.4), constrained_layout=True
    )
    for index, (strategy, label, color) in enumerate(
        zip(strategies, labels, colors)
    ):
        strategy_rows = {
            row["workload"]: row
            for row in rows
            if row["strategy"] == strategy
        }
        speedups = [
            float(strategy_rows[name]["speedup_over_unfused"])
            for name in workloads
        ]
        transfers = [
            float(
                strategy_rows[name]["intermediate_transfer_bytes"]
            )
            / (1024 * 1024)
            for name in workloads
        ]
        offset = (index - 1) * width
        bars = axes[0].bar(
            x + offset, speedups, width, label=label, color=color
        )
        axes[0].bar_label(bars, fmt="%.2f", padding=2, fontsize=8)
        axes[1].bar(
            x + offset, transfers, width, label=label, color=color
        )
    axes[0].axhline(
        1.0, color="#DC2626", linestyle="--", linewidth=1.2
    )
    axes[0].set_title("Runtime Improvement over Unfused")
    axes[0].set_ylabel("Speedup")
    axes[1].set_title("Materialized Intermediate Transfer")
    axes[1].set_ylabel("MiB per run")
    for axis in axes:
        axis.set_xticks(
            x,
            [name.replace("_", " ").title() for name in workloads],
            rotation=18,
            ha="right",
        )
        axis.grid(axis="y", linestyle="--", alpha=0.3)
        axis.legend(frameon=False, fontsize=9)
    fig.suptitle(
        "Communication- and Reuse-Aware Task Fusion",
        fontsize=16,
        fontweight="bold",
    )
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    output = destination / "task_fusion_comparison.png"
    fig.savefig(output, dpi=220, bbox_inches="tight")
    plt.close(fig)
    return output
