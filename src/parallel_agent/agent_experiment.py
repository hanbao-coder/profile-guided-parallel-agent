from __future__ import annotations

import json
import random
import traceback
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

from .agent_ablation import (
    aggregate_agent_rows,
    overall_agent_metrics,
    summarize_agent_runs,
)
from .agent_pipeline import run_agent_pipeline
from .deepseek_adapter import DeepSeekAdapter


@dataclass(frozen=True)
class ExperimentJob:
    workload: str
    source: str
    size: int
    feedback_mode: str
    replicate: int


def _read_trace_totals(run_dirs: list[Path]) -> tuple[int, int]:
    calls = 0
    tokens = 0
    for run_dir in run_dirs:
        trace_path = run_dir / "model_trace.json"
        if not trace_path.exists():
            continue
        trace = json.loads(trace_path.read_text(encoding="utf-8"))
        for call in trace.get("calls", []):
            calls += 1
            tokens += int(call.get("total_tokens") or 0)
    return calls, tokens


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def run_agent_experiment(
    config_path: str | Path,
    *,
    output_dir: str | Path,
    adapter_name: str = "deepseek",
    resume: bool = True,
) -> dict[str, Any]:
    config_file = Path(config_path).resolve()
    config = yaml.safe_load(config_file.read_text(encoding="utf-8"))
    root = config_file.parents[1]
    destination = Path(output_dir).resolve()
    destination.mkdir(parents=True, exist_ok=True)

    modes = list(config.get("feedback_modes", []))
    if not modes or any(
        mode not in {"one_shot", "correctness", "performance"}
        for mode in modes
    ):
        raise ValueError("feedback_modes must contain supported Agent modes")
    replicates = int(config.get("independent_runs", 1))
    if replicates < 1:
        raise ValueError("independent_runs must be positive")

    jobs = [
        ExperimentJob(
            workload=name,
            source=str((root / entry["path"]).resolve()),
            size=int(entry["size"]),
            feedback_mode=mode,
            replicate=replicate,
        )
        for name, entry in config.get("workloads", {}).items()
        for mode in modes
        for replicate in range(1, replicates + 1)
    ]
    if not jobs:
        raise ValueError("Experiment config contains no workloads")
    order_seed = int(config.get("order_seed", 42))
    random.Random(order_seed).shuffle(jobs)

    execution = config.get("execution", {})
    budget = config.get("budget", {})
    max_calls = int(budget.get("max_model_calls", 100))
    max_tokens = int(budget.get("max_total_tokens", 250_000))
    completed_dirs: list[Path] = []
    failed_jobs: list[dict[str, Any]] = []
    skipped_budget: list[dict[str, Any]] = []
    resumed_jobs = 0
    executed_this_invocation = 0

    for job in jobs:
        run_dir = (
            destination
            / job.workload
            / job.feedback_mode
            / f"run_{job.replicate:02d}"
        )
        report_path = run_dir / "run_report.json"
        if resume and report_path.exists():
            completed_dirs.append(run_dir)
            resumed_jobs += 1
            continue

        existing_dirs = [
            path.parent
            for path in destination.rglob("run_report.json")
        ]
        calls, tokens = _read_trace_totals(existing_dirs)
        if calls >= max_calls or tokens >= max_tokens:
            skipped_budget.append(
                {
                    **asdict(job),
                    "reason": "experiment budget reached before job start",
                    "calls_so_far": calls,
                    "tokens_so_far": tokens,
                }
            )
            continue

        run_dir.mkdir(parents=True, exist_ok=True)
        _write_json(run_dir / "job.json", asdict(job))
        try:
            adapter = (
                DeepSeekAdapter.from_env()
                if adapter_name == "deepseek"
                else None
            )
            run_agent_pipeline(
                job.source,
                output_dir=run_dir,
                size=job.size,
                seed=int(execution.get("seed", 42)) + job.replicate,
                workers=int(execution.get("workers", 4)),
                chunks=int(execution.get("chunks", 4)),
                timeout_seconds=float(
                    execution.get("timeout_seconds", 120)
                ),
                max_repair_attempts=int(
                    execution.get("max_repair_attempts", 1)
                ),
                feedback_mode=job.feedback_mode,
                performance_repeats=int(
                    execution.get("performance_repeats", 3)
                ),
                minimum_speedup=float(
                    execution.get("minimum_speedup", 1.05)
                ),
                max_performance_attempts=int(
                    execution.get("max_performance_attempts", 1)
                ),
                adapter=adapter,
            )
            completed_dirs.append(run_dir)
            executed_this_invocation += 1
        except Exception as exc:  # keep the experiment resumable
            failure = {
                **asdict(job),
                "error_type": type(exc).__name__,
                "message": str(exc),
                "traceback": traceback.format_exc(),
            }
            failed_jobs.append(failure)
            _write_json(run_dir / "experiment_error.json", failure)

        all_report_dirs = [
            path.parent
            for path in destination.rglob("run_report.json")
        ]
        calls, tokens = _read_trace_totals(all_report_dirs)
        _write_json(
            destination / "progress.json",
            {
                "completed": len(all_report_dirs),
                "total_jobs": len(jobs),
                "executed_this_invocation": executed_this_invocation,
                "resumed_jobs": resumed_jobs,
                "model_calls": calls,
                "total_tokens": tokens,
                "failed": len(failed_jobs),
                "budget_skipped": len(skipped_budget),
            },
        )

    report_dirs = [
        path.parent for path in destination.rglob("run_report.json")
    ]
    summary_path = destination / "agent_experiment_summary.csv"
    rows = summarize_agent_runs(
        [str(path) for path in sorted(report_dirs)], summary_path
    )
    aggregate_path = destination / "agent_experiment_aggregate.csv"
    aggregate = aggregate_agent_rows(rows, aggregate_path)
    overall_path = destination / "agent_experiment_overall.csv"
    overall = overall_agent_metrics(aggregate, overall_path)
    calls, tokens = _read_trace_totals(report_dirs)
    manifest = {
        "config": str(config_file),
        "adapter": adapter_name,
        "order_seed": order_seed,
        "total_jobs": len(jobs),
        "completed_jobs": len(report_dirs),
        "executed_this_invocation": executed_this_invocation,
        "resumed_jobs": resumed_jobs,
        "failed_jobs": failed_jobs,
        "budget_skipped": skipped_budget,
        "model_calls": calls,
        "total_tokens": tokens,
        "summary_csv": str(summary_path),
        "aggregate_csv": str(aggregate_path),
        "overall_csv": str(overall_path),
        "resumable": True,
    }
    _write_json(destination / "experiment_manifest.json", manifest)
    return {
        "manifest": manifest,
        "rows": rows,
        "aggregate": aggregate,
        "overall": overall,
    }
