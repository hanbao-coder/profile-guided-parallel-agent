from __future__ import annotations

import json
import random
import statistics
from pathlib import Path
from typing import Any

from .agent_adapter import AgentAdapter, OfflineHeuristicAdapter
from .candidate_executor import execute_candidate
from .generator import generate_candidate


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _write_model_traces(destination: Path, adapter: AgentAdapter) -> None:
    traces = getattr(adapter, "traces", None)
    if traces is not None:
        _write_json(
            destination / "model_trace.json",
            {
                "adapter": adapter.name,
                "calls": traces,
            },
        )


def _median_payload_runtime(runs: list[Any]) -> float | None:
    values = [
        float(run.payload["runtime_seconds"])
        for run in runs
        if run.payload and "runtime_seconds" in run.payload
    ]
    return statistics.median(values) if values else None


def _evaluate_candidate(
    candidate: Path,
    *,
    size: int,
    seed: int,
    timeout_seconds: float,
    repeats: int,
    order_seed: int,
) -> dict[str, Any]:
    serial_runs = []
    parallel_runs = []
    schedule = [
        mode
        for _ in range(max(1, repeats))
        for mode in ("serial", "parallel")
    ]
    random.Random(order_seed).shuffle(schedule)
    for mode in schedule:
        run = execute_candidate(
            candidate,
            mode=mode,
            size=size,
            seed=seed,
            timeout_seconds=timeout_seconds,
        )
        if mode == "serial":
            serial_runs.append(run)
        else:
            parallel_runs.append(run)

    serial_results = [
        run.payload.get("result")
        for run in serial_runs
        if run.payload and run.error_type is None
    ]
    parallel_results = [
        run.payload.get("result")
        for run in parallel_runs
        if run.payload and run.error_type is None
    ]
    all_runs = serial_runs + parallel_runs
    correct = (
        bool(serial_results)
        and len(serial_results) == len(serial_runs)
        and len(parallel_results) == len(parallel_runs)
        and all(run.error_type is None for run in all_runs)
        and all(result == serial_results[0] for result in serial_results)
        and all(result == serial_results[0] for result in parallel_results)
    )
    serial_total = statistics.median(
        run.elapsed_seconds for run in serial_runs
    )
    parallel_total = statistics.median(
        run.elapsed_seconds for run in parallel_runs
    )
    return {
        "serial_runs": serial_runs,
        "parallel_runs": parallel_runs,
        "correct": correct,
        "serial_total_median_seconds": serial_total,
        "parallel_total_median_seconds": parallel_total,
        "serial_compute_median_seconds": _median_payload_runtime(serial_runs),
        "parallel_compute_median_seconds": _median_payload_runtime(parallel_runs),
        "end_to_end_speedup": (
            serial_total / parallel_total if parallel_total > 0 else 0.0
        ),
        "execution_order": schedule,
    }


def _serial_fallback_plan(
    plan: Any, *, reason: str
) -> Any:
    from .artifacts import ParallelPlan

    fallback = ParallelPlan(
        schema_version=plan.schema_version,
        source_path=plan.source_path,
        parallelizable=False,
        backend="serial",
        strategy="serial",
        workers=1,
        chunks=1,
        correctness_gate=True,
        fallback="serial",
        reasons=plan.reasons + [reason],
    )
    fallback.validate()
    return fallback


