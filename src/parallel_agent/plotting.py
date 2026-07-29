from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np


MODE_ORDER = ("serial", "naive", "optimized")
MODE_LABELS = {
    "serial": "M0 Serial",
    "naive": "M1 Naive",
    "optimized": "M2 Optimized",
}
MODE_COLORS = {
    "serial": "#6B7280",
    "naive": "#F59E0B",
    "optimized": "#2563EB",
}


def _read_rows(csv_path: Path) -> list[dict[str, Any]]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError("Suite CSV contains no experiment rows")
    required = {
        "benchmark",
        "mode",
        "total_runtime_seconds",
        "total_speedup",
        "selected_mode",
    }
    missing = required - set(rows[0])
    if missing:
        raise ValueError(f"Suite CSV is missing columns: {sorted(missing)}")
    if "total_runtime_iqr_seconds" not in rows[0]:
        _restore_iqr_from_json(csv_path, rows)
    return rows


def _restore_iqr_from_json(
    csv_path: Path, rows: list[dict[str, Any]]
) -> None:
    """Backfill IQR for CSV files created before the column was introduced."""
    for row in rows:
        scale = row.get("scale", "")
        report_path = csv_path.parent / f"{row['benchmark']}_{scale}.json"
        if not report_path.exists():
            raise ValueError(
                "Suite CSV has no IQR column and its source report is missing: "
                f"{report_path}"
            )
        report = json.loads(report_path.read_text(encoding="utf-8"))
        row["total_runtime_iqr_seconds"] = report["summary"][row["mode"]][
            "total_runtime_iqr_seconds"
        ]


def _format_name(name: str) -> str:
    return name.replace("_", " ").title()


def plot_suite_results(
    suite_csv: str | Path, output_dir: str | Path
) -> dict[str, str]:
    csv_path = Path(suite_csv)
    rows = _read_rows(csv_path)
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)

    benchmarks = list(dict.fromkeys(row["benchmark"] for row in rows))
    lookup = {(row["benchmark"], row["mode"]): row for row in rows}
    missing_pairs = [
        (benchmark, mode)
        for benchmark in benchmarks
        for mode in MODE_ORDER
        if (benchmark, mode) not in lookup
    ]
    if missing_pairs:
        raise ValueError(f"Suite CSV is missing benchmark/mode rows: {missing_pairs}")

    runtime_path = destination / "total_runtime_by_method.png"
    speedup_path = destination / "total_speedup.png"
    decision_path = destination / "m2_decisions.png"

    _plot_runtime(benchmarks, lookup, runtime_path)
    _plot_speedup(benchmarks, lookup, speedup_path)
    _plot_decisions(benchmarks, lookup, decision_path)

    return {
        "runtime_figure": str(runtime_path),
        "speedup_figure": str(speedup_path),
        "decision_figure": str(decision_path),
    }


def _plot_runtime(
    benchmarks: list[str],
    lookup: dict[tuple[str, str], dict[str, Any]],
    output: Path,
) -> None:
    x = np.arange(len(benchmarks))
    width = 0.25
    fig, ax = plt.subplots(figsize=(12, 6.5), constrained_layout=True)

    for index, mode in enumerate(MODE_ORDER):
        values = [
            float(lookup[(benchmark, mode)]["total_runtime_seconds"])
            for benchmark in benchmarks
        ]
        errors = [
            float(lookup[(benchmark, mode)]["total_runtime_iqr_seconds"]) / 2
            for benchmark in benchmarks
        ]
        bars = ax.bar(
            x + (index - 1) * width,
            values,
            width,
            yerr=errors,
            capsize=3,
            label=MODE_LABELS[mode],
            color=MODE_COLORS[mode],
        )
        ax.bar_label(bars, fmt="%.3f", padding=3, fontsize=8)

    ax.set_title("End-to-End Runtime: Serial vs. Naive vs. Optimized")
    ax.set_ylabel("Median runtime (seconds); error bar = IQR / 2")
    ax.set_xticks(x, [_format_name(name) for name in benchmarks], rotation=18)
    ax.grid(axis="y", linestyle="--", alpha=0.35)
    ax.legend(ncols=3, frameon=False, loc="upper right")
    fig.savefig(output, dpi=220)
    plt.close(fig)


def _plot_speedup(
    benchmarks: list[str],
    lookup: dict[tuple[str, str], dict[str, Any]],
    output: Path,
) -> None:
    x = np.arange(len(benchmarks))
    width = 0.35
    fig, ax = plt.subplots(figsize=(11.5, 6), constrained_layout=True)
    for index, mode in enumerate(("naive", "optimized")):
        values = [
            float(lookup[(benchmark, mode)]["total_speedup"])
            for benchmark in benchmarks
        ]
        bars = ax.bar(
            x + (index - 0.5) * width,
            values,
            width,
            label=MODE_LABELS[mode],
            color=MODE_COLORS[mode],
        )
        ax.bar_label(bars, fmt="%.2fx", padding=3, fontsize=9)

    ax.axhline(1.0, color="#DC2626", linewidth=1.4, linestyle="--")
    ax.text(
        len(benchmarks) - 0.55,
        1.02,
        "break-even",
        color="#DC2626",
        fontsize=9,
        ha="right",
    )
    ax.set_title("End-to-End Speedup over Serial Baseline")
    ax.set_ylabel("Speedup (higher is better)")
    ax.set_xticks(x, [_format_name(name) for name in benchmarks], rotation=18)
    ax.set_ylim(0, max(2.15, ax.get_ylim()[1]))
    ax.grid(axis="y", linestyle="--", alpha=0.35)
    ax.legend(ncols=2, frameon=False, loc="upper right")
    fig.savefig(output, dpi=220)
    plt.close(fig)


def _plot_decisions(
    benchmarks: list[str],
    lookup: dict[tuple[str, str], dict[str, Any]],
    output: Path,
) -> None:
    decisions = [
        lookup[(benchmark, "optimized")]["selected_mode"]
        for benchmark in benchmarks
    ]
    colors = [
        "#2563EB" if decision == "optimized" else "#10B981"
        for decision in decisions
    ]
    labels = [
        "Parallel" if decision == "optimized" else "Serial fallback"
        for decision in decisions
    ]

    fig, ax = plt.subplots(figsize=(10.5, 4.8), constrained_layout=True)
    bars = ax.barh(
        [_format_name(name) for name in benchmarks],
        [1] * len(benchmarks),
        color=colors,
    )
    for bar, label in zip(bars, labels, strict=True):
        ax.text(
            0.5,
            bar.get_y() + bar.get_height() / 2,
            label,
            ha="center",
            va="center",
            color="white",
            fontweight="bold",
        )
    ax.set_title("M2 Benefit-Gate Decisions")
    ax.set_xlim(0, 1)
    ax.set_xticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)
    fig.savefig(output, dpi=220)
    plt.close(fig)
