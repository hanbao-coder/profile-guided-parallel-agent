#!/usr/bin/env python3
"""Summarize the preregistered Radon worker-boundary experiment."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt


ROOT = Path(__file__).resolve().parents[1]


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _radon_runs(summary: dict[str, Any]) -> list[dict[str, Any]]:
    return [run for run in summary["runs"] if run["project"] == "radon"]


def _candidate_statuses(results_root: Path) -> Counter[str]:
    counts: Counter[str] = Counter()
    for path in sorted(results_root.glob("radon/*/outcome.json")):
        outcome = _read(path)
        for event in outcome.get("agent", {}).get("events", []):
            evaluation = event.get("observation", {}).get("candidate_evaluation")
            if isinstance(evaluation, dict) and evaluation.get("status"):
                counts[str(evaluation["status"])] += 1
    return counts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--control-summary",
        type=Path,
        default=ROOT / "results/m5/corrected-final-summary.json",
    )
    parser.add_argument(
        "--treatment-summary",
        type=Path,
        default=ROOT / "results/m7/worker-boundary-summary.json",
    )
    parser.add_argument(
        "--treatment-results",
        type=Path,
        default=ROOT / "results/m7/worker-boundary",
    )
    parser.add_argument("--output", type=Path, default=ROOT / "docs/data/m7-worker-boundary.json")
    parser.add_argument("--figure", type=Path, default=ROOT / "docs/figures/m7-worker-boundary.png")
    args = parser.parse_args()

    control_runs = _radon_runs(_read(args.control_summary))
    treatment_runs = _radon_runs(_read(args.treatment_summary))
    treatment_statuses = _candidate_statuses(args.treatment_results)
    compact = {
        "schema_version": 1,
        "project": "radon",
        "control": {
            "runs": len(control_runs),
            "effective": sum(run["primary_outcome"] == "effective_parallelization" for run in control_runs),
            "safe_fallback": sum(run["primary_outcome"] == "safe_serial_fallback" for run in control_runs),
            "model_tokens": sum(int(run.get("model_tokens") or 0) for run in control_runs),
        },
        "worker_boundary": {
            "runs": len(treatment_runs),
            "effective": sum(run["primary_outcome"] == "effective_parallelization" for run in treatment_runs),
            "safe_fallback": sum(run["primary_outcome"] == "safe_serial_fallback" for run in treatment_runs),
            "model_tokens": sum(int(run.get("model_tokens") or 0) for run in treatment_runs),
            "candidate_evaluations": dict(treatment_statuses),
            "boundary_failures": treatment_statuses["worker_boundary_failure"],
        },
        "conclusion": (
            "The boundary checker detected three risky process boundaries in two runs, "
            "but produced no correct or effective final candidate; H5 is not supported "
            "on the preregistered primary outcomes."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(compact, ensure_ascii=False, indent=2), encoding="utf-8")

    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    names = ["当前完整方法", "加入 Worker 边界检查"]
    effective = [compact["control"]["effective"], compact["worker_boundary"]["effective"]]
    fallback = [compact["control"]["safe_fallback"], compact["worker_boundary"]["safe_fallback"]]
    fig, ax = plt.subplots(figsize=(8.2, 4.8))
    ax.bar(names, effective, color="#2E7D32", label="有效并行")
    bars = ax.bar(names, fallback, bottom=effective, color="#64B5F6", label="安全回退")
    ax.bar_label(bars, labels=[str(value) for value in fallback], label_type="center")
    ax.set_ylim(0, 3.35)
    ax.set_yticks([0, 1, 2, 3])
    ax.set_ylabel("运行次数（每组 3 次）")
    ax.set_title("Radon Worker 边界实验：最终结果没有改善")
    ax.text(
        0.5,
        0.12,
        "新检查在中间候选中发现 3 次风险，但两组最终都没有有效并行结果",
        transform=ax.transAxes,
        ha="center",
        fontsize=10,
    )
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=2, frameon=False)
    ax.grid(axis="y", alpha=0.2)
    fig.tight_layout()
    args.figure.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.figure, dpi=180, bbox_inches="tight")
    plt.close(fig)
    print(json.dumps(compact, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
