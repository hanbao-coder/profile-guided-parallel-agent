from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np


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
        rows.append(
            {
                "run": run_dir.name,
                "workload": analysis.get("workload_name", "unknown"),
                "feedback_mode": report.get("feedback_mode"),
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
