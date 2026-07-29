#!/usr/bin/env python3
"""Verify the frozen first-stage research package without calling any LLM API."""

from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "docs" / "data"


class VerificationError(RuntimeError):
    """Raised when a release invariant is not satisfied."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def load_json(path: Path) -> dict:
    require(path.is_file(), f"缺少文件：{path.relative_to(ROOT)}")
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_csv(path: Path) -> list[dict[str, str]]:
    require(path.is_file(), f"缺少文件：{path.relative_to(ROOT)}")
    # Excel-compatible CSV artifacts include a UTF-8 BOM.
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def verify_required_files() -> None:
    required = [
        ROOT / "README.md",
        ROOT / "pyproject.toml",
        ROOT / "configs" / "configuration_search_formal.yaml",
        ROOT / "configs" / "task_fusion_formal.yaml",
        ROOT / "configs" / "dag_scheduling_formal.yaml",
        ROOT / "docs" / "advisor-report-01.md",
        ROOT / "docs" / "advisor-talk-01.md",
        ROOT / "docs" / "advisor-message-01.md",
        ROOT / "docs" / "advisor-demo.md",
        ROOT / "docs" / "literature-notes.md",
    ]
    missing = [str(path.relative_to(ROOT)) for path in required if not path.is_file()]
    require(not missing, f"缺少第一阶段交付文件：{', '.join(missing)}")


def verify_configuration_ablation() -> dict[str, float]:
    base = DATA / "configuration_ablation_20260729"
    overall = load_json(base / "configuration_search_overall.json")
    manifest = load_json(base / "experiment_manifest.json")
    rows = load_csv(base / "configuration_search_aggregate.csv")

    require(overall["workloads"] == 8, "配置消融应覆盖 8 个任务")
    require(overall["runs"] == 24, "配置消融应包含 24 个独立作业")
    require(len(rows) == 8, "配置消融汇总 CSV 应有 8 行")
    require(manifest["total_jobs"] == manifest["completed_jobs"] == 24, "24 个作业未全部完成")
    require(not manifest["failed_jobs"], "配置消融中存在失败作业")
    require(manifest["tuning_and_holdout_separated"], "搜索与留出评测没有分离")
    require(manifest["small_sample_scale_confirmation"], "缺少完整规模确认阶段")

    selected = float(overall["selected_speedup_macro_mean"])
    fixed = float(overall["fixed_speedup_macro_mean"])
    selected_regression = float(overall["selected_regression_rate"])
    fixed_regression = float(overall["fixed_regression_rate"])
    require(selected >= 1.10, "完整方法宏平均有效加速低于冻结阈值 1.10x")
    require(fixed < 1.0, "固定配置不再呈现总体性能退化，需重新核对报告")
    require(selected_regression == 0.0, "完整方法性能退化率不再为 0%")
    require(fixed_regression >= 0.70, "固定配置退化率低于冻结报告中的 70%")
    return {
        "selected_speedup": selected,
        "fixed_speedup": fixed,
        "selected_regression": selected_regression,
        "fixed_regression": fixed_regression,
    }


def verify_task_fusion() -> dict[str, float]:
    base = DATA / "task_fusion_20260729"
    overall = load_json(base / "task_fusion_overall.json")
    rows = load_csv(base / "task_fusion_summary.csv")
    require(overall["workloads"] == 2 and overall["repeats"] == 5, "任务融合实验规模不一致")
    require(overall["all_correct"], "任务融合候选未全部通过正确性验证")
    require(len(rows) == 6, "任务融合应包含 2 个任务 × 3 种策略")

    indexed = {(row["workload"], row["strategy"]): row for row in rows}
    chain_unfused = indexed[("large_intermediate_chain", "unfused")]
    chain_aware = indexed[("large_intermediate_chain", "aware")]
    fanout_fixed = indexed[("shared_heavy_fanout", "fixed_fused")]
    fanout_aware = indexed[("shared_heavy_fanout", "aware")]

    require(chain_aware["actual_strategy"] == "fused", "单消费者链未选择融合")
    require(int(chain_aware["intermediate_transfer_bytes"]) == 0, "融合后仍有中间传输")
    require(int(chain_aware["task_count"]) < int(chain_unfused["task_count"]), "融合未减少任务数")
    require(float(chain_aware["speedup_over_unfused"]) > 1.0, "单消费者链融合没有收益")
    require(float(fanout_fixed["speedup_over_unfused"]) < 1.0, "固定融合边界案例未发生退化")
    require(fanout_aware["actual_strategy"] == "unfused", "复用感知策略未保留共享生产者")
    return {
        "chain_aware_speedup": float(chain_aware["speedup_over_unfused"]),
        "fanout_fixed_speedup": float(fanout_fixed["speedup_over_unfused"]),
    }


def verify_dag_scheduling() -> dict[str, float]:
    base = DATA / "dag_scheduling_20260729"
    overall = load_json(base / "dag_scheduling_overall.json")
    rows = load_csv(base / "dag_scheduling_summary.csv")
    require(overall["graphs"] == 2, "DAG 调度实验应包含 2 张图")
    require(overall["critical_path_better_or_equal"], "关键路径策略未保持不劣")
    require(len(rows) == 4, "DAG 汇总应包含 2 张图 × 2 种策略")

    indexed = {(row["graph"], row["policy"]): row for row in rows}
    speedups: dict[str, float] = {}
    for graph in ("compute_critical", "communication_critical"):
        fifo = indexed[(graph, "fifo")]
        critical = indexed[(graph, "critical_path")]
        speedup = float(critical["speedup_over_fifo"])
        require(speedup > 1.0, f"{graph} 的关键路径策略没有缩短建模 makespan")
        require(
            float(critical["worker_idle_ratio"]) < float(fifo["worker_idle_ratio"]),
            f"{graph} 的关键路径策略没有降低 Worker 空闲比例",
        )
        speedups[graph] = speedup
    return speedups


def verify_report_claims(
    ablation: dict[str, float],
    fusion: dict[str, float],
    dag: dict[str, float],
) -> None:
    report_path = ROOT / "docs" / "advisor-report-01.md"
    report = report_path.read_text(encoding="utf-8")
    normalized_report = " ".join(report.split())
    expected_fragments = [
        f"{ablation['selected_speedup']:.3f}x",
        f"{ablation['fixed_regression']:.1%}",
        f"{fusion['chain_aware_speedup']:.2f}x",
        f"{fusion['fanout_fixed_speedup']:.3f}x",
        f"{dag['compute_critical']:.3f}x",
        f"{dag['communication_critical']:.3f}x",
        "确定性同构 Worker 列表调度模型",
        "不表述为真实 Ray 运行加速",
    ]
    missing = [fragment for fragment in expected_fragments if fragment not in normalized_report]
    require(not missing, f"导师报告缺少或未同步声明：{', '.join(missing)}")


def run_tests() -> None:
    with tempfile.TemporaryDirectory(prefix="parallel-agent-pytest-") as base_temp:
        env = os.environ.copy()
        src = str(ROOT / "src")
        env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "")
        command = [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            f"--basetemp={base_temp}",
        ]
        completed = subprocess.run(command, cwd=ROOT, env=env, check=False)
        require(completed.returncode == 0, "自动化测试未全部通过")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="验证第一阶段正式数据、文档声明和可选的自动化测试。"
    )
    parser.add_argument(
        "--run-tests",
        action="store_true",
        help="同时运行完整 pytest；不会调用 DeepSeek API。",
    )
    args = parser.parse_args()

    try:
        verify_required_files()
        ablation = verify_configuration_ablation()
        fusion = verify_task_fusion()
        dag = verify_dag_scheduling()
        verify_report_claims(ablation, fusion, dag)
        if args.run_tests:
            run_tests()
    except (VerificationError, KeyError, ValueError, csv.Error, json.JSONDecodeError) as exc:
        print(f"[失败] {exc}", file=sys.stderr)
        return 1

    print("[通过] 第一阶段科研交付包验收完成")
    print(
        "  配置消融："
        f"完整方法 {ablation['selected_speedup']:.3f}x，"
        f"固定配置 {ablation['fixed_speedup']:.3f}x，"
        f"退化率 {ablation['fixed_regression']:.1%} → "
        f"{ablation['selected_regression']:.1%}"
    )
    print(
        "  任务融合："
        f"单消费者链 {fusion['chain_aware_speedup']:.2f}x，"
        f"固定融合反例 {fusion['fanout_fixed_speedup']:.3f}x"
    )
    print(
        "  DAG 模型："
        f"计算关键图 {dag['compute_critical']:.3f}x，"
        f"通信关键图 {dag['communication_critical']:.3f}x"
    )
    print(f"  自动化测试：{'已运行' if args.run_tests else '未运行（使用 --run-tests 开启）'}")
    print("  DeepSeek API：未调用，费用为 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
