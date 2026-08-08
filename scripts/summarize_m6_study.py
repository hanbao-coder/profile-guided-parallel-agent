#!/usr/bin/env python3
"""Create compact study tables and Chinese figures from repository runs."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt


ROOT = Path(__file__).resolve().parents[1]

OUTCOME_GROUPS = {
    "effective_parallelization": "有效并行化",
    "safe_serial_fallback": "安全回退",
    "analysis_nonconvergence": "未形成方案",
    "patch_application_failure": "未形成方案",
    "correctness_failure": "错误修改",
    "integration_or_output_failure": "错误修改",
    "end_to_end_performance_regression": "错误修改",
    "non_parallel_candidate": "未形成方案",
    "no_meaningful_end_to_end_gain": "无明显收益",
    "performance_measurement_failure": "测量失败",
}

DISPLAY_NAMES = {
    "ordinary": "普通 Agent",
    "contract_only": "仅语义约束",
    "full": "完整方法",
}


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _group_counts(summary: dict[str, Any]) -> Counter[str]:
    grouped: Counter[str] = Counter()
    for run in summary["runs"]:
        outcome = str(run["primary_outcome"])
        grouped[OUTCOME_GROUPS.get(outcome, outcome)] += 1
    return grouped


def _full_feedback_counts(results_root: Path) -> Counter[str]:
    counts: Counter[str] = Counter()
    for path in sorted(results_root.glob("*/*/outcome.json")):
        outcome = _read_json(path)
        for event in outcome.get("agent", {}).get("events", []):
            evaluation = event.get("observation", {}).get("candidate_evaluation")
            if isinstance(evaluation, dict) and evaluation.get("status"):
                counts[str(evaluation["status"])] += 1
    return counts


def _configure_chinese_font() -> None:
    plt.rcParams["font.sans-serif"] = [
        "Microsoft YaHei",
        "SimHei",
        "Noto Sans CJK SC",
        "DejaVu Sans",
    ]
    plt.rcParams["axes.unicode_minus"] = False


def _plot_overall(rows: list[dict[str, Any]], output: Path) -> None:
    labels = ["有效并行化", "安全回退", "错误修改", "未形成方案", "无明显收益", "测量失败"]
    colors = ["#2E7D32", "#64B5F6", "#D65F5F", "#B0BEC5", "#FFB74D", "#8E7CC3"]
    names = [row["method_name"] for row in rows]
    bottoms = [0] * len(rows)
    fig, ax = plt.subplots(figsize=(9, 5.2))
    for label, color in zip(labels, colors):
        values = [int(row["grouped_counts"].get(label, 0)) for row in rows]
        ax.bar(names, values, bottom=bottoms, label=label, color=color)
        for index, value in enumerate(values):
            if value:
                ax.text(index, bottoms[index] + value / 2, str(value), ha="center", va="center", fontsize=10)
        bottoms = [bottom + value for bottom, value in zip(bottoms, values)]
    ax.set_ylabel("运行次数")
    ax.set_title("三种方法的最终结果")
    ax.legend(ncol=3, loc="upper center", bbox_to_anchor=(0.5, -0.12), frameon=False)
    ax.grid(axis="y", alpha=0.2)
    fig.tight_layout()
    fig.savefig(output, dpi=180, bbox_inches="tight")
    plt.close(fig)


def _plot_mkdocs(rows: list[dict[str, Any]], output: Path) -> None:
    categories = ["有效并行化", "安全回退", "错误修改", "未形成方案"]
    colors = ["#2E7D32", "#64B5F6", "#D65F5F", "#B0BEC5"]
    names = [row["method_name"] for row in rows]
    bottoms = [0] * len(rows)
    fig, ax = plt.subplots(figsize=(8.2, 4.8))
    for category, color in zip(categories, colors):
        values = [int(row["mkdocs_counts"].get(category, 0)) for row in rows]
        ax.bar(names, values, bottom=bottoms, label=category, color=color)
        for index, value in enumerate(values):
            if value:
                ax.text(index, bottoms[index] + value / 2, str(value), ha="center", va="center")
        bottoms = [bottom + value for bottom, value in zip(bottoms, values)]
    ax.set_ylim(0, 3.35)
    ax.set_yticks([0, 1, 2, 3])
    ax.set_ylabel("运行次数（每组 3 次）")
    ax.set_title("MkDocs 消融实验：反馈与回退能否避免错误交付")
    ax.legend(ncol=2, loc="upper center", bbox_to_anchor=(0.5, -0.13), frameon=False)
    ax.grid(axis="y", alpha=0.2)
    fig.tight_layout()
    fig.savefig(output, dpi=180, bbox_inches="tight")
    plt.close(fig)


def _plot_feedback(counts: Counter[str], output: Path) -> None:
    translations = {
        "correctness_failure": "测试失败",
        "integration_or_output_failure": "输出或集成失败",
        "end_to_end_performance_regression": "整体变慢",
        "no_meaningful_end_to_end_gain": "加速不足 5%",
        "non_parallel_candidate": "没有实际并行结构",
        "effective_end_to_end_gain": "候选被接受",
    }
    ordered = sorted(counts.items(), key=lambda item: item[1], reverse=True)
    labels = [translations.get(name, name) for name, _ in ordered]
    values = [value for _, value in ordered]
    colors = ["#2E7D32" if name == "effective_end_to_end_gain" else "#D65F5F" for name, _ in ordered]
    fig, ax = plt.subplots(figsize=(9, 5.2))
    bars = ax.barh(labels[::-1], values[::-1], color=colors[::-1])
    ax.bar_label(bars, padding=3)
    ax.set_xlabel("候选方案次数")
    ax.set_title("完整方法在反馈阶段发现的问题")
    ax.grid(axis="x", alpha=0.2)
    fig.tight_layout()
    fig.savefig(output, dpi=180, bbox_inches="tight")
    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ordinary", type=Path, default=ROOT / "results/m5/corrected-b0-summary.json")
    parser.add_argument("--contract-only", type=Path, default=ROOT / "results/m6/ablation-contract-only-summary.json")
    parser.add_argument("--full", type=Path, default=ROOT / "results/m5/corrected-final-summary.json")
    parser.add_argument("--full-results-root", type=Path, default=ROOT / "results/m5/corrected-final")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "docs/data")
    parser.add_argument("--figure-dir", type=Path, default=ROOT / "docs/figures")
    args = parser.parse_args()

    summaries = {
        "ordinary": _read_json(args.ordinary),
        "contract_only": _read_json(args.contract_only),
        "full": _read_json(args.full),
    }
    rows: list[dict[str, Any]] = []
    for method, summary in summaries.items():
        grouped = _group_counts(summary)
        mkdocs = {
            "runs": [run for run in summary["runs"] if run["project"] == "mkdocs"]
        }
        rows.append(
            {
                "method": method,
                "method_name": DISPLAY_NAMES[method],
                "run_count": len(summary["runs"]),
                "grouped_counts": dict(grouped),
                "mkdocs_counts": dict(_group_counts(mkdocs)),
                "effective_rate": grouped["有效并行化"] / len(summary["runs"]),
                "unsafe_change_rate": grouped["错误修改"] / len(summary["runs"]),
                "model_calls": sum(int(run.get("model_calls") or 0) for run in summary["runs"]),
                "model_tokens": sum(int(run.get("model_tokens") or 0) for run in summary["runs"]),
            }
        )

    per_project: list[dict[str, Any]] = []
    for project in sorted({run["project"] for run in summaries["full"]["runs"]}):
        record: dict[str, Any] = {"project": project}
        for method in ("ordinary", "full"):
            project_summary = {
                "runs": [
                    run for run in summaries[method]["runs"] if run["project"] == project
                ]
            }
            record[method] = dict(_group_counts(project_summary))
            effective_speedups = [
                run["speedup"]
                for run in project_summary["runs"]
                if run["primary_outcome"] == "effective_parallelization"
                and run.get("speedup") is not None
            ]
            record[f"{method}_effective_speedups"] = effective_speedups
        per_project.append(record)

    feedback_counts = _full_feedback_counts(args.full_results_root)
    compact = {
        "schema_version": 1,
        "definitions": {
            "effective_parallelization": "测试和输出正确，且端到端加速至少 5%",
            "safe_fallback": "候选方案未通过验证，系统明确恢复原串行代码",
            "unsafe_change": "候选修改被保留，但测试、输出或端到端性能不合格",
        },
        "methods": rows,
        "per_project": per_project,
        "full_method_candidate_evaluations": dict(feedback_counts),
        "notes": [
            "普通 Agent 和完整方法各覆盖 4 个真实项目，每个项目独立运行 3 次。",
            "仅语义约束消融只在 MkDocs 上运行 3 次，因此只与 MkDocs 子集比较。",
            "安全回退不等于并行化成功，它只说明系统没有交付已知错误或变慢的修改。",
        ],
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    args.figure_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "m6-study-summary.json").write_text(
        json.dumps(compact, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    with (args.output_dir / "m6-study-summary.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "method",
                "method_name",
                "run_count",
                "effective_count",
                "safe_fallback_count",
                "unsafe_change_count",
                "no_candidate_count",
                "effective_rate",
                "unsafe_change_rate",
            ],
        )
        writer.writeheader()
        for row in rows:
            grouped = row["grouped_counts"]
            writer.writerow(
                {
                    "method": row["method"],
                    "method_name": row["method_name"],
                    "run_count": row["run_count"],
                    "effective_count": grouped.get("有效并行化", 0),
                    "safe_fallback_count": grouped.get("安全回退", 0),
                    "unsafe_change_count": grouped.get("错误修改", 0),
                    "no_candidate_count": grouped.get("未形成方案", 0),
                    "effective_rate": row["effective_rate"],
                    "unsafe_change_rate": row["unsafe_change_rate"],
                }
            )

    _configure_chinese_font()
    _plot_overall([rows[0], rows[2]], args.figure_dir / "m6-overall-outcomes.png")
    _plot_mkdocs(rows, args.figure_dir / "m6-mkdocs-ablation.png")
    _plot_feedback(feedback_counts, args.figure_dir / "m6-feedback-findings.png")
    print(json.dumps(compact, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
