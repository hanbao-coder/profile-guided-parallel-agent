from __future__ import annotations

import json
import random
import statistics
from pathlib import Path
from typing import Any

from .agent_adapter import AgentAdapter, OfflineHeuristicAdapter
from .artifacts import AnalysisArtifact, ParallelPlan
from .candidate_executor import execute_candidate
from .controlled_codegen import (
    GeneratedCodeSafetyError,
    generate_controlled_candidate,
)
from .configuration_search import run_configuration_search
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


def _quartiles(values: list[float]) -> tuple[float, float]:
    if len(values) == 1:
        return values[0], values[0]
    q1, _, q3 = statistics.quantiles(
        values, n=4, method="inclusive"
    )
    return q1, q3


def _evaluate_candidate(
    candidate: Path,
    *,
    size: int,
    seed: int,
    timeout_seconds: float,
    repeats: int,
    order_seed: int,
    max_parallel_tasks: int | None = None,
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
    result_correct = (
        bool(serial_results)
        and len(serial_results) == len(serial_runs)
        and len(parallel_results) == len(parallel_runs)
        and all(run.error_type is None for run in all_runs)
        and all(result == serial_results[0] for result in serial_results)
        and all(result == serial_results[0] for result in parallel_results)
    )
    task_count_values = [
        run.payload.get("task_count")
        for run in parallel_runs
        if run.payload is not None
    ]
    task_count_valid = (
        len(task_count_values) == len(parallel_runs)
        and all(
            isinstance(value, int)
            and not isinstance(value, bool)
            and value >= 1
            and (
                max_parallel_tasks is None
                or value <= max_parallel_tasks
            )
            for value in task_count_values
        )
    )
    validation_errors: list[str] = []
    if not result_correct:
        validation_errors.append(
            "serial and parallel results are missing, failed, or unequal"
        )
    if not task_count_valid:
        validation_errors.append(
            "parallel task_count must be an integer between 1 and the "
            f"configured chunk count ({max_parallel_tasks})"
        )
    correct = result_correct and task_count_valid
    serial_values = [run.elapsed_seconds for run in serial_runs]
    parallel_values = [run.elapsed_seconds for run in parallel_runs]
    serial_total = statistics.median(serial_values)
    parallel_total = statistics.median(parallel_values)
    serial_q1, serial_q3 = _quartiles(serial_values)
    parallel_q1, parallel_q3 = _quartiles(parallel_values)
    return {
        "serial_runs": serial_runs,
        "parallel_runs": parallel_runs,
        "correct": correct,
        "result_correct": result_correct,
        "task_count_valid": task_count_valid,
        "validation_errors": validation_errors,
        "serial_total_median_seconds": serial_total,
        "parallel_total_median_seconds": parallel_total,
        "serial_total_q1_seconds": serial_q1,
        "serial_total_q3_seconds": serial_q3,
        "parallel_total_q1_seconds": parallel_q1,
        "parallel_total_q3_seconds": parallel_q3,
        "serial_compute_median_seconds": _median_payload_runtime(serial_runs),
        "parallel_compute_median_seconds": _median_payload_runtime(parallel_runs),
        "end_to_end_speedup": (
            serial_total / parallel_total if parallel_total > 0 else 0.0
        ),
        "conservative_speedup": (
            serial_q1 / parallel_q3 if parallel_q3 > 0 else 0.0
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


def _configuration_search_summary(
    report: dict[str, Any],
) -> dict[str, Any]:
    selection = report.get("selection", {})
    holdout = report.get("holdout", {})
    return {
        "status": report.get("status"),
        "report_path": "configuration_search/configuration_search_report.json",
        "selected_label": selection.get(
            "selected_label", report.get("selected_label")
        ),
        "selected_configuration": selection.get("selected_configuration"),
        "selected_speedup": holdout.get("selected_speedup"),
        "fixed_speedup": holdout.get("fixed_speedup"),
        "selected_over_fixed": holdout.get("selected_over_fixed"),
        "cache": report.get("cache"),
    }


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
    generation_mode: str = "template",
    max_code_repair_attempts: int = 2,
    performance_controller: str = "llm_feedback",
    search_tuning_size: int | None = None,
    search_tuning_repeats: int = 2,
    search_confirmation_repeats: int = 2,
    search_holdout_repeats: int = 5,
    search_warmups: int = 1,
    search_minimum_relative_improvement: float = 1.05,
    search_cache_dir: str | Path | None = None,
    adapter: AgentAdapter | None = None,
    analysis_override: AnalysisArtifact | None = None,
    plan_override: ParallelPlan | None = None,
) -> dict[str, Any]:
    if feedback_mode not in {"one_shot", "correctness", "performance"}:
        raise ValueError(
            "feedback_mode must be one_shot, correctness, or performance"
        )
    if performance_repeats < 1:
        raise ValueError("performance_repeats must be positive")
    if minimum_speedup <= 0:
        raise ValueError("minimum_speedup must be positive")
    if generation_mode not in {"template", "llm"}:
        raise ValueError("generation_mode must be template or llm")
    if performance_controller not in {
        "llm_feedback",
        "configuration_search",
    }:
        raise ValueError(
            "performance_controller must be llm_feedback or "
            "configuration_search"
        )
    if (
        performance_controller == "configuration_search"
        and feedback_mode != "performance"
    ):
        raise ValueError(
            "configuration_search controller requires performance feedback mode"
        )
    if (
        performance_controller == "configuration_search"
        and generation_mode != "template"
    ):
        raise ValueError(
            "configuration_search currently requires deterministic template "
            "generation so the measured and deployed candidates are identical"
        )
    if (analysis_override is None) != (plan_override is None):
        raise ValueError(
            "analysis_override and plan_override must be provided together"
        )
    selected_adapter = adapter or OfflineHeuristicAdapter()
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)

    if analysis_override is not None and plan_override is not None:
        analysis_override.validate()
        plan_override.validate()
        expected_source = Path(source_path).resolve()
        if Path(analysis_override.source_path).resolve() != expected_source:
            raise ValueError("analysis_override source does not match source_path")
        if Path(plan_override.source_path).resolve() != expected_source:
            raise ValueError("plan_override source does not match source_path")
        analysis = analysis_override
        plan = plan_override
    else:
        analysis = selected_adapter.analyze(source_path)
        plan = selected_adapter.plan(
            analysis, workers=workers, chunks=chunks
        )
    _write_json(destination / "analysis.json", analysis.to_dict())
    _write_json(destination / "parallel_plan.json", plan.to_dict())

    if not plan.parallelizable:
        report = {
            "status": "rejected",
            "adapter": selected_adapter.name,
            "feedback_mode": feedback_mode,
            "generation_mode": generation_mode,
            "performance_controller": performance_controller,
            "correct": None,
            "selected_mode": "serial",
            "reason": plan.reasons,
            "attempts": [],
        }
        _write_model_traces(destination, selected_adapter)
        _write_json(destination / "run_report.json", report)
        return report

    current_plan = plan
    configuration_search_report: dict[str, Any] | None = None
    if performance_controller == "configuration_search":
        configuration_search_report = run_configuration_search(
            source_path,
            output_dir=destination / "configuration_search",
            size=size,
            tuning_size=search_tuning_size,
            seed=seed,
            max_workers=workers,
            tuning_repeats=search_tuning_repeats,
            confirmation_repeats=search_confirmation_repeats,
            holdout_repeats=search_holdout_repeats,
            warmups=search_warmups,
            timeout_seconds=timeout_seconds,
            minimum_speedup=minimum_speedup,
            minimum_relative_improvement=(
                search_minimum_relative_improvement
            ),
            order_seed=seed,
            cache_dir=search_cache_dir,
        )
        search_summary = _configuration_search_summary(
            configuration_search_report
        )
        selected = configuration_search_report.get(
            "selection", {}
        ).get("selected_configuration")
        if (
            configuration_search_report.get("status") != "completed"
            or selected is None
        ):
            current_plan = _serial_fallback_plan(
                current_plan,
                reason=(
                    "Deterministic configuration search rejected parallel "
                    "execution or found no robust full-scale gain."
                ),
            )
            _write_json(
                destination / "parallel_plan.json", current_plan.to_dict()
            )
            report = {
                "status": "accepted",
                "adapter": selected_adapter.name,
                "feedback_mode": feedback_mode,
                "generation_mode": generation_mode,
                "performance_controller": performance_controller,
                "correct": True,
                "selected_mode": "serial",
                "performance_gate_passed": False,
                "repair_attempts_used": 0,
                "code_repair_attempts_used": 0,
                "performance_attempts_used": 0,
                "final_plan": current_plan.to_dict(),
                "configuration_search": search_summary,
                "attempts": [],
            }
            _write_model_traces(destination, selected_adapter)
            _write_json(destination / "run_report.json", report)
            return report
        current_plan = ParallelPlan(
            schema_version=plan.schema_version,
            source_path=plan.source_path,
            parallelizable=True,
            backend="multiprocessing",
            strategy="map_reduce",
            workers=int(selected["workers"]),
            chunks=int(selected["chunks"]),
            correctness_gate=True,
            fallback="serial",
            reasons=plan.reasons
            + [
                "Deterministic multi-scale search selected "
                f"{selected['workers']} worker(s) and "
                f"{selected['chunks']} chunk(s)."
            ],
        )
        current_plan.validate()
        _write_json(destination / "parallel_plan.json", current_plan.to_dict())
    attempts: list[dict[str, Any]] = []
    correct = False
    selected_mode: str | None = None
    correctness_repairs_used = 0
    performance_attempts_used = 0
    performance_gate_passed: bool | None = None
    parallel_impl_code: str | None = None
    code_repairs_used = 0
    attempt_number = 0
    while True:
        attempt_number += 1
        _write_json(destination / "parallel_plan.json", current_plan.to_dict())
        if generation_mode == "llm":
            if parallel_impl_code is None:
                parallel_impl_code = selected_adapter.generate_parallel_impl(
                    current_plan
                )
            impl_path = (
                destination / f"parallel_impl_attempt_{attempt_number}.py"
            )
            impl_path.write_text(parallel_impl_code, encoding="utf-8")
            try:
                candidate, safety_report = generate_controlled_candidate(
                    current_plan,
                    parallel_impl_code,
                    destination / "candidate.py",
                )
                _write_json(
                    destination
                    / f"code_safety_attempt_{attempt_number}.json",
                    safety_report,
                )
            except GeneratedCodeSafetyError as exc:
                safety_feedback = {
                    "error_type": "generated_code_safety_error",
                    "message": str(exc),
                    "allowed_top_level_functions": [
                        "partition_items",
                        "execute_parallel",
                    ],
                }
                attempts.append(
                    {
                        "attempt": attempt_number,
                        "plan": current_plan.to_dict(),
                        "generation_error": safety_feedback,
                        "correct": False,
                    }
                )
                _write_json(
                    destination
                    / f"code_feedback_{code_repairs_used + 1}.json",
                    safety_feedback,
                )
                can_repair_code = (
                    feedback_mode in {"correctness", "performance"}
                    and code_repairs_used < max_code_repair_attempts
                )
                if not can_repair_code:
                    break
                code_repairs_used += 1
                parallel_impl_code = (
                    selected_adapter.repair_parallel_impl(
                        current_plan,
                        parallel_impl_code,
                        safety_feedback,
                        attempt=code_repairs_used,
                    )
                )
                continue
        else:
            candidate = generate_candidate(
                current_plan, destination / "candidate.py"
            )
        snapshot = destination / f"candidate_attempt_{attempt_number}.py"
        snapshot.write_text(candidate.read_text(encoding="utf-8"), encoding="utf-8")
        evaluation = _evaluate_candidate(
            candidate,
            size=size,
            seed=seed,
            timeout_seconds=timeout_seconds,
            # Measurement count is identical across ablation groups. The
            # groups differ in which feedback they are allowed to consume.
            repeats=performance_repeats,
            order_seed=seed + attempt_number,
            max_parallel_tasks=current_plan.chunks,
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
            "serial_total_q1_seconds": evaluation[
                "serial_total_q1_seconds"
            ],
            "serial_total_q3_seconds": evaluation[
                "serial_total_q3_seconds"
            ],
            "parallel_total_q1_seconds": evaluation[
                "parallel_total_q1_seconds"
            ],
            "parallel_total_q3_seconds": evaluation[
                "parallel_total_q3_seconds"
            ],
            "serial_compute_median_seconds": evaluation[
                "serial_compute_median_seconds"
            ],
            "parallel_compute_median_seconds": evaluation[
                "parallel_compute_median_seconds"
            ],
            "end_to_end_speedup": evaluation["end_to_end_speedup"],
            "conservative_speedup": evaluation["conservative_speedup"],
            "minimum_speedup": minimum_speedup,
            "beneficial": (
                correct
                and evaluation["end_to_end_speedup"] >= minimum_speedup
                and evaluation["conservative_speedup"] >= 1.0
            ),
            "repeats": performance_repeats,
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
            "result_correct": evaluation["result_correct"],
            "task_count_valid": evaluation["task_count_valid"],
            "validation_errors": evaluation["validation_errors"],
            "performance": performance,
        }
        attempts.append(attempt_record)
        if not correct:
            if (
                generation_mode == "llm"
                and feedback_mode in {"correctness", "performance"}
                and code_repairs_used < max_code_repair_attempts
            ):
                code_repairs_used += 1
                code_feedback = {
                    "error_type": "runtime_or_correctness_failure",
                    "serial_error": serial_run.error_type,
                    "serial_stderr": serial_run.stderr[-4000:],
                    "parallel_error": parallel_run.error_type,
                    "parallel_stderr": parallel_run.stderr[-4000:],
                    "outputs_equal": evaluation["result_correct"],
                    "task_count_valid": evaluation[
                        "task_count_valid"
                    ],
                    "validation_errors": evaluation[
                        "validation_errors"
                    ],
                }
                _write_json(
                    destination
                    / f"code_feedback_{code_repairs_used}.json",
                    code_feedback,
                )
                parallel_impl_code = (
                    selected_adapter.repair_parallel_impl(
                        current_plan,
                        parallel_impl_code or "",
                        code_feedback,
                        attempt=code_repairs_used,
                    )
                )
                continue
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

        if (
            feedback_mode != "performance"
            or performance_controller == "configuration_search"
        ):
            selected_mode = "parallel"
            performance_gate_passed = (
                performance["beneficial"]
                if performance_controller == "configuration_search"
                else None
            )
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
        "generation_mode": generation_mode,
        "performance_controller": performance_controller,
        "correct": correct,
        "selected_mode": selected_mode,
        "performance_gate_passed": performance_gate_passed,
        "repair_attempts_used": correctness_repairs_used,
        "code_repair_attempts_used": code_repairs_used,
        "performance_attempts_used": performance_attempts_used,
        "final_plan": current_plan.to_dict(),
        "attempts": attempts,
    }
    if configuration_search_report is not None:
        report["configuration_search"] = _configuration_search_summary(
            configuration_search_report
        )
    _write_model_traces(destination, selected_adapter)
    _write_json(destination / "run_report.json", report)
    return report
