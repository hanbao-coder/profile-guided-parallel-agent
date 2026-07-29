from __future__ import annotations

import json
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
    adapter: AgentAdapter | None = None,
) -> dict[str, Any]:
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
            "correct": None,
            "reason": plan.reasons,
            "attempts": [],
        }
        _write_model_traces(destination, selected_adapter)
        _write_json(destination / "run_report.json", report)
        return report

    current_plan = plan
    attempts: list[dict[str, Any]] = []
    correct = False
    for attempt_number in range(1, max_repair_attempts + 2):
        _write_json(destination / "parallel_plan.json", current_plan.to_dict())
        candidate = generate_candidate(current_plan, destination / "candidate.py")
        snapshot = destination / f"candidate_attempt_{attempt_number}.py"
        snapshot.write_text(candidate.read_text(encoding="utf-8"), encoding="utf-8")
        serial_run = execute_candidate(
            candidate,
            mode="serial",
            size=size,
            seed=seed,
            timeout_seconds=timeout_seconds,
        )
        parallel_run = execute_candidate(
            candidate,
            mode="parallel",
            size=size,
            seed=seed,
            timeout_seconds=timeout_seconds,
        )
        serial_result = (
            serial_run.payload.get("result") if serial_run.payload else None
        )
        parallel_result = (
            parallel_run.payload.get("result") if parallel_run.payload else None
        )
        correct = (
            serial_run.error_type is None
            and parallel_run.error_type is None
            and serial_result == parallel_result
        )
        attempt_record = {
            "attempt": attempt_number,
            "plan": current_plan.to_dict(),
            "serial": serial_run.to_dict(),
            "parallel": parallel_run.to_dict(),
            "correct": correct,
        }
        attempts.append(attempt_record)
        if correct:
            break
        if attempt_number > max_repair_attempts:
            break
        feedback = {
            "serial_error": serial_run.error_type,
            "serial_stderr": serial_run.stderr[-4000:],
            "parallel_error": parallel_run.error_type,
            "parallel_stderr": parallel_run.stderr[-4000:],
            "outputs_equal": serial_result == parallel_result,
        }
        _write_json(
            destination / f"repair_feedback_{attempt_number}.json", feedback
        )
        current_plan = selected_adapter.repair(
            current_plan, feedback, attempt=attempt_number
        )
    report = {
        "status": "accepted" if correct else "failed",
        "adapter": selected_adapter.name,
        "correct": correct,
        "repair_attempts_used": max(0, len(attempts) - 1),
        "attempts": attempts,
    }
    _write_model_traces(destination, selected_adapter)
    _write_json(destination / "run_report.json", report)
    return report
