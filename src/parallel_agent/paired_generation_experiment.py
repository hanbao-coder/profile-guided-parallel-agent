from __future__ import annotations

import csv
import json
import random
import statistics
import traceback
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

import yaml
import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np

from .agent_ablation import (
    PRICE_PER_MILLION_TOKENS,
    PRICING_SNAPSHOT_DATE,
)
from .agent_adapter import AgentAdapter, OfflineHeuristicAdapter
from .agent_pipeline import run_agent_pipeline
from .candidate_executor import CandidateRun, execute_candidate
from .deepseek_adapter import DeepSeekAdapter


@dataclass(frozen=True)
class PairedGenerationJob:
    workload: str
    source: str
    size: int
    replicate: int


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _quartiles(values: list[float]) -> tuple[float, float]:
    if len(values) == 1:
        return values[0], values[0]
    q1, _, q3 = statistics.quantiles(
        values, n=4, method="inclusive"
    )
    return q1, q3


def _trace_cost(calls: list[dict[str, Any]]) -> float:
    return sum(
        (
            int(call.get("prompt_tokens") or 0)
            * PRICE_PER_MILLION_TOKENS.get(
                str(call.get("model")), {"input": 0.0}
            )["input"]
            + int(call.get("completion_tokens") or 0)
            * PRICE_PER_MILLION_TOKENS.get(
                str(call.get("model")), {"output": 0.0}
            )["output"]
        )
        / 1_000_000
        for call in calls
    )


def _read_calls(run_dir: Path) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for trace_path in sorted(run_dir.rglob("model_trace.json")):
        payload = json.loads(trace_path.read_text(encoding="utf-8"))
        calls.extend(payload.get("calls", []))
    return calls


def _paired_measurement(
    *,
    template_candidate: Path,
    llm_candidate: Path,
    size: int,
    seed: int,
    timeout_seconds: float,
    warmups: int,
    repeats: int,
    order_seed: int,
) -> dict[str, Any]:
    if warmups < 0:
        raise ValueError("warmups cannot be negative")
    if repeats < 1:
        raise ValueError("repeats must be positive")
    candidates = {
        "serial": (template_candidate, "serial"),
        "template": (template_candidate, "parallel"),
        "llm": (llm_candidate, "parallel"),
    }
    warmup_records: list[dict[str, Any]] = []
    for _ in range(warmups):
        for label, (candidate, mode) in candidates.items():
            result = execute_candidate(
                candidate,
                mode=mode,
                size=size,
                seed=seed,
                timeout_seconds=timeout_seconds,
            )
            warmup_records.append({"label": label, **result.to_dict()})

    schedule = [
        label
        for _ in range(repeats)
        for label in ("serial", "template", "llm")
    ]
    random.Random(order_seed).shuffle(schedule)
    runs: dict[str, list[CandidateRun]] = {
        "serial": [],
        "template": [],
        "llm": [],
    }
    ordered_records: list[dict[str, Any]] = []
    for label in schedule:
        candidate, mode = candidates[label]
        result = execute_candidate(
            candidate,
            mode=mode,
            size=size,
            seed=seed,
            timeout_seconds=timeout_seconds,
        )
        runs[label].append(result)
        ordered_records.append({"label": label, **result.to_dict()})

    valid_results: dict[str, list[Any]] = {}
    for label, group in runs.items():
        valid_results[label] = [
            run.payload.get("result")
            for run in group
            if run.error_type is None and run.payload is not None
        ]
    reference = (
        valid_results["serial"][0] if valid_results["serial"] else None
    )
    correctness = {
        label: (
            len(valid_results[label]) == len(runs[label])
            and bool(valid_results[label])
            and all(value == reference for value in valid_results[label])
        )
        for label in runs
    }
    timings = {
        label: [run.elapsed_seconds for run in group]
        for label, group in runs.items()
    }
    medians = {
        label: statistics.median(values)
        for label, values in timings.items()
    }
    quartiles = {
        label: _quartiles(values)
        for label, values in timings.items()
    }
    template_speedup = (
        medians["serial"] / medians["template"]
        if medians["template"] > 0
        else 0.0
    )
    llm_speedup = (
        medians["serial"] / medians["llm"]
        if medians["llm"] > 0
        else 0.0
    )
    llm_over_template = (
        medians["template"] / medians["llm"]
        if medians["llm"] > 0
        else 0.0
    )
    return {
        "warmups": warmups,
        "repeats": repeats,
        "execution_order": schedule,
        "warmup_records": warmup_records,
        "runs": ordered_records,
        "correctness": correctness,
        "median_seconds": medians,
        "q1_seconds": {
            label: values[0] for label, values in quartiles.items()
        },
        "q3_seconds": {
            label: values[1] for label, values in quartiles.items()
        },
        "template_speedup": template_speedup,
        "llm_speedup": llm_speedup,
        "llm_over_template": llm_over_template,
        "conservative_llm_over_template": (
            quartiles["template"][0] / quartiles["llm"][1]
            if quartiles["llm"][1] > 0
            else 0.0
        ),
    }


