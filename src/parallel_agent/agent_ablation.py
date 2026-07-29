from __future__ import annotations

import csv
import json
import statistics
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np


PRICING_SNAPSHOT_DATE = "2026-07-29"
PRICE_PER_MILLION_TOKENS = {
    "deepseek-v4-flash": {"input": 0.14, "output": 0.28},
    "deepseek-v4-pro": {"input": 0.435, "output": 0.87},
}


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def summarize_agent_runs(
    run_dirs: list[str | Path], output_csv: str | Path
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for run_dir_value in run_dirs:
        run_dir = Path(run_dir_value)
        report = _read_json(run_dir / "run_report.json")
        analysis_path = run_dir / "analysis.json"
        analysis = _read_json(analysis_path) if analysis_path.exists() else {}
        trace_path = run_dir / "model_trace.json"
        traces = (
            _read_json(trace_path).get("calls", [])
            if trace_path.exists()
            else []
        )
        attempts = report.get("attempts", [])
        first_performance = (
            attempts[0].get("performance", {}) if attempts else {}
        )
        last_performance = (
            attempts[-1].get("performance", {}) if attempts else {}
        )
        selected_mode = report.get("selected_mode")
        measured_speedup = last_performance.get("end_to_end_speedup")
        effective_speedup = (
            1.0
            if selected_mode == "serial" and report.get("correct")
            else measured_speedup
        )
        pro_calls = sum(
            call.get("model") == "deepseek-v4-pro" for call in traces
        )
        flash_calls = sum(
            call.get("model") == "deepseek-v4-flash" for call in traces
        )
        estimated_cost = sum(
            (
                int(call.get("prompt_tokens") or 0)
                * PRICE_PER_MILLION_TOKENS.get(
                    call.get("model"), {"input": 0.0}
                )["input"]
                + int(call.get("completion_tokens") or 0)
                * PRICE_PER_MILLION_TOKENS.get(
                    call.get("model"), {"output": 0.0}
                )["output"]
            )
            / 1_000_000
            for call in traces
        )
        rows.append(
            {
                "run": run_dir.name,
                "workload": analysis.get("workload_name", "unknown"),
                "feedback_mode": report.get("feedback_mode"),
                "generation_mode": report.get(
                    "generation_mode", "template"
                ),
                "status": report.get("status"),
                "correct": report.get("correct"),
                "selected_mode": selected_mode,
                "initial_end_to_end_speedup": first_performance.get(
                    "end_to_end_speedup"
                ),
                "final_measured_speedup": measured_speedup,
                "effective_speedup_after_fallback": effective_speedup,
                "repair_attempts": report.get("repair_attempts_used", 0),
                "performance_attempts": report.get(
                    "performance_attempts_used", 0
                ),
                "code_repair_attempts": report.get(
                    "code_repair_attempts_used", 0
                ),
                "generation_safety_rejections": sum(
                    "generation_error" in attempt
                    for attempt in attempts
                ),
                "model_calls": len(traces),
                "pro_calls": pro_calls,
                "flash_calls": flash_calls,
                "prompt_tokens": sum(
                    int(call.get("prompt_tokens") or 0) for call in traces
                ),
                "completion_tokens": sum(
                    int(call.get("completion_tokens") or 0) for call in traces
                ),
                "total_tokens": sum(
                    int(call.get("total_tokens") or 0) for call in traces
                ),
                "estimated_cost_upper_usd": estimated_cost,
                "pricing_snapshot_date": PRICING_SNAPSHOT_DATE,
            }
        )

    output = Path(output_csv)
    output.parent.mkdir(parents=True, exist_ok=True)
    if rows:
        with output.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    return rows


def aggregate_agent_rows(
    rows: list[dict[str, Any]], output_csv: str | Path
) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        key = (
            str(row["workload"]),
            str(row["feedback_mode"]),
            str(row.get("generation_mode", "template")),
        )
        groups.setdefault(key, []).append(row)

    aggregate: list[dict[str, Any]] = []
    for (workload, mode, generation_mode), group in sorted(
        groups.items()
    ):
        measured = [
            float(row["final_measured_speedup"])
            for row in group
            if row.get("final_measured_speedup") not in {None, ""}
        ]
        effective = [
            float(row["effective_speedup_after_fallback"])
            for row in group
            if row.get("effective_speedup_after_fallback") not in {None, ""}
        ]
        correct_count = sum(
            str(row.get("correct")).lower() == "true" for row in group
        )
        regression_count = sum(value < 0.95 for value in effective)
        aggregate.append(
            {
                "workload": workload,
                "feedback_mode": mode,
                "generation_mode": generation_mode,
                "runs": len(group),
                "accepted_runs": sum(
                    row.get("status") == "accepted" for row in group
                ),
                "correct_rate": correct_count / len(group),
                "serial_fallback_rate": sum(
                    row.get("selected_mode") == "serial" for row in group
                )
                / len(group),
                "performance_regression_rate": (
                    regression_count / len(effective) if effective else None
                ),
                "measured_speedup_mean": (
                    statistics.fmean(measured) if measured else None
                ),
                "measured_speedup_stdev": (
                    statistics.stdev(measured) if len(measured) > 1 else 0.0
                ),
                "effective_speedup_mean": (
                    statistics.fmean(effective) if effective else None
                ),
                "effective_speedup_stdev": (
                    statistics.stdev(effective) if len(effective) > 1 else 0.0
                ),
                "model_calls_total": sum(
                    int(row.get("model_calls") or 0) for row in group
                ),
                "tokens_total": sum(
                    int(row.get("total_tokens") or 0) for row in group
                ),
                "code_repair_attempts_total": sum(
                    int(row.get("code_repair_attempts") or 0)
                    for row in group
                ),
                "generation_safety_rejections_total": sum(
                    int(row.get("generation_safety_rejections") or 0)
                    for row in group
                ),
                "estimated_cost_upper_usd_total": sum(
                    float(row.get("estimated_cost_upper_usd") or 0.0)
                    for row in group
                ),
                "pricing_snapshot_date": PRICING_SNAPSHOT_DATE,
            }
        )

    output = Path(output_csv)
    output.parent.mkdir(parents=True, exist_ok=True)
    if aggregate:
        with output.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(aggregate[0]))
            writer.writeheader()
            writer.writerows(aggregate)
    return aggregate


