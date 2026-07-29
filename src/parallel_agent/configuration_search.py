from __future__ import annotations

import hashlib
import json
import math
import random
import statistics
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Sequence

from .agent_adapter import OfflineHeuristicAdapter
from .artifacts import ParallelPlan
from .candidate_executor import CandidateRun, execute_candidate
from .generator import generate_candidate


@dataclass(frozen=True)
class ParallelConfiguration:
    workers: int
    chunks: int

    @property
    def label(self) -> str:
        return f"w{self.workers}_c{self.chunks}"

    def validate(self) -> None:
        if self.workers < 1 or self.chunks < 1:
            raise ValueError("workers and chunks must be positive")
        if self.chunks < self.workers:
            raise ValueError("chunks must be at least workers")


def configuration_grid(
    *,
    max_workers: int,
    chunk_multipliers: Sequence[int] = (1, 2, 4),
) -> list[ParallelConfiguration]:
    if max_workers < 1:
        raise ValueError("max_workers must be positive")
    if not chunk_multipliers or any(
        multiplier < 1 for multiplier in chunk_multipliers
    ):
        raise ValueError("chunk multipliers must be positive")
    workers = {1, max_workers}
    power = 2
    while power < max_workers:
        workers.add(power)
        power *= 2
    configurations = {
        ParallelConfiguration(
            workers=worker,
            chunks=worker * multiplier,
        )
        for worker in workers
        for multiplier in chunk_multipliers
    }
    return sorted(
        configurations, key=lambda item: (item.workers, item.chunks)
    )


def _quartiles(values: list[float]) -> tuple[float, float]:
    if len(values) == 1:
        return values[0], values[0]
    q1, _, q3 = statistics.quantiles(
        values, n=4, method="inclusive"
    )
    return q1, q3