def _summarize_pairs(
    pair_dirs: list[Path], destination: Path
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for pair_dir in sorted(pair_dirs):
        report = json.loads(
            (pair_dir / "pair_report.json").read_text(encoding="utf-8")
        )
        shared_calls = _read_calls(pair_dir / "shared")
        generation_calls = _read_calls(pair_dir / "llm")
        calls = shared_calls + generation_calls
        measurement = report["measurement"]
        rows.append(
            {
                "run": pair_dir.name,
                "workload": report["workload"],
                "replicate": report["replicate"],
                "status": report.get("status", "completed"),
                "shared_plan": report["shared_plan"],
                "template_correct": measurement["correctness"]["template"],
                "llm_correct": measurement["correctness"]["llm"],
                "template_median_seconds": measurement["median_seconds"][
                    "template"
                ],
                "llm_median_seconds": measurement["median_seconds"]["llm"],
                "template_speedup": measurement["template_speedup"],
                "llm_speedup": measurement["llm_speedup"],
                "llm_over_template": measurement["llm_over_template"],
                "conservative_llm_over_template": measurement[
                    "conservative_llm_over_template"
                ],
                "llm_code_repairs": report["llm_report"].get(
                    "code_repair_attempts_used", 0
                ),
                "llm_safety_rejections": sum(
                    "generation_error" in attempt
                    for attempt in report["llm_report"].get("attempts", [])
                ),
                "model_calls": len(calls),
                "total_tokens": sum(
                    int(call.get("total_tokens") or 0) for call in calls
                ),
                "shared_model_calls": len(shared_calls),
                "shared_tokens": sum(
                    int(call.get("total_tokens") or 0)
                    for call in shared_calls
                ),
                "llm_generation_calls": len(generation_calls),
                "llm_generation_tokens": sum(
                    int(call.get("total_tokens") or 0)
                    for call in generation_calls
                ),
                "llm_generation_cost_upper_usd": _trace_cost(
                    generation_calls
                ),
                "estimated_cost_upper_usd": _trace_cost(calls),
                "pricing_snapshot_date": PRICING_SNAPSHOT_DATE,
            }
        )
    completed_paths = {path.resolve() for path in pair_dirs}
    for error_path in sorted(destination.rglob("experiment_error.json")):
        pair_dir = error_path.parent
        if pair_dir.resolve() in completed_paths:
            continue
        failure = json.loads(error_path.read_text(encoding="utf-8"))
        template_path = pair_dir / "template" / "run_report.json"
        llm_path = pair_dir / "llm" / "run_report.json"
        template_report = (
            json.loads(template_path.read_text(encoding="utf-8"))
            if template_path.exists()
            else {}
        )
        llm_report = (
            json.loads(llm_path.read_text(encoding="utf-8"))
            if llm_path.exists()
            else {}
        )
        shared_calls = _read_calls(pair_dir / "shared")
        generation_calls = _read_calls(pair_dir / "llm")
        calls = shared_calls + generation_calls
        rows.append(
            {
                "run": pair_dir.name,
                "workload": failure.get("workload", "unknown"),
                "replicate": failure.get("replicate"),
                "status": "failed",
                "shared_plan": (
                    pair_dir.joinpath(
                        "shared", "parallel_plan.json"
                    ).exists()
                ),
                "template_correct": template_report.get("correct", False),
                "llm_correct": llm_report.get("correct", False),
                "template_median_seconds": None,
                "llm_median_seconds": None,
                "template_speedup": None,
                "llm_speedup": None,
                "llm_over_template": None,
                "conservative_llm_over_template": None,
                "llm_code_repairs": llm_report.get(
                    "code_repair_attempts_used", 0
                ),
                "llm_safety_rejections": sum(
                    "generation_error" in attempt
                    for attempt in llm_report.get("attempts", [])
                ),
                "model_calls": len(calls),
                "total_tokens": sum(
                    int(call.get("total_tokens") or 0) for call in calls
                ),
                "shared_model_calls": len(shared_calls),
                "shared_tokens": sum(
                    int(call.get("total_tokens") or 0)
                    for call in shared_calls
                ),
                "llm_generation_calls": len(generation_calls),
                "llm_generation_tokens": sum(
                    int(call.get("total_tokens") or 0)
                    for call in generation_calls
                ),
                "llm_generation_cost_upper_usd": _trace_cost(
                    generation_calls
                ),
                "estimated_cost_upper_usd": _trace_cost(calls),
                "pricing_snapshot_date": PRICING_SNAPSHOT_DATE,
            }
        )
    rows.sort(
        key=lambda row: (
            str(row["workload"]),
            int(row.get("replicate") or 0),
        )
    )

    summary_path = destination / "paired_generation_summary.csv"
    if rows:
        with summary_path.open(
            "w", encoding="utf-8-sig", newline=""
        ) as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(str(row["workload"]), []).append(row)
    aggregate: list[dict[str, Any]] = []
    for workload, group in sorted(groups.items()):
        comparisons = [
            float(row["llm_over_template"])
            for row in group
            if row.get("llm_over_template") not in {None, ""}
        ]
        template_speedups = [
            float(row["template_speedup"])
            for row in group
            if row.get("template_speedup") not in {None, ""}
        ]
        llm_speedups = [
            float(row["llm_speedup"])
            for row in group
            if row.get("llm_speedup") not in {None, ""}
        ]
        aggregate.append(
            {
                "workload": workload,
                "runs": len(group),
                "measured_pairs": len(comparisons),
                "generation_failure_rate": sum(
                    row.get("status") != "completed" for row in group
                )
                / len(group),
                "template_correct_rate": sum(
                    str(row["template_correct"]).lower() == "true"
                    for row in group
                )
                / len(group),
                "llm_correct_rate": sum(
                    str(row["llm_correct"]).lower() == "true"
                    for row in group
                )
                / len(group),
                "template_speedup_mean": (
                    statistics.fmean(template_speedups)
                    if template_speedups
                    else None
                ),
                "llm_speedup_mean": (
                    statistics.fmean(llm_speedups)
                    if llm_speedups
                    else None
                ),
                "llm_over_template_mean": (
                    statistics.fmean(comparisons)
                    if comparisons
                    else None
                ),
                "llm_over_template_stdev": (
                    statistics.stdev(comparisons)
                    if len(comparisons) > 1
                    else 0.0
                ),
                "llm_win_rate": (
                    sum(value > 1.0 for value in comparisons)
                    / len(comparisons)
                    if comparisons
                    else None
                ),
                "model_calls_total": sum(
                    int(row["model_calls"]) for row in group
                ),
                "tokens_total": sum(
                    int(row["total_tokens"]) for row in group
                ),
                "llm_generation_calls_total": sum(
                    int(row["llm_generation_calls"]) for row in group
                ),
                "llm_generation_tokens_total": sum(
                    int(row["llm_generation_tokens"]) for row in group
                ),
                "llm_generation_cost_upper_usd_total": sum(
                    float(row["llm_generation_cost_upper_usd"])
                    for row in group
                ),
                "estimated_cost_upper_usd_total": sum(
                    float(row["estimated_cost_upper_usd"])
                    for row in group
                ),
            }
        )
    aggregate_path = destination / "paired_generation_aggregate.csv"
    if aggregate:
        with aggregate_path.open(
            "w", encoding="utf-8-sig", newline=""
        ) as handle:
            writer = csv.DictWriter(handle, fieldnames=list(aggregate[0]))
            writer.writeheader()
            writer.writerows(aggregate)

    total_runs = len(rows)
    overall = {
        "workloads": len(groups),
        "runs": total_runs,
        "template_correct_rate": (
            sum(
                str(row["template_correct"]).lower() == "true"
                for row in rows
            )
            / total_runs
            if total_runs
            else None
        ),
        "llm_correct_rate": (
            sum(
                str(row["llm_correct"]).lower() == "true"
                for row in rows
            )
            / total_runs
            if total_runs
            else None
        ),
        "llm_over_template_macro_mean": (
            statistics.fmean(
                float(row["llm_over_template_mean"])
                for row in aggregate
                if row.get("llm_over_template_mean") is not None
            )
            if any(
                row.get("llm_over_template_mean") is not None
                for row in aggregate
            )
            else None
        ),
        "generation_failure_rate": (
            sum(row.get("status") != "completed" for row in rows)
            / total_runs
            if total_runs
            else None
        ),
        "llm_win_rate": (
            sum(
                float(row["llm_over_template"]) > 1.0
                for row in rows
                if row.get("llm_over_template") not in {None, ""}
            )
            / sum(
                row.get("llm_over_template") not in {None, ""}
                for row in rows
            )
            if any(
                row.get("llm_over_template") not in {None, ""}
                for row in rows
            )
            else None
        ),
        "model_calls_total": sum(
            int(row["model_calls"]) for row in rows
        ),
        "tokens_total": sum(int(row["total_tokens"]) for row in rows),
        "llm_generation_calls_total": sum(
            int(row["llm_generation_calls"]) for row in rows
        ),
        "llm_generation_tokens_total": sum(
            int(row["llm_generation_tokens"]) for row in rows
        ),
        "llm_generation_cost_upper_usd_total": sum(
            float(row["llm_generation_cost_upper_usd"])
            for row in rows
        ),
        "estimated_cost_upper_usd_total": sum(
            float(row["estimated_cost_upper_usd"]) for row in rows
        ),
        "pricing_snapshot_date": PRICING_SNAPSHOT_DATE,
    }
    _write_json(destination / "paired_generation_overall.json", overall)
    return rows, aggregate, overall


def run_paired_generation_experiment(
    config_path: str | Path,
    *,
    output_dir: str | Path,
    adapter_name: str = "deepseek",
    resume: bool = True,
    adapter_factory: Callable[[], AgentAdapter] | None = None,
) -> dict[str, Any]:
    config_file = Path(config_path).resolve()
    config = yaml.safe_load(config_file.read_text(encoding="utf-8"))
    root = config_file.parents[1]
    destination = Path(output_dir).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    replicates = int(config.get("independent_runs", 1))
    if replicates < 1:
        raise ValueError("independent_runs must be positive")
    jobs = [
        PairedGenerationJob(
            workload=name,
            source=str((root / entry["path"]).resolve()),
            size=int(entry["size"]),
            replicate=replicate,
        )
        for name, entry in config.get("workloads", {}).items()
        for replicate in range(1, replicates + 1)
    ]
    if not jobs:
        raise ValueError("Experiment config contains no workloads")
    order_seed = int(config.get("order_seed", 42))
    random.Random(order_seed).shuffle(jobs)
    execution = config.get("execution", {})
    measurement = config.get("measurement", {})
    budget = config.get("budget", {})
    max_calls = int(budget.get("max_model_calls", 100))
    max_tokens = int(budget.get("max_total_tokens", 250_000))
    completed = 0
    resumed = 0
    failures: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    def make_adapter() -> AgentAdapter:
        if adapter_factory is not None:
            return adapter_factory()
        if adapter_name == "deepseek":
            return DeepSeekAdapter.from_env()
        if adapter_name == "offline":
            return OfflineHeuristicAdapter()
        raise ValueError("adapter_name must be deepseek or offline")

    for job in jobs:
        pair_dir = (
            destination / job.workload / f"run_{job.replicate:02d}"
        )
        report_path = pair_dir / "pair_report.json"
        if resume and report_path.exists():
            resumed += 1
            continue
        calls_so_far = _read_calls(destination)
        tokens_so_far = sum(
            int(call.get("total_tokens") or 0) for call in calls_so_far
        )
        if len(calls_so_far) >= max_calls or tokens_so_far >= max_tokens:
            skipped.append(
                {
                    **asdict(job),
                    "reason": "experiment budget reached before job start",
                    "calls_so_far": len(calls_so_far),
                    "tokens_so_far": tokens_so_far,
                }
            )
            continue

        pair_dir.mkdir(parents=True, exist_ok=True)
        _write_json(pair_dir / "job.json", asdict(job))
        adapter: AgentAdapter | None = None
        try:
            adapter = make_adapter()
            analysis = adapter.analyze(job.source)
            plan = adapter.plan(
                analysis,
                workers=int(execution.get("workers", 4)),
                chunks=int(execution.get("chunks", 4)),
            )
            shared_dir = pair_dir / "shared"
            _write_json(shared_dir / "analysis.json", analysis.to_dict())
            _write_json(shared_dir / "parallel_plan.json", plan.to_dict())
            shared_calls = list(getattr(adapter, "traces", []))
            if hasattr(adapter, "traces"):
                _write_json(
                    shared_dir / "model_trace.json",
                    {"adapter": adapter.name, "calls": shared_calls},
                )
                getattr(adapter, "traces").clear()

            common = {
                "size": job.size,
                "seed": int(execution.get("seed", 42)) + job.replicate,
                "workers": plan.workers,
                "chunks": plan.chunks,
                "timeout_seconds": float(
                    execution.get("timeout_seconds", 120)
                ),
                "max_repair_attempts": 0,
                "feedback_mode": "correctness",
                "performance_repeats": 1,
                "minimum_speedup": 1.0,
                "max_performance_attempts": 0,
                "analysis_override": analysis,
                "plan_override": plan,
            }
            template_report = run_agent_pipeline(
                job.source,
                output_dir=pair_dir / "template",
                generation_mode="template",
                max_code_repair_attempts=0,
                adapter=OfflineHeuristicAdapter(),
                **common,
            )
            llm_report = run_agent_pipeline(
                job.source,
                output_dir=pair_dir / "llm",
                generation_mode="llm",
                max_code_repair_attempts=int(
                    execution.get("max_code_repair_attempts", 2)
                ),
                adapter=adapter,
                **common,
            )
            if not plan.parallelizable:
                raise ValueError(
                    "Paired generator experiment requires a parallel plan"
                )
            if not template_report.get("correct") or not llm_report.get(
                "correct"
            ):
                raise RuntimeError(
                    "Both generated candidates must pass correctness before "
                    "paired timing"
                )
            measured = _paired_measurement(
                template_candidate=pair_dir / "template" / "candidate.py",
                llm_candidate=pair_dir / "llm" / "candidate.py",
                size=job.size,
                seed=int(execution.get("seed", 42)) + job.replicate,
                timeout_seconds=float(
                    execution.get("timeout_seconds", 120)
                ),
                warmups=int(measurement.get("warmups", 1)),
                repeats=int(measurement.get("repeats", 3)),
                order_seed=order_seed + job.replicate,
            )
            pair_report = {
                "status": "completed",
                "workload": job.workload,
                "replicate": job.replicate,
                "source": job.source,
                "shared_plan": True,
                "shared_analysis": analysis.to_dict(),
                "shared_parallel_plan": plan.to_dict(),
                "template_report": template_report,
                "llm_report": llm_report,
                "measurement": measured,
            }
            _write_json(report_path, pair_report)
            (pair_dir / "experiment_error.json").unlink(missing_ok=True)
            completed += 1
        except Exception as exc:
            if adapter is not None and hasattr(adapter, "traces"):
                _write_json(
                    pair_dir / "failed_model_trace.json",
                    {
                        "adapter": adapter.name,
                        "calls": list(getattr(adapter, "traces")),
                    },
                )
            failure = {
                **asdict(job),
                "error_type": type(exc).__name__,
                "message": str(exc),
                "traceback": traceback.format_exc(),
            }
            failures.append(failure)
            _write_json(pair_dir / "experiment_error.json", failure)

        calls_now = _read_calls(destination)
        _write_json(
            destination / "progress.json",
            {
                "completed": len(
                    list(destination.rglob("pair_report.json"))
                ),
                "total_jobs": len(jobs),
                "executed_this_invocation": completed,
                "resumed_jobs": resumed,
                "model_calls": len(calls_now),
                "total_tokens": sum(
                    int(call.get("total_tokens") or 0)
                    for call in calls_now
                ),
                "failed": len(failures),
                "budget_skipped": len(skipped),
            },
        )

    pair_dirs = [
        path.parent for path in destination.rglob("pair_report.json")
    ]
    rows, aggregate, overall = _summarize_pairs(pair_dirs, destination)
    calls = _read_calls(destination)
    manifest = {
        "config": str(config_file),
        "adapter": adapter_name,
        "total_jobs": len(jobs),
        "completed_jobs": len(pair_dirs),
        "executed_this_invocation": completed,
        "resumed_jobs": resumed,
        "failed_jobs": failures,
        "budget_skipped": skipped,
        "model_calls": len(calls),
        "total_tokens": sum(
            int(call.get("total_tokens") or 0) for call in calls
        ),
        "shared_analysis_and_plan": True,
        "resumable": True,
    }
    _write_json(destination / "experiment_manifest.json", manifest)
    return {
        "manifest": manifest,
        "rows": rows,
        "aggregate": aggregate,
        "overall": overall,
    }


def plot_paired_generation_experiment(
    summary_csv: str | Path,
    aggregate_csv: str | Path,
    output_dir: str | Path,
) -> Path:
    with Path(summary_csv).open(
        "r", encoding="utf-8-sig", newline=""
    ) as handle:
        summary = list(csv.DictReader(handle))
    with Path(aggregate_csv).open(
        "r", encoding="utf-8-sig", newline=""
    ) as handle:
        aggregate = list(csv.DictReader(handle))
    if not summary or not aggregate:
        raise ValueError("Paired generation CSV files cannot be empty")

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    output = destination / "paired_generator_comparison.png"
    workloads = [row["workload"] for row in aggregate]
    means = [float(row["llm_over_template_mean"]) for row in aggregate]
    errors = [
        float(row["llm_over_template_stdev"]) for row in aggregate
    ]
    template_correct = sum(
        str(row["template_correct"]).lower() == "true" for row in summary
    ) / len(summary)
    llm_correct = sum(
        str(row["llm_correct"]).lower() == "true" for row in summary
    ) / len(summary)
    repair_count = sum(int(row["llm_code_repairs"]) for row in summary)
    generation_tokens = sum(
        int(row["llm_generation_tokens"]) for row in summary
    )

    fig, axes = plt.subplots(
        1, 2, figsize=(12.2, 5.4), constrained_layout=True
    )
    x = np.arange(len(workloads))
    bars = axes[0].bar(
        x,
        means,
        yerr=errors,
        capsize=4,
        color="#2563EB",
    )
    axes[0].bar_label(bars, fmt="%.3fx", padding=3, fontsize=8)
    axes[0].axhline(
        1.0, color="#DC2626", linestyle="--", linewidth=1.3
    )
    axes[0].set_title("LLM Runtime Relative to Template")
    axes[0].set_ylabel(
        "Template parallel time / LLM parallel time"
    )
    axes[0].set_xticks(
        x, [name.replace("_", " ").title() for name in workloads]
    )
    axes[0].tick_params(axis="x", rotation=18)
    axes[0].grid(axis="y", linestyle="--", alpha=0.3)

    reliability = axes[1].bar(
        ["Template", "Controlled LLM"],
        [template_correct, llm_correct],
        color=["#6B7280", "#2563EB"],
    )
    axes[1].bar_label(
        reliability,
        labels=[
            f"{template_correct:.1%}",
            f"{llm_correct:.1%}",
        ],
        padding=4,
    )
    axes[1].set_ylim(0, 1.12)
    axes[1].set_ylabel("Correct candidate rate")
    axes[1].set_title("Generator Reliability and Added Cost")
    axes[1].text(
        0.5,
        0.08,
        (
            f"LLM code repairs: {repair_count}\n"
            f"LLM generation tokens: {generation_tokens:,}"
        ),
        transform=axes[1].transAxes,
        ha="center",
        va="bottom",
        fontsize=10,
        bbox={
            "boxstyle": "round,pad=0.4",
            "facecolor": "#EFF6FF",
            "edgecolor": "#93C5FD",
        },
    )
    axes[1].grid(axis="y", linestyle="--", alpha=0.3)
    fig.suptitle(
        "Shared-Plan Paired Generator Experiment (12 Runs)",
        fontsize=14,
        fontweight="bold",
    )
    fig.savefig(output, dpi=220)
    plt.close(fig)
    return output