def overall_agent_metrics(
    aggregate_rows: list[dict[str, Any]], output_csv: str | Path
) -> list[dict[str, Any]]:
    modes: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in aggregate_rows:
        key = (
            str(row["feedback_mode"]),
            str(row.get("generation_mode", "template")),
        )
        modes.setdefault(key, []).append(row)

    output_rows: list[dict[str, Any]] = []
    for (mode, generation_mode), group in sorted(modes.items()):
        total_runs = sum(int(row["runs"]) for row in group)

        def weighted(field: str) -> float:
            return sum(
                float(row[field]) * int(row["runs"]) for row in group
            ) / total_runs

        output_rows.append(
            {
                "feedback_mode": mode,
                "generation_mode": generation_mode,
                "workloads": len(group),
                "runs": total_runs,
                "correct_rate": weighted("correct_rate"),
                "serial_fallback_rate": weighted(
                    "serial_fallback_rate"
                ),
                "performance_regression_rate": weighted(
                    "performance_regression_rate"
                ),
                "measured_speedup_macro_mean": weighted(
                    "measured_speedup_mean"
                ),
                "effective_speedup_macro_mean": weighted(
                    "effective_speedup_mean"
                ),
                "model_calls_total": sum(
                    int(row["model_calls_total"]) for row in group
                ),
                "tokens_total": sum(
                    int(row["tokens_total"]) for row in group
                ),
                "estimated_cost_upper_usd_total": sum(
                    float(row["estimated_cost_upper_usd_total"])
                    for row in group
                ),
                "pricing_snapshot_date": PRICING_SNAPSHOT_DATE,
            }
        )

    output = Path(output_csv)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output_rows:
        with output.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(output_rows[0]))
            writer.writeheader()
            writer.writerows(output_rows)
    return output_rows