def _fingerprint(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _compact_run(
    run: CandidateRun, *, label: str
) -> dict[str, Any]:
    result = (
        run.payload.get("result")
        if run.payload is not None
        else None
    )
    return {
        "label": label,
        "mode": run.mode,
        "returncode": run.returncode,
        "elapsed_seconds": run.elapsed_seconds,
        "runtime_seconds": (
            run.payload.get("runtime_seconds")
            if run.payload is not None
            else None
        ),
        "task_count": (
            run.payload.get("task_count")
            if run.payload is not None
            else None
        ),
        "result_fingerprint": (
            _fingerprint(result) if run.payload is not None else None
        ),
        "error_type": run.error_type,
        "stderr_tail": run.stderr[-1000:],
    }


def _measure_schedule(
    candidate: Path,
    *,
    configurations: dict[str, ParallelConfiguration | None],
    size: int,
    seed: int,
    timeout_seconds: float,
    repeats: int,
    order_seed: int,
) -> tuple[
    dict[str, list[CandidateRun]],
    list[str],
    list[dict[str, Any]],
]:
    if repeats < 1:
        raise ValueError("repeats must be positive")
    schedule = [
        label for _ in range(repeats) for label in configurations
    ]
    random.Random(order_seed).shuffle(schedule)
    runs = {label: [] for label in configurations}
    compact: list[dict[str, Any]] = []
    for label in schedule:
        configuration = configurations[label]
        run = execute_candidate(
            candidate,
            mode="serial" if configuration is None else "parallel",
            size=size,
            seed=seed,
            timeout_seconds=timeout_seconds,
            workers=(
                configuration.workers
                if configuration is not None
                else None
            ),
            chunks=(
                configuration.chunks
                if configuration is not None
                else None
            ),
        )
        runs[label].append(run)
        compact.append(_compact_run(run, label=label))
    return runs, schedule, compact


def _configuration_statistics(
    runs: dict[str, list[CandidateRun]],
    configurations: dict[str, ParallelConfiguration | None],
) -> dict[str, dict[str, Any]]:
    serial_results = [
        run.payload.get("result")
        for run in runs["serial"]
        if run.error_type is None and run.payload is not None
    ]
    reference = serial_results[0] if serial_results else None
    serial_valid = (
        bool(serial_results)
        and len(serial_results) == len(runs["serial"])
        and all(value == reference for value in serial_results)
    )
    serial_times = [run.elapsed_seconds for run in runs["serial"]]
    serial_median = statistics.median(serial_times)
    serial_q1, serial_q3 = _quartiles(serial_times)
    statistics_by_label: dict[str, dict[str, Any]] = {
        "serial": {
            "valid": serial_valid,
            "median_seconds": serial_median,
            "q1_seconds": serial_q1,
            "q3_seconds": serial_q3,
            "speedup": 1.0,
            "conservative_speedup": 1.0,
        }
    }
    for label, configuration in configurations.items():
        if configuration is None:
            continue
        group = runs[label]
        results = [
            run.payload.get("result")
            for run in group
            if run.error_type is None and run.payload is not None
        ]
        task_counts = [
            run.payload.get("task_count")
            for run in group
            if run.payload is not None
        ]
        valid = (
            serial_valid
            and bool(results)
            and len(results) == len(group)
            and all(value == reference for value in results)
            and len(task_counts) == len(group)
            and all(
                isinstance(value, int)
                and not isinstance(value, bool)
                and 1 <= value <= configuration.chunks
                for value in task_counts
            )
        )
        times = [run.elapsed_seconds for run in group]
        median = statistics.median(times)
        q1, q3 = _quartiles(times)
        statistics_by_label[label] = {
            **asdict(configuration),
            "valid": valid,
            "median_seconds": median,
            "q1_seconds": q1,
            "q3_seconds": q3,
            "speedup": (
                serial_median / median if median > 0 else 0.0
            ),
            "conservative_speedup": (
                serial_q1 / q3 if q3 > 0 else 0.0
            ),
            "task_count_median": (
                statistics.median(task_counts)
                if task_counts
                else None
            ),
        }
    return statistics_by_label


def select_configuration(
    statistics_by_label: dict[str, dict[str, Any]],
    *,
    minimum_speedup: float,
) -> str:
    if minimum_speedup <= 0:
        raise ValueError("minimum_speedup must be positive")
    eligible = [
        (label, row)
        for label, row in statistics_by_label.items()
        if label != "serial"
        and row["valid"]
        and row["speedup"] >= minimum_speedup
        and row["conservative_speedup"] >= minimum_speedup
    ]
    if not eligible:
        return "serial"
    return min(
        eligible,
        key=lambda item: (
            float(item[1]["median_seconds"]),
            int(item[1]["workers"]),
            int(item[1]["chunks"]),
        ),
    )[0]


def run_configuration_search(
    source_path: str | Path,
    *,
    output_dir: str | Path,
    size: int,
    seed: int,
    max_workers: int,
    tuning_size: int | None = None,
    chunk_multipliers: Sequence[int] = (1, 2, 4),
    tuning_repeats: int = 2,
    confirmation_repeats: int = 2,
    holdout_repeats: int = 5,
    warmups: int = 1,
    timeout_seconds: float = 120.0,
    minimum_speedup: float = 1.05,
    minimum_relative_improvement: float = 1.05,
    order_seed: int = 42,
) -> dict[str, Any]:
    source = Path(source_path).resolve()
    effective_tuning_size = (
        size if tuning_size is None else tuning_size
    )
    if size < 1 or effective_tuning_size < 1:
        raise ValueError("size and tuning_size must be positive")
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    adapter = OfflineHeuristicAdapter()
    analysis = adapter.analyze(source)
    if not analysis.parallelizable:
        report = {
            "status": "rejected",
            "source": str(source),
            "analysis": analysis.to_dict(),
            "selected_label": "serial",
            "reason": analysis.rationale,
        }
        (destination / "configuration_search_report.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return report

    grid = configuration_grid(
        max_workers=max_workers,
        chunk_multipliers=chunk_multipliers,
    )
    fixed_configuration = ParallelConfiguration(
        workers=max_workers,
        chunks=max_workers,
    )
    fixed_label = fixed_configuration.label
    if fixed_configuration not in grid:
        grid.append(fixed_configuration)
        grid.sort(key=lambda item: (item.workers, item.chunks))
    maximum = max(grid, key=lambda item: item.workers)
    plan = ParallelPlan(
        schema_version="1.0",
        source_path=str(source),
        parallelizable=True,
        backend="multiprocessing",
        strategy="map_reduce",
        workers=maximum.workers,
        chunks=maximum.chunks,
        correctness_gate=True,
        fallback="serial",
        reasons=["Generate one parameterized candidate for measured search."],
    )
    candidate = generate_candidate(plan, destination / "candidate.py")
    configurations: dict[str, ParallelConfiguration | None] = {
        "serial": None,
        **{configuration.label: configuration for configuration in grid},
    }

    warmup_records: list[dict[str, Any]] = []
    for _ in range(warmups):
        for label, configuration in configurations.items():
            run = execute_candidate(
                candidate,
                mode=(
                    "serial" if configuration is None else "parallel"
                ),
                size=effective_tuning_size,
                seed=seed,
                timeout_seconds=timeout_seconds,
                workers=(
                    configuration.workers
                    if configuration is not None
                    else None
                ),
                chunks=(
                    configuration.chunks
                    if configuration is not None
                    else None
                ),
            )
            warmup_records.append(_compact_run(run, label=label))

    tuning_started = time.perf_counter()
    tuning_runs, tuning_order, compact_tuning = _measure_schedule(
        candidate,
        configurations=configurations,
        size=effective_tuning_size,
        seed=seed,
        timeout_seconds=timeout_seconds,
        repeats=tuning_repeats,
        order_seed=order_seed,
    )
    tuning_seconds = time.perf_counter() - tuning_started
    tuning_statistics = _configuration_statistics(
        tuning_runs, configurations
    )
    preliminary_selected_label = select_configuration(
        tuning_statistics,
        minimum_speedup=minimum_speedup,
    )
    selected_label = preliminary_selected_label
    confirmation: dict[str, Any] | None = None
    if (
        preliminary_selected_label != fixed_label
        and effective_tuning_size < size
        and confirmation_repeats > 0
    ):
        if preliminary_selected_label == "serial":
            probe_candidates = [
                (label, row)
                for label, row in tuning_statistics.items()
                if label != "serial" and row["valid"]
            ]
        else:
            probe_candidates = [
                (
                    preliminary_selected_label,
                    tuning_statistics[preliminary_selected_label],
                )
            ]
        if probe_candidates:
            probe_label, _ = min(
                probe_candidates,
                key=lambda item: float(item[1]["median_seconds"]),
            )
            probe_configuration = configurations[probe_label]
            assert probe_configuration is not None
            confirmation_configurations = {
                "serial": None,
                "probe": probe_configuration,
            }
            if probe_configuration != fixed_configuration:
                confirmation_configurations[
                    "fixed"
                ] = fixed_configuration
            confirmation_started = time.perf_counter()
            (
                confirmation_runs,
                confirmation_order,
                compact_confirmation,
            ) = _measure_schedule(
                candidate,
                configurations=confirmation_configurations,
                size=size,
                seed=seed,
                timeout_seconds=timeout_seconds,
                repeats=confirmation_repeats,
                order_seed=order_seed + 17,
            )
            tuning_seconds += (
                time.perf_counter() - confirmation_started
            )
            confirmation_statistics = _configuration_statistics(
                confirmation_runs, confirmation_configurations
            )
            eligible_confirmation = {
                label: row
                for label, row in confirmation_statistics.items()
                if label != "serial"
                and row["valid"]
                and row["speedup"] >= minimum_speedup
                and row["conservative_speedup"] >= minimum_speedup
            }
            confirmation_choice = "serial"
            if "probe" in eligible_confirmation:
                confirmation_choice = "probe"
            if "fixed" in eligible_confirmation:
                if confirmation_choice == "serial":
                    confirmation_choice = "fixed"
                else:
                    probe_row = eligible_confirmation["probe"]
                    fixed_row = eligible_confirmation["fixed"]
                    probe_over_fixed = (
                        float(fixed_row["median_seconds"])
                        / float(probe_row["median_seconds"])
                    )
                    conservative_probe_over_fixed = (
                        float(fixed_row["q1_seconds"])
                        / float(probe_row["q3_seconds"])
                    )
                    if (
                        probe_over_fixed
                        < minimum_relative_improvement
                        or conservative_probe_over_fixed < 1.0
                    ):
                        confirmation_choice = "fixed"
            confirmation_passed = confirmation_choice != "serial"
            if confirmation_choice == "probe":
                selected_label = probe_label
            elif confirmation_choice == "fixed":
                selected_label = fixed_label
            confirmation = {
                "reason": (
                    "Small-sample tuning selected a non-fixed action; probe "
                    "the candidate at full scale and compare it with the "
                    "fixed baseline."
                ),
                "probe_label": probe_label,
                "probe_configuration": asdict(probe_configuration),
                "execution_order": confirmation_order,
                "statistics": confirmation_statistics,
                "runs": compact_confirmation,
                "passed": confirmation_passed,
                "choice": confirmation_choice,
            }
    selected_configuration = configurations[selected_label]
    holdout_configurations: dict[
        str, ParallelConfiguration | None
    ] = {
        "serial": None,
        "fixed": fixed_configuration,
    }
    if selected_label != "serial" and selected_label != fixed_label:
        holdout_configurations["selected"] = selected_configuration

    holdout_runs, holdout_order, compact_holdout = _measure_schedule(
        candidate,
        configurations=holdout_configurations,
        size=size,
        seed=seed,
        timeout_seconds=timeout_seconds,
        repeats=holdout_repeats,
        order_seed=order_seed + 1,
    )
    holdout_statistics = _configuration_statistics(
        holdout_runs, holdout_configurations
    )
    selected_holdout_key = (
        "serial"
        if selected_label == "serial"
        else "fixed"
        if selected_label == fixed_label
        else "selected"
    )
    selected_holdout = holdout_statistics[selected_holdout_key]
    fixed_holdout = holdout_statistics["fixed"]
    serial_holdout = holdout_statistics["serial"]
    per_run_savings = (
        float(serial_holdout["median_seconds"])
        - float(selected_holdout["median_seconds"])
    )
    savings_over_fixed = (
        float(fixed_holdout["median_seconds"])
        - float(selected_holdout["median_seconds"])
    )
    break_even_vs_serial = (
        math.ceil(tuning_seconds / per_run_savings)
        if selected_label != "serial" and per_run_savings > 0
        else None
    )
    break_even_vs_fixed = (
        math.ceil(tuning_seconds / savings_over_fixed)
        if savings_over_fixed > 0
        else None
    )
    report = {
        "status": "completed",
        "source": str(source),
        "workload": analysis.workload_name,
        "size": size,
        "tuning_size": effective_tuning_size,
        "seed": seed,
        "analysis": analysis.to_dict(),
        "grid": [asdict(configuration) for configuration in grid],
        "warmups": warmups,
        "tuning_repeats": tuning_repeats,
        "confirmation_repeats": confirmation_repeats,
        "holdout_repeats": holdout_repeats,
        "minimum_speedup": minimum_speedup,
        "minimum_relative_improvement": minimum_relative_improvement,
        "tuning": {
            "execution_order": tuning_order,
            "statistics": tuning_statistics,
            "runs": compact_tuning,
            "search_wall_seconds": tuning_seconds,
        },
        "selection": {
            "preliminary_selected_label": preliminary_selected_label,
            "selected_label": selected_label,
            "selected_configuration": (
                asdict(selected_configuration)
                if selected_configuration is not None
                else None
            ),
            "fixed_configuration": asdict(fixed_configuration),
            "scale_confirmation": confirmation,
        },
        "holdout": {
            "execution_order": holdout_order,
            "statistics": holdout_statistics,
            "runs": compact_holdout,
            "selected_key": selected_holdout_key,
            "selected_speedup": selected_holdout["speedup"],
            "fixed_speedup": fixed_holdout["speedup"],
            "selected_over_fixed": (
                float(fixed_holdout["median_seconds"])
                / float(selected_holdout["median_seconds"])
                if float(selected_holdout["median_seconds"]) > 0
                else 0.0
            ),
        },
        "amortization": {
            "search_wall_seconds": tuning_seconds,
            "median_savings_vs_serial_per_run_seconds": per_run_savings,
            "median_savings_vs_fixed_per_run_seconds": savings_over_fixed,
            "break_even_vs_serial_repetitions": break_even_vs_serial,
            "break_even_vs_fixed_repetitions": break_even_vs_fixed,
        },
        "warmup_records": warmup_records,
    }
    (destination / "configuration_search_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return report
