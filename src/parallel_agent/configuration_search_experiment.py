from __future__ import annotations

import csv
import json
import random
import statistics
import traceback
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml
import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np

from .configuration_search import run_configuration_search


@dataclass(frozen=True)
class ConfigurationSearchJob:
    workload: str
    source: str
    size: int
    tuning_size: int
    replicate: int


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _summarize(
    destination: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for report_path in sorted(
        destination.rglob("configuration_search_report.json")
    ):
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if report.get("status") != "completed":
            continue
        selection = report["selection"]
        confirmation = selection.get("scale_confirmation")
        holdout = report["holdout"]
        amortization = report["amortization"]
        selected_speedup = float(holdout["selected_speedup"])
        no_scale_speedup = float(holdout["no_scale_speedup"])
        fixed_speedup = float(holdout["fixed_speedup"])
        rows.append(
            {
                "workload": report["workload"],
                "run": report_path.parent.name,
                "size": report["size"],
                "tuning_size": report["tuning_size"],
                "preliminary_selected_label": selection[
                    "preliminary_selected_label"
                ],
                "confirmation_used": confirmation is not None,
                "confirmation_passed": (
                    confirmation.get("passed")
                    if confirmation is not None
                    else None
                ),
                "selected_label": selection["selected_label"],
                "selected_speedup": selected_speedup,
                "no_scale_speedup": no_scale_speedup,
                "fixed_speedup": fixed_speedup,
                "selected_over_no_scale": float(
                    holdout["selected_over_no_scale"]
                ),
                "selected_over_fixed": float(
                    holdout["selected_over_fixed"]
                ),
                "selected_regression": selected_speedup < 0.95,
                "no_scale_regression": no_scale_speedup < 0.95,
                "fixed_regression": fixed_speedup < 0.95,
                "search_wall_seconds": amortization[
                    "search_wall_seconds"
                ],
                "small_sample_search_wall_seconds": amortization[
                    "small_sample_search_wall_seconds"
                ],
                "scale_confirmation_wall_seconds": amortization[
                    "scale_confirmation_wall_seconds"
                ],
                "break_even_vs_serial_repetitions": amortization[
                    "break_even_vs_serial_repetitions"
                ],
                "break_even_vs_fixed_repetitions": amortization[
                    "break_even_vs_fixed_repetitions"
                ],
            }
        )
    rows.sort(key=lambda row: (str(row["workload"]), str(row["run"])))
    summary_path = destination / "configuration_search_summary.csv"
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
        selected = [float(row["selected_speedup"]) for row in group]
        no_scale = [float(row["no_scale_speedup"]) for row in group]
        fixed = [float(row["fixed_speedup"]) for row in group]
        relative = [
            float(row["selected_over_fixed"]) for row in group
        ]
        aggregate.append(
            {
                "workload": workload,
                "runs": len(group),
                "selected_speedup_mean": statistics.fmean(selected),
                "selected_speedup_stdev": (
                    statistics.stdev(selected)
                    if len(selected) > 1
                    else 0.0
                ),
                "no_scale_speedup_mean": statistics.fmean(no_scale),
                "no_scale_speedup_stdev": (
                    statistics.stdev(no_scale)
                    if len(no_scale) > 1
                    else 0.0
                ),
                "fixed_speedup_mean": statistics.fmean(fixed),
                "fixed_speedup_stdev": (
                    statistics.stdev(fixed)
                    if len(fixed) > 1
                    else 0.0
                ),
                "selected_over_fixed_mean": statistics.fmean(relative),
                "selected_over_fixed_stdev": (
                    statistics.stdev(relative)
                    if len(relative) > 1
                    else 0.0
                ),
                "selected_regression_rate": sum(
                    bool(row["selected_regression"]) for row in group
                )
                / len(group),
                "no_scale_regression_rate": sum(
                    bool(row["no_scale_regression"]) for row in group
                )
                / len(group),
                "fixed_regression_rate": sum(
                    bool(row["fixed_regression"]) for row in group
                )
                / len(group),
                "serial_selection_rate": sum(
                    row["selected_label"] == "serial" for row in group
                )
                / len(group),
                "scale_confirmation_rate": sum(
                    bool(row["confirmation_used"]) for row in group
                )
                / len(group),
                "scale_rescue_rate": sum(
                    str(row["confirmation_passed"]).lower() == "true"
                    for row in group
                )
                / len(group),
                "search_wall_seconds_mean": statistics.fmean(
                    float(row["search_wall_seconds"]) for row in group
                ),
            }
        )
    aggregate_path = destination / "configuration_search_aggregate.csv"
    if aggregate:
        with aggregate_path.open(
            "w", encoding="utf-8-sig", newline=""
        ) as handle:
            writer = csv.DictWriter(handle, fieldnames=list(aggregate[0]))
            writer.writeheader()
            writer.writerows(aggregate)

    total = len(rows)
    overall = {
        "workloads": len(groups),
        "runs": total,
        "selected_speedup_macro_mean": (
            statistics.fmean(
                float(row["selected_speedup_mean"])
                for row in aggregate
            )
            if aggregate
            else None
        ),
        "fixed_speedup_macro_mean": (
            statistics.fmean(
                float(row["fixed_speedup_mean"]) for row in aggregate
            )
            if aggregate
            else None
        ),
        "no_scale_speedup_macro_mean": (
            statistics.fmean(
                float(row["no_scale_speedup_mean"])
                for row in aggregate
            )
            if aggregate
            else None
        ),
        "selected_regression_rate": (
            sum(bool(row["selected_regression"]) for row in rows)
            / total
            if total
            else None
        ),
        "fixed_regression_rate": (
            sum(bool(row["fixed_regression"]) for row in rows) / total
            if total
            else None
        ),
        "no_scale_regression_rate": (
            sum(bool(row["no_scale_regression"]) for row in rows) / total
            if total
            else None
        ),
        "selected_beats_fixed_rate": (
            sum(float(row["selected_over_fixed"]) > 1.0 for row in rows)
            / total
            if total
            else None
        ),
        "selected_avoids_fixed_regression_rate": (
            sum(
                bool(row["fixed_regression"])
                and not bool(row["selected_regression"])
                for row in rows
            )
            / total
            if total
            else None
        ),
        "search_wall_seconds_total": sum(
            float(row["search_wall_seconds"]) for row in rows
        ),
    }
    _write_json(destination / "configuration_search_overall.json", overall)
    return rows, aggregate, overall


def run_configuration_search_experiment(
    config_path: str | Path,
    *,
    output_dir: str | Path,
    resume: bool = True,
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
        ConfigurationSearchJob(
            workload=name,
            source=str((root / entry["path"]).resolve()),
            size=int(entry["size"]),
            tuning_size=int(entry.get("tuning_size", entry["size"])),
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
    completed = 0
    resumed = 0
    failures: list[dict[str, Any]] = []
    for job in jobs:
        run_dir = destination / job.workload / f"run_{job.replicate:02d}"
        report_path = run_dir / "configuration_search_report.json"
        if resume and report_path.exists():
            resumed += 1
            continue
        run_dir.mkdir(parents=True, exist_ok=True)
        _write_json(run_dir / "job.json", asdict(job))
        try:
            run_configuration_search(
                job.source,
                output_dir=run_dir,
                size=job.size,
                tuning_size=job.tuning_size,
                seed=int(execution.get("seed", 42)) + job.replicate,
                max_workers=int(execution.get("max_workers", 4)),
                chunk_multipliers=tuple(
                    int(value)
                    for value in execution.get(
                        "chunk_multipliers", [1, 2, 4]
                    )
                ),
                tuning_repeats=int(
                    execution.get("tuning_repeats", 2)
                ),
                confirmation_repeats=int(
                    execution.get("confirmation_repeats", 2)
                ),
                holdout_repeats=int(
                    execution.get("holdout_repeats", 5)
                ),
                warmups=int(execution.get("warmups", 1)),
                timeout_seconds=float(
                    execution.get("timeout_seconds", 120)
                ),
                minimum_speedup=float(
                    execution.get("minimum_speedup", 1.05)
                ),
                minimum_relative_improvement=float(
                    execution.get(
                        "minimum_relative_improvement", 1.05
                    )
                ),
                order_seed=order_seed + job.replicate,
            )
            completed += 1
            (run_dir / "experiment_error.json").unlink(missing_ok=True)
        except Exception as exc:
            failure = {
                **asdict(job),
                "error_type": type(exc).__name__,
                "message": str(exc),
                "traceback": traceback.format_exc(),
            }
            failures.append(failure)
            _write_json(run_dir / "experiment_error.json", failure)
        _write_json(
            destination / "progress.json",
            {
                "completed": len(
                    list(
                        destination.rglob(
                            "configuration_search_report.json"
                        )
                    )
                ),
                "total_jobs": len(jobs),
                "executed_this_invocation": completed,
                "resumed_jobs": resumed,
                "failed": len(failures),
            },
        )

    rows, aggregate, overall = _summarize(destination)
    report_count = len(
        list(destination.rglob("configuration_search_report.json"))
    )
    manifest = {
        "config": str(config_file),
        "total_jobs": len(jobs),
        "completed_jobs": report_count,
        "executed_this_invocation": completed,
        "resumed_jobs": resumed,
        "failed_jobs": failures,
        "tuning_and_holdout_separated": True,
        "small_sample_scale_confirmation": True,
        "resumable": True,
    }
    _write_json(destination / "experiment_manifest.json", manifest)
    return {
        "manifest": manifest,
        "rows": rows,
        "aggregate": aggregate,
        "overall": overall,
    }


def plot_configuration_search_experiment(
    aggregate_csv: str | Path,
    overall_json: str | Path,
    output_dir: str | Path,
) -> Path:
    with Path(aggregate_csv).open(
        "r", encoding="utf-8-sig", newline=""
    ) as handle:
        aggregate = list(csv.DictReader(handle))
    overall = json.loads(Path(overall_json).read_text(encoding="utf-8"))
    if not aggregate:
        raise ValueError("Configuration-search aggregate CSV is empty")
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    output = destination / "configuration_search_comparison.png"

    workloads = [row["workload"] for row in aggregate]
    fixed = [float(row["fixed_speedup_mean"]) for row in aggregate]
    selected = [
        float(row["selected_speedup_mean"]) for row in aggregate
    ]
    no_scale = [
        float(row["no_scale_speedup_mean"]) for row in aggregate
    ]
    fixed_error = [
        float(row["fixed_speedup_stdev"]) for row in aggregate
    ]
    selected_error = [
        float(row["selected_speedup_stdev"]) for row in aggregate
    ]
    no_scale_error = [
        float(row["no_scale_speedup_stdev"]) for row in aggregate
    ]
    x = np.arange(len(workloads))
    width = 0.26
    fig, axes = plt.subplots(
        1, 2, figsize=(13.8, 5.8), constrained_layout=True
    )
    fixed_bars = axes[0].bar(
        x - width,
        fixed,
        width,
        yerr=fixed_error,
        capsize=3,
        color="#9CA3AF",
        label="Fixed 4 workers / 4 chunks",
    )
    no_scale_bars = axes[0].bar(
        x,
        no_scale,
        width,
        yerr=no_scale_error,
        capsize=3,
        color="#F59E0B",
        label="Small-sample decision",
    )
    selected_bars = axes[0].bar(
        x + width,
        selected,
        width,
        yerr=selected_error,
        capsize=3,
        color="#2563EB",
        label="Full three-stage method",
    )
    axes[0].axhline(
        1.0, color="#DC2626", linestyle="--", linewidth=1.2
    )
    axes[0].set_title("Holdout End-to-End Speedup")
    axes[0].set_ylabel("Speedup over serial")
    axes[0].set_xticks(
        x,
        [name.replace("_", " ").title() for name in workloads],
        rotation=25,
        ha="right",
    )
    axes[0].grid(axis="y", linestyle="--", alpha=0.3)
    axes[0].legend(frameon=False, fontsize=9)
    axes[0].bar_label(fixed_bars, fmt="%.2f", padding=2, fontsize=7)
    axes[0].bar_label(
        no_scale_bars, fmt="%.2f", padding=2, fontsize=7
    )
    axes[0].bar_label(
        selected_bars, fmt="%.2f", padding=2, fontsize=7
    )

    regression = [
        float(overall["fixed_regression_rate"]),
        float(overall["no_scale_regression_rate"]),
        float(overall["selected_regression_rate"]),
    ]
    regression_bars = axes[1].bar(
        ["Fixed", "Small-sample", "Full method"],
        regression,
        color=["#9CA3AF", "#F59E0B", "#2563EB"],
    )
    axes[1].bar_label(
        regression_bars,
        labels=[f"{value:.1%}" for value in regression],
        padding=4,
    )
    axes[1].set_ylim(0, max(0.75, max(regression) + 0.1))
    axes[1].set_ylabel("Fraction of runs below 0.95x")
    axes[1].set_title("Performance Regression Rate")
    axes[1].grid(axis="y", linestyle="--", alpha=0.3)
    axes[1].text(
        0.5,
        0.82,
        (
            f"Adaptive macro speedup: "
            f"{overall['selected_speedup_macro_mean']:.3f}x\n"
            f"Small-sample macro speedup: "
            f"{overall['no_scale_speedup_macro_mean']:.3f}x\n"
            f"Fixed macro speedup: "
            f"{overall['fixed_speedup_macro_mean']:.3f}x\n"
            f"Search wall time: "
            f"{overall['search_wall_seconds_total']:.1f}s"
        ),
        transform=axes[1].transAxes,
        ha="center",
        va="top",
        bbox={
            "boxstyle": "round,pad=0.45",
            "facecolor": "#EFF6FF",
            "edgecolor": "#93C5FD",
        },
    )
    fig.suptitle(
        "Multi-Scale Configuration Search (8 Workloads × 3 Runs)",
        fontsize=14,
        fontweight="bold",
    )
    fig.savefig(output, dpi=220)
    plt.close(fig)
    return output