def plot_agent_experiment(
    aggregate_csv: str | Path, output_dir: str | Path
) -> dict[str, str]:
    with Path(aggregate_csv).open(
        "r", encoding="utf-8-sig", newline=""
    ) as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError("Agent experiment aggregate CSV contains no rows")

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    speedup_path = destination / "agent_effective_speedup.png"
    regression_path = destination / "agent_regression_rate.png"
    cost_path = destination / "agent_token_cost.png"

    workloads = list(dict.fromkeys(row["workload"] for row in rows))
    preferred_modes = ["one_shot", "correctness", "performance"]
    modes = [
        mode
        for mode in preferred_modes
        if any(row["feedback_mode"] == mode for row in rows)
    ]
    labels = {
        "one_shot": "One-shot",
        "correctness": "Correctness feedback",
        "performance": "Performance feedback",
    }
    colors = {
        "one_shot": "#F59E0B",
        "correctness": "#6B7280",
        "performance": "#2563EB",
    }
    lookup = {
        (row["workload"], row["feedback_mode"]): row for row in rows
    }
    x = np.arange(len(workloads))
    width = 0.75 / len(modes)
    fig, ax = plt.subplots(figsize=(11.5, 6.2), constrained_layout=True)
    center = (len(modes) - 1) / 2
    for index, mode in enumerate(modes):
        values = [
            float(lookup[(workload, mode)]["effective_speedup_mean"])
            for workload in workloads
        ]
        errors = [
            float(lookup[(workload, mode)]["effective_speedup_stdev"])
            for workload in workloads
        ]
        bars = ax.bar(
            x + (index - center) * width,
            values,
            width,
            yerr=errors,
            capsize=3,
            color=colors[mode],
            label=labels[mode],
        )
        ax.bar_label(bars, fmt="%.2fx", padding=3, fontsize=8)
    ax.axhline(1.0, color="#DC2626", linestyle="--", linewidth=1.3)
    ax.set_title("Formal Agent Ablation: Effective End-to-End Speedup")
    ax.set_ylabel("Speedup after final execution decision")
    ax.set_xticks(
        x, [name.replace("_", " ").title() for name in workloads]
    )
    ax.grid(axis="y", linestyle="--", alpha=0.3)
    ax.legend(frameon=False, ncols=len(modes))
    fig.savefig(speedup_path, dpi=220)
    plt.close(fig)

    regression_rates = []
    fallback_rates = []
    for mode in modes:
        group = [row for row in rows if row["feedback_mode"] == mode]
        total = sum(int(row["runs"]) for row in group)
        regression_rates.append(
            sum(
                float(row["performance_regression_rate"])
                * int(row["runs"])
                for row in group
            )
            / total
        )
        fallback_rates.append(
            sum(
                float(row["serial_fallback_rate"]) * int(row["runs"])
                for row in group
            )
            / total
        )
    fig, ax = plt.subplots(figsize=(8.8, 5.6), constrained_layout=True)
    bars = ax.bar(
        np.arange(len(modes)),
        regression_rates,
        color=[colors[mode] for mode in modes],
    )
    ax.bar_label(
        bars,
        labels=[f"{value:.0%}" for value in regression_rates],
        padding=3,
    )
    ax.set_title("Performance Regression Rate Across 12 Runs per Mode")
    ax.set_ylabel("Fraction with final speedup < 0.95x")
    ax.set_xticks(np.arange(len(modes)), [labels[mode] for mode in modes])
    ax.set_ylim(0, 0.65)
    ax.grid(axis="y", linestyle="--", alpha=0.3)
    fig.savefig(regression_path, dpi=220)
    plt.close(fig)

    tokens = [
        sum(
            int(row["tokens_total"])
            for row in rows
            if row["feedback_mode"] == mode
        )
        for mode in modes
    ]
    costs = [
        sum(
            float(row["estimated_cost_upper_usd_total"])
            for row in rows
            if row["feedback_mode"] == mode
        )
        for mode in modes
    ]
    fig, ax = plt.subplots(figsize=(8.8, 5.6), constrained_layout=True)
    bars = ax.bar(
        np.arange(len(modes)),
        tokens,
        color=[colors[mode] for mode in modes],
    )
    ax.bar_label(
        bars,
        labels=[f"{token:,}" for token in tokens],
        padding=4,
    )
    ax.set_title("Model Token and Conservative API Cost by Mode")
    ax.set_ylabel("Total tokens (12 runs)")
    ax.set_xticks(
        np.arange(len(modes)),
        [
            f"{labels[mode]}\n≤${cost:.4f}"
            for mode, cost in zip(modes, costs, strict=True)
        ],
    )
    ax.grid(axis="y", linestyle="--", alpha=0.3)
    fig.savefig(cost_path, dpi=220)
    plt.close(fig)
    return {
        "speedup_figure": str(speedup_path),
        "regression_figure": str(regression_path),
        "cost_figure": str(cost_path),
    }


def plot_agent_ablation(
    summary_csv: str | Path, output_path: str | Path
) -> Path:
    with Path(summary_csv).open(
        "r", encoding="utf-8-sig", newline=""
    ) as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError("Agent ablation CSV contains no rows")

    labels = [
        {
            "one_shot": "One-shot",
            "correctness": "Correctness feedback",
            "performance": "Performance feedback",
        }.get(row["feedback_mode"], row["feedback_mode"])
        for row in rows
    ]
    measured = [
        float(row["final_measured_speedup"]) for row in rows
    ]
    effective = [
        float(row["effective_speedup_after_fallback"]) for row in rows
    ]
    x = np.arange(len(rows))
    width = 0.34
    fig, ax = plt.subplots(figsize=(9.5, 5.8), constrained_layout=True)
    measured_bars = ax.bar(
        x - width / 2,
        measured,
        width,
        color="#F59E0B",
        label="Generated parallel candidate",
    )
    effective_bars = ax.bar(
        x + width / 2,
        effective,
        width,
        color="#2563EB",
        label="Final selected execution",
    )
    ax.bar_label(measured_bars, fmt="%.2fx", padding=3)
    ax.bar_label(effective_bars, fmt="%.2fx", padding=3)
    ax.axhline(1.0, color="#DC2626", linestyle="--", linewidth=1.3)
    ax.set_title("Tiny Tasks: Feedback Ablation")
    ax.set_ylabel("End-to-end speedup over serial")
    ax.set_xticks(x, labels)
    ax.set_ylim(0, max(1.25, ax.get_ylim()[1]))
    ax.grid(axis="y", linestyle="--", alpha=0.3)
    ax.legend(frameon=False, loc="upper left")
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=220)
    plt.close(fig)
    return output
