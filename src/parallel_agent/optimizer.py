from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence


@dataclass(frozen=True)
class BackendCalibration:
    workers: int
    startup_seconds: float
    task_overhead_seconds: float


@dataclass(frozen=True)
class ExecutionPlan:
    selected_mode: str
    workers: int
    chunks: int
    predicted_serial_seconds: float
    predicted_warm_seconds: float
    predicted_total_seconds: float


def worker_candidates(max_workers: int) -> list[int]:
    if max_workers < 1:
        raise ValueError("max_workers must be positive")
    values = {1, max_workers}
    power = 2
    while power < max_workers:
        values.add(power)
        power *= 2
    return sorted(values)


def choose_execution_plan(
    *,
    item_count: int,
    item_runtime_seconds: float,
    calibrations: Mapping[int, BackendCalibration],
    chunks_per_worker: Sequence[int] = (1, 2, 4, 8),
    min_expected_speedup: float = 1.05,
    serialization_seconds: float = 0.0,
) -> ExecutionPlan:
    if item_count <= 0:
        return ExecutionPlan("serial_fallback", 1, 1, 0.0, 0.0, 0.0)
    if not calibrations:
        raise ValueError("At least one backend calibration is required")

    serial = item_count * max(item_runtime_seconds, 1e-9)
    best: ExecutionPlan | None = None
    for workers, calibration in calibrations.items():
        for multiplier in chunks_per_worker:
            chunks = min(item_count, max(1, workers * multiplier))
            waves = (chunks + workers - 1) // workers
            ideal_waves = chunks / workers
            imbalance_factor = waves / ideal_waves
            warm = (
                serial / workers * imbalance_factor
                + chunks * calibration.task_overhead_seconds
                + serialization_seconds
            )
            total = calibration.startup_seconds + warm
            candidate = ExecutionPlan(
                selected_mode="optimized",
                workers=workers,
                chunks=chunks,
                predicted_serial_seconds=serial,
                predicted_warm_seconds=warm,
                predicted_total_seconds=total,
            )
            if best is None or candidate.predicted_total_seconds < best.predicted_total_seconds:
                best = candidate

    assert best is not None
    if best.predicted_total_seconds * min_expected_speedup >= serial:
        return ExecutionPlan(
            selected_mode="serial_fallback",
            workers=1,
            chunks=1,
            predicted_serial_seconds=serial,
            predicted_warm_seconds=serial,
            predicted_total_seconds=serial,
        )
    return best
