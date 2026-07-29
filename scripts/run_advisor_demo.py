#!/usr/bin/env python3
"""Run a short, offline advisor demo using live analysis and frozen formal data."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from parallel_agent.analyzer import analyze_file  # noqa: E402


def read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def print_step(number: int, title: str) -> None:
    print()
    print(f"[{number}/4] {title}")


def build_demo_summary() -> dict:
    prefix_path = ROOT / "benchmarks" / "prefix_sum" / "serial.py"
    prefix = analyze_file(prefix_path)

    ablation_root = ROOT / "docs" / "data" / "configuration_ablation_20260729"
    aggregate_rows = read_csv(ablation_root / "configuration_search_aggregate.csv")
    aggregate = {row["workload"]: row for row in aggregate_rows}
    load_imbalance = read_json(
        ablation_root / "representative_runs" / "load_imbalance_run01.json"
    )

    fingerprints = {
        row["result_fingerprint"]
        for row in load_imbalance["holdout"]["runs"]
        if row["returncode"] == 0
    }
    load_selection = load_imbalance["selection"]["selected_configuration"]
    load_holdout = load_imbalance["holdout"]
    tiny = aggregate["tiny_tasks"]

    return {
        "demo_type": "offline_live_analysis_plus_frozen_formal_results",
        "deepseek_api_called": False,
        "prefix_sum": {
            "evidence_type": "live_static_analysis",
            "parallelizable": prefix.parallelizable,
            "hazards": prefix.hazards,
            "decision": "reject_parallelization",
        },
        "load_imbalance": {
            "evidence_type": "frozen_formal_holdout",
            "selected_workers": load_selection["workers"],
            "selected_chunks": load_selection["chunks"],
            "selected_speedup": load_holdout["selected_speedup"],
            "fixed_speedup": load_holdout["fixed_speedup"],
            "all_holdout_outputs_match": len(fingerprints) == 1,
            "decision": "keep_profiled_parallel_configuration",
        },
        "tiny_tasks": {
            "evidence_type": "frozen_three_run_aggregate",
            "selected_speedup_mean": float(tiny["selected_speedup_mean"]),
            "fixed_speedup_mean": float(tiny["fixed_speedup_mean"]),
            "serial_selection_rate": float(tiny["serial_selection_rate"]),
            "decision": "fall_back_to_serial",
        },
        "boundaries": [
            "Prefix Sum is analyzed live.",
            "Performance numbers are frozen formal multiprocessing results, not rerun live.",
            "DAG scheduling results are a deterministic model, not Ray runtime speedups.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="运行不调用 DeepSeek 的 3–5 分钟导师现场演示。"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="结果保存目录；默认写入 work/advisor-demo-时间戳。",
    )
    args = parser.parse_args()

    output_dir = args.output_dir
    if output_dir is None:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        output_dir = ROOT / "work" / f"advisor-demo-{stamp}"
    elif not output_dir.is_absolute():
        output_dir = ROOT / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    summary = build_demo_summary()

    print("=" * 66)
    print("Python 自动并行化 Agent：第一次导师汇报离线演示")
    print("说明：现场只做静态分析；性能数字来自已冻结的正式留出实验。")
    print("=" * 66)

    print_step(1, "依赖感知：不是看到循环就并行")
    prefix = summary["prefix_sum"]
    print(f"Prefix Sum 可并行：{prefix['parallelizable']}")
    print(f"检测到风险：{', '.join(prefix['hazards'])}")
    print("系统决策：拒绝朴素并行，避免语义错误。")

    print_step(2, "粒度搜索：不均衡任务选择更细的 Chunk")
    load = summary["load_imbalance"]
    print(
        f"选择配置：{load['selected_workers']} Worker / "
        f"{load['selected_chunks']} Chunk"
    )
    print(
        f"留出加速：自适应 {load['selected_speedup']:.3f}x；"
        f"固定 4/4 为 {load['fixed_speedup']:.3f}x"
    )
    print(f"所有留出运行输出指纹一致：{load['all_holdout_outputs_match']}")

    print_step(3, "收益 Gate：细粒度任务回退串行")
    tiny = summary["tiny_tasks"]
    print(
        f"Tiny Tasks：固定并行 {tiny['fixed_speedup_mean']:.3f}x；"
        f"优化方法 {tiny['selected_speedup_mean']:.3f}x"
    )
    print(f"串行选择率：{tiny['serial_selection_rate']:.0%}")
    print("系统决策：回退串行，避免为了并行而并行。")

    print_step(4, "实验边界")
    for boundary in summary["boundaries"]:
        print(f"- {boundary}")
    print("- 本演示不调用 DeepSeek，API 费用为 0。")

    output_path = output_dir / "advisor_demo_summary.json"
    output_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print()
    print(f"[完成] 演示记录：{output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
