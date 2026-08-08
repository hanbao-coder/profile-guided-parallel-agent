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
        if (path.parent / "exclusion.json").is_file():
            continue
        outcome = _read(path)
        for event in outcome.get("agent", {}).get("events", []):
            evaluation = event.get("observation", {}).get("candidate_evaluation")
            if isinstance(evaluation, dict) and evaluation.get("status"):
                counts[str(evaluation["status"])] += 1
    return counts


def _boundary_finding_kinds(results_root: Path) -> Counter[str]:
    counts: Counter[str] = Counter()
    for path in sorted(results_root.glob("radon/*/outcome.json")):
        if (path.parent / "exclusion.json").is_file():
            continue
        outcome = _read(path)
        for event in outcome.get("agent", {}).get("events", []):
            evaluation = event.get("observation", {}).get("candidate_evaluation")
            if not isinstance(evaluation, dict):
                continue
            report = evaluation.get("worker_boundary_report")
            if not isinstance(report, dict):
                continue
            for finding in report.get("findings", []):
                if isinstance(finding, dict) and finding.get("kind"):
                    counts[str(finding["kind"])] += 1
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
    parser.add_argument(
        "--reference-summary",
        type=Path,
        default=ROOT / "docs/data/radon-manual-reference-summary.json",
    )
    parser.add_argument("--output", type=Path, default=ROOT / "docs/data/m7-worker-boundary.json")
    parser.add_argument("--figure", type=Path, default=ROOT / "docs/figures/m7-worker-boundary.png")
    args = parser.parse_args()

    control_runs = _radon_runs(_read(args.control_summary))
    treatment_runs = _radon_runs(_read(args.treatment_summary))
    treatment_statuses = _candidate_statuses(args.treatment_results)
    finding_kinds = _boundary_finding_kinds(args.treatment_results)
    reference = _read(args.reference_summary)
    reference_effective = bool(reference.get("effective_at_1_05"))
    study_status = (
        "complete" if len(treatment_runs) >= 3 and reference_effective
        else "terminated_invalid_reference" if not reference_effective
        else "pending"
    )
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
            "boundary_findings": dict(finding_kinds),
            "boundary_failures": sum(
                count for kind, count in finding_kinds.items() if kind != "syntax_error"
            ),
        },
        "reference": {
            "speedup": reference.get("speedup"),
            "effective_at_1_05": reference_effective,
        },
        "study_complete": study_status == "complete",
        "study_status": study_status,
        "conclusion": (
            "The preregistered treatment has three valid runs and produced no correct "
            "or effective final candidate; H5 is not supported on the primary outcomes."
            if study_status == "complete"
            else (
                "The study was terminated because the manual reference achieved less "
                "than the preregistered 1.05x speedup, invalidating the performance premise."
                if study_status == "terminated_invalid_reference"
                else "The treatment has fewer than three valid runs, so H5 remains pending."
            )
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(compact, ensure_ascii=False, indent=2), encoding="utf-8")

    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    names = [
        f"当前完整方法（{compact['control']['runs']} 次）",
        f"Worker 边界检查（{compact['worker_boundary']['runs']} 次有效运行）",
    ]
    effective = [compact["control"]["effective"], compact["worker_boundary"]["effective"]]
    fallback = [compact["control"]["safe_fallback"], compact["worker_boundary"]["safe_fallback"]]
    fig, ax = plt.subplots(figsize=(8.2, 4.8))
    ax.bar(names, effective, color="#2E7D32", label="有效并行")
    bars = ax.bar(names, fallback, bottom=effective, color="#64B5F6", label="安全回退")
    ax.bar_label(bars, labels=[str(value) for value in fallback], label_type="center")
    ax.set_ylim(0, 3.35)
    ax.set_yticks([0, 1, 2, 3])
    ax.set_ylabel("运行次数")
    title = {
        "terminated_invalid_reference": "Radon Worker 边界支线：性能前提失效后终止",
        "pending": "Radon Worker 边界实验：等待补齐运行",
        "complete": "Radon Worker 边界实验：最终结果没有改善",
    }[compact["study_status"]]
    ax.set_title(title)
    ax.text(
        0.5,
        0.92,
        (
            f"人工参考仅 {compact['reference']['speedup']:.4f}×，未达到 1.05× 门槛；"
            "两次 Agent 运行只保留为探索证据"
            if compact["study_status"] == "terminated_invalid_reference"
            else
            f"当前发现 {compact['worker_boundary']['boundary_failures']} 次边界风险；"
            "有效运行不足 3 次，暂不下最终结论"
            if compact["study_status"] == "pending"
            else f"新检查发现 {compact['worker_boundary']['boundary_failures']} 次边界风险，"
            "但两组最终都没有有效并行结果"
        ),
        transform=ax.transAxes,
        ha="center",
        fontsize=10,
        bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.85},
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
