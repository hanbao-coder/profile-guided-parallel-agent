#!/usr/bin/env python3
"""Verify the current research core without calling an LLM or rerunning experiments."""

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
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def load_json(path: Path) -> dict:
    require(path.is_file(), f"缺少文件：{path.relative_to(ROOT)}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_csv(path: Path) -> list[dict[str, str]]:
    require(path.is_file(), f"缺少文件：{path.relative_to(ROOT)}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def verify_ray_dataset(name: str) -> tuple[dict, list[dict[str, str]]]:
    base = DATA / name
    overall = load_json(base / "summary" / "ray_formal_overall.json")
    aggregate = load_csv(base / "summary" / "ray_formal_aggregate.csv")
    require(overall["independent_runs"] == 3, f"{name} 应有 3 轮独立运行")
    require(overall["workloads"] == 8, f"{name} 应覆盖 8 个工作负载")
    require(overall["modes"] == 3, f"{name} 应包含 M0/M1/M2")
    require(overall["formal_measurements"] == 360, f"{name} 应有 360 次正式计时")
    require(overall["all_correct"], f"{name} 存在错误结果")
    require(len(aggregate) == 24, f"{name} 聚合表应有 24 行")

    for run_index in range(1, 4):
        run_dir = base / f"run_{run_index:02d}"
        rows = load_csv(run_dir / "suite_large.csv")
        reports = sorted(run_dir.glob("*_large.json"))
        require(len(rows) == 24, f"{run_dir.name} 的方法矩阵不完整")
        require(len(reports) == 8, f"{run_dir.name} 应有 8 份原始报告")
        require(
            all(row["correct"].lower() == "true" for row in rows),
            f"{run_dir.name} 存在错误汇总行",
        )
        for report_path in reports:
            report = load_json(report_path)
            require(
                all(
                    report["summary"][mode]["correct"]
                    for mode in ("serial", "naive", "optimized")
                ),
                f"{report_path.name} 存在错误方法结果",
            )
    return overall, aggregate


def indexed(rows: list[dict[str, str]]) -> dict[tuple[str, str], dict[str, str]]:
    return {(row["benchmark"], row["mode"]): row for row in rows}


def verify_variance_improvement() -> dict[str, float]:
    before, before_rows = verify_ray_dataset("wsl_ray_formal_20260729")
    after, after_rows = verify_ray_dataset("wsl_ray_variance_20260730")
    before_optimized = before["mode_summary"]["optimized"]
    after_optimized = after["mode_summary"]["optimized"]
    require(
        after_optimized["warm_speedup_macro_mean"]
        > before_optimized["warm_speedup_macro_mean"],
        "方差感知版本没有提高 M2 宏平均加速",
    )
    require(
        after_optimized["warm_regression_rate"]
        < before_optimized["warm_regression_rate"],
        "方差感知版本没有降低 M2 退化率",
    )

    old_index = indexed(before_rows)
    new_index = indexed(after_rows)
    old_load = float(
        old_index[("load_imbalance", "optimized")]["warm_speedup_mean"]
    )
    new_load = float(
        new_index[("load_imbalance", "optimized")]["warm_speedup_mean"]
    )
    require(new_load > old_load * 2.0, "负载不均衡案例未获得预期修复")

    for row in after_rows:
        require(
            row.get("parallel_overhead_ratio_mean") not in {None, ""},
            "正式聚合缺少并行开销指标",
        )
        require(
            row.get("first_use_parallel_overhead_ratio_mean") not in {None, ""},
            "正式聚合缺少首次使用并行开销指标",
        )
    return {
        "before_speedup": float(before_optimized["warm_speedup_macro_mean"]),
        "after_speedup": float(after_optimized["warm_speedup_macro_mean"]),
        "before_regression": float(before_optimized["warm_regression_rate"]),
        "after_regression": float(after_optimized["warm_regression_rate"]),
        "old_load_imbalance": old_load,
        "new_load_imbalance": new_load,
        "optimized_over_naive_geomean": float(
            after["optimized_over_naive_geometric_mean"]
        ),
    }


def verify_agent_ray_contract() -> None:
    generator = (ROOT / "src" / "parallel_agent" / "generator.py").read_text(
        encoding="utf-8"
    )
    pipeline = (
        ROOT / "src" / "parallel_agent" / "agent_pipeline.py"
    ).read_text(encoding="utf-8")
    notebook = (ROOT / "docs" / "research-notebook.md").read_text(
        encoding="utf-8"
    )
    plan_schema = load_json(ROOT / "schemas" / "parallel_plan.schema.json")
    require("remote_run_chunk = ray.remote(run_chunk)" in generator, "候选模板未接入 Ray")
    require("execution_backend" in pipeline, "Agent 管道未传递执行后端")
    require(
        "ray" in plan_schema["properties"]["backend"]["enum"],
        "结构化并行计划 Schema 未声明 Ray 后端",
    )
    require("DeepSeek Agent" in notebook and "结果 `3491` 一致" in notebook, "缺少 Agent-Ray 验证记录")


def run_tests() -> None:
    with tempfile.TemporaryDirectory(prefix="parallel-agent-core-") as base_temp:
        environment = os.environ.copy()
        source = str(ROOT / "src")
        environment["PYTHONPATH"] = source + os.pathsep + environment.get(
            "PYTHONPATH", ""
        )
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "-p",
                "no:cacheprovider",
                f"--basetemp={base_temp}",
            ],
            cwd=ROOT,
            env=environment,
            check=False,
        )
        require(completed.returncode == 0, "自动化测试未全部通过")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="验证当前研究核心、正式 Ray 数据与可选自动化测试。"
    )
    parser.add_argument("--run-tests", action="store_true")
    arguments = parser.parse_args()
    try:
        metrics = verify_variance_improvement()
        verify_agent_ray_contract()
        if arguments.run_tests:
            run_tests()
    except (VerificationError, KeyError, ValueError, csv.Error, json.JSONDecodeError) as exc:
        print(f"[失败] {exc}", file=sys.stderr)
        return 1

    print("[通过] 当前研究核心验收完成")
    print(
        "  方差感知 M2："
        f"{metrics['before_speedup']:.3f}x → {metrics['after_speedup']:.3f}x，"
        f"退化率 {metrics['before_regression']:.1%} → "
        f"{metrics['after_regression']:.1%}"
    )
    print(
        "  Load Imbalance："
        f"{metrics['old_load_imbalance']:.3f}x → "
        f"{metrics['new_load_imbalance']:.3f}x"
    )
    print(
        "  M2/M1 几何平均："
        f"{metrics['optimized_over_naive_geomean']:.3f}x"
    )
    print(f"  自动化测试：{'已运行' if arguments.run_tests else '未运行'}")
    print("  DeepSeek API：未调用，费用为 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