def run_agent_pipeline(
    source_path: str | Path,
    *,
    output_dir: str | Path,
    size: int,
    seed: int,
    workers: int,
    chunks: int,
    timeout_seconds: float = 120.0,
    max_repair_attempts: int = 2,
    feedback_mode: str = "correctness",
    performance_repeats: int = 3,
    minimum_speedup: float = 1.05,
    max_performance_attempts: int = 1,
    adapter: AgentAdapter | None = None,
) -> dict[str, Any]:
    if feedback_mode not in {"one_shot", "correctness", "performance"}:
        raise ValueError(
            "feedback_mode must be one_shot, correctness, or performance"
        )
    if performance_repeats < 1:
        raise ValueError("performance_repeats must be positive")
    if minimum_speedup <= 0:
        raise ValueError("minimum_speedup must be positive")
    selected_adapter = adapter or OfflineHeuristicAdapter()
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)

    analysis = selected_adapter.analyze(source_path)
    plan = selected_adapter.plan(analysis, workers=workers, chunks=chunks)
    _write_json(destination / "analysis.json", analysis.to_dict())
    _write_json(destination / "parallel_plan.json", plan.to_dict())

    if not plan.parallelizable:
        report = {
            "status": "rejected",
            "adapter": selected_adapter.name,
            "feedback_mode": feedback_mode,
            "correct": None,
            "selected_mode": "serial",
            "reason": plan.reasons,
            "attempts": [],
        }
        _write_model_traces(destination, selected_adapter)
        _write_json(destination / "run_report.json", report)
        return report

    current_plan = plan
    attempts: list[dict[str, Any]] = []
    correct = False
    selected_mode: str | None = None
    correctness_repairs_used = 0
    performance_attempts_used = 0
    performance_gate_passed: bool | None = None
    attempt_number = 0
    while True:
        attempt_number += 1
        _write_json(destination / "parallel_plan.json", current_plan.to_dict())
        candidate = generate_candidate(current_plan, destination / "candidate.py")
        snapshot = destination / f"candidate_attempt_{attempt_number}.py"
        snapshot.write_text(candidate.read_text(encoding="utf-8"), encoding="utf-8")
        evaluation = _evaluate_candidate(
            candidate,
            size=size,
            seed=seed,
            timeout_seconds=timeout_seconds,
            repeats=(
                performance_repeats
                if feedback_mode == "performance"
                else 1
            ),
            order_seed=seed + attempt_number,
        )
        serial_run = evaluation["serial_runs"][0]
        parallel_run = evaluation["parallel_runs"][0]
        correct = evaluation["correct"]
        performance = {
            "serial_total_median_seconds": evaluation[
                "serial_total_median_seconds"
            ],
            "parallel_total_median_seconds": evaluation[
                "parallel_total_median_seconds"
            ],
            "serial_compute_median_seconds": evaluation[
                "serial_compute_median_seconds"
            ],
            "parallel_compute_median_seconds": evaluation[
                "parallel_compute_median_seconds"
            ],
            "end_to_end_speedup": evaluation["end_to_end_speedup"],
            "minimum_speedup": minimum_speedup,
            "beneficial": (
                correct
                and evaluation["end_to_end_speedup"] >= minimum_speedup
            ),
            "repeats": (
                performance_repeats
                if feedback_mode == "performance"
                else 1
            ),
            "execution_order": evaluation["execution_order"],
        }
        attempt_record = {
            "attempt": attempt_number,
            "plan": current_plan.to_dict(),
            "serial": serial_run.to_dict(),
            "parallel": parallel_run.to_dict(),
            "serial_runs": [
                run.to_dict() for run in evaluation["serial_runs"]
            ],
            "parallel_runs": [
                run.to_dict() for run in evaluation["parallel_runs"]
            ],
            "correct": correct,
            "performance": performance,
        }
        attempts.append(attempt_record)
        if not correct:
            can_repair = (
                feedback_mode in {"correctness", "performance"}
                and correctness_repairs_used < max_repair_attempts
            )
            if not can_repair:
                break
            correctness_repairs_used += 1
            feedback = {
                "serial_error": serial_run.error_type,
                "serial_stderr": serial_run.stderr[-4000:],
                "parallel_error": parallel_run.error_type,
                "parallel_stderr": parallel_run.stderr[-4000:],
                "outputs_equal": False,
            }
            _write_json(
                destination
                / f"repair_feedback_{correctness_repairs_used}.json",
                feedback,
            )
            current_plan = selected_adapter.repair(
                current_plan,
                feedback,
                attempt=correctness_repairs_used,
            )
            continue

        if feedback_mode != "performance":
            selected_mode = "parallel"
            break

        performance_gate_passed = performance["beneficial"]
        if performance_gate_passed:
            selected_mode = "parallel"
            break

        performance_feedback = {
            **performance,
            "workers": current_plan.workers,
            "chunks": current_plan.chunks,
            "task_count": (
                parallel_run.payload.get("task_count")
                if parallel_run.payload
                else None
            ),
            "decision_required": (
                "Choose a new worker/chunk plan or fall back to serial."
            ),
        }
        next_feedback_index = performance_attempts_used + 1
        _write_json(
            destination
            / f"performance_feedback_{next_feedback_index}.json",
            performance_feedback,
        )
        if performance_attempts_used >= max_performance_attempts:
            current_plan = _serial_fallback_plan(
                current_plan,
                reason=(
                    "Measured performance remained below the minimum speedup "
                    f"after {performance_attempts_used} optimization attempt(s)."
                ),
            )
            _write_json(
                destination / "parallel_plan.json", current_plan.to_dict()
            )
            selected_mode = "serial"
            break

        performance_attempts_used += 1
        current_plan = selected_adapter.optimize_performance(
            current_plan,
            performance_feedback,
            attempt=performance_attempts_used,
        )
        _write_json(destination / "parallel_plan.json", current_plan.to_dict())
        if not current_plan.parallelizable:
            selected_mode = "serial"
            break

    report = {
        "status": "accepted" if correct else "failed",
        "adapter": selected_adapter.name,
        "feedback_mode": feedback_mode,
        "correct": correct,
        "selected_mode": selected_mode,
        "performance_gate_passed": performance_gate_passed,
        "repair_attempts_used": correctness_repairs_used,
        "performance_attempts_used": performance_attempts_used,
        "final_plan": current_plan.to_dict(),
        "attempts": attempts,
    }
    _write_model_traces(destination, selected_adapter)
    _write_json(destination / "run_report.json", report)
    return report
