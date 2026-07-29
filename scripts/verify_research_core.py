#!/usr/bin/env python3
"""Verify the current research core without calling an LLM or rerunning experiments."""

from __future__ import annotations

import argparse
from collections import Counter
import csv
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "docs" / "data"
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


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


def verify_ray_dataset(
    name: str, *, require_cluster_evidence: bool = False
) -> tuple[dict, list[dict[str, str]]]:
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
            if require_cluster_evidence:
                cluster = report.get("ray_cluster")
                require(
                    isinstance(cluster, dict),
                    f"{report_path.name} 缺少 Ray 集群证据",
                )
                require(
                    cluster["physical_node_count"] == 1
                    and not cluster["multi_node"],
                    f"{report_path.name} 不是声明的 WSL2 单节点实验",
                )
                require(
                    cluster["executed_node_count"] == 1
                    and not cluster["executed_on_multiple_nodes"],
                    f"{report_path.name} 的任务执行节点声明不一致",
                )
                expected_counts: Counter[str] = Counter()
                for run in report["runs"]:
                    counts = run.get("execution_node_counts")
                    require(
                        isinstance(counts, dict),
                        f"{report_path.name} 缺少逐次节点任务计数",
                    )
                    expected_counts.update(
                        {
                            str(node_id): int(count)
                            for node_id, count in counts.items()
                        }
                    )
                    if counts:
                        require(
                            sum(int(count) for count in counts.values())
                            == int(run["task_count"]),
                            f"{report_path.name} 的任务数与节点计数不一致",
                        )
                require(
                    dict(expected_counts)
                    == cluster["task_executions_by_node"],
                    f"{report_path.name} 的聚合节点计数无法由原始运行恢复",
                )
    return overall, aggregate


def indexed(rows: list[dict[str, str]]) -> dict[tuple[str, str], dict[str, str]]:
    return {(row["benchmark"], row["mode"]): row for row in rows}


def verify_variance_improvement() -> dict[str, float]:
    before, before_rows = verify_ray_dataset("wsl_ray_formal_20260729")
    variance, _variance_rows = verify_ray_dataset(
        "wsl_ray_variance_20260730"
    )
    after, after_rows = verify_ray_dataset(
        "wsl_ray_cluster_ready_20260730",
        require_cluster_evidence=True,
    )
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
    variance_speedup = float(
        variance["mode_summary"]["optimized"]["warm_speedup_macro_mean"]
    )
    require(
        abs(
            float(after_optimized["warm_speedup_macro_mean"])
            - variance_speedup
        )
        / variance_speedup
        < 0.2,
        "当前实现与上一轮方差感知正式结果偏差超过 20%",
    )
    require(
        after_optimized["warm_regression_rate"]
        <= variance["mode_summary"]["optimized"]["warm_regression_rate"],
        "当前实现的性能退化率高于上一轮正式结果",
    )

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
        "optimized_beats_naive_rate": float(
            after["optimized_beats_naive_rate"]
        ),
        "variance_speedup": variance_speedup,
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


def verify_loop_frontend_contract() -> None:
    from parallel_agent.loop_frontend import (
        load_verified_normalization,
        normalize_serial_loop,
    )
    from parallel_agent.runner import load_workload

    with tempfile.TemporaryDirectory(prefix="parallel-agent-loop-") as temp:
        output = Path(temp) / "normalized.py"
        normalization = normalize_serial_loop(
            ROOT / "examples" / "simple_serial_loop.py",
            output_path=output,
            entry_function="run_serial",
        )
        verified = load_verified_normalization(output)
        require(verified is not None, "普通循环标准化元数据无法重新验证")
        require(
            verified.output_sha256 == normalization.output_sha256,
            "普通循环包装器哈希不一致",
        )
        workload = load_workload(output)
        items = workload.make_input(2, 42)
        result = workload.combine(
            [workload.unit(item) for item in items]
        )
        require(result == 1767, "普通循环标准化后语义发生变化")

    evidence = DATA / "loop_frontend_20260730"
    rejected = load_json(evidence / "first_rejection" / "run_report.json")
    accepted = load_json(evidence / "accepted" / "run_report.json")
    analysis = load_json(evidence / "accepted" / "analysis.json")
    plan = load_json(evidence / "accepted" / "parallel_plan.json")
    trace = load_json(evidence / "accepted" / "model_trace.json")
    require(rejected["status"] == "rejected", "缺少前端语义丢失的首轮拒绝证据")
    require(
        accepted["status"] == "accepted" and accepted["correct"],
        "普通循环 DeepSeek-Ray 证据未通过正确性门",
    )
    require(
        analysis["parallelizable"] and analysis["loops"] == 1,
        "修复后的模型分析没有保留原始循环语义",
    )
    require(
        plan["backend"] == "ray" and plan["parallelizable"],
        "普通循环最终计划未绑定 Ray",
    )
    attempt = accepted["attempts"][0]
    require(
        attempt["serial"]["payload"]["result"] == 3491
        and attempt["parallel"]["payload"]["result"] == 3491
        and attempt["parallel"]["payload"]["task_count"] == 2,
        "普通循环串行/Ray 结果或任务数证据不一致",
    )
    calls = trace["calls"]
    require(
        [call["model"] for call in calls]
        == ["deepseek-v4-pro", "deepseek-v4-flash"],
        "普通循环在线证据未遵循 Pro/Flash 路由",
    )
    require(
        sum(int(call["total_tokens"]) for call in calls) == 2435,
        "普通循环在线证据 Token 汇总发生漂移",
    )


def verify_ray_smoke(path: Path) -> None:
    report = load_json(path.resolve())
    require(report["backend"] == "ray", "Ray 冒烟报告使用了错误后端")
    require(
        all(summary["correct"] for summary in report["summary"].values()),
        "Ray 冒烟报告存在错误结果",
    )
    cluster = report.get("ray_cluster")
    require(isinstance(cluster, dict), "Ray 冒烟报告缺少集群证据")
    require(cluster["alive_nodes"] >= 1, "Ray 冒烟未发现存活节点")
    require(
        cluster["physical_node_count"] >= 1,
        "Ray 冒烟未记录物理节点地址",
    )
    require(
        cluster["executed_node_count"] >= 1,
        "Ray 冒烟未记录任务实际执行节点",
    )
    require(
        set(cluster["executed_node_ids"])
        <= {node["node_id"] for node in cluster["nodes"]},
        "任务执行节点不属于报告中的存活集群节点",
    )
    require(
        cluster["executed_on_multiple_nodes"]
        == (cluster["executed_node_count"] >= 2),
        "实际多节点执行标志与节点计数不一致",
    )
    expected_counts: Counter[str] = Counter()
    for run in report["runs"]:
        counts = run.get("execution_node_counts")
        require(isinstance(counts, dict), "Ray 冒烟缺少逐次节点任务计数")
        expected_counts.update(
            {
                str(node_id): int(count)
                for node_id, count in counts.items()
            }
        )
        if counts:
            require(
                sum(int(count) for count in counts.values())
                == int(run["task_count"]),
                "Ray 冒烟的任务数与节点计数不一致",
            )
    require(
        dict(expected_counts) == cluster["task_executions_by_node"],
        "Ray 冒烟的聚合节点计数无法由原始运行恢复",
    )


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
    parser.add_argument(
        "--ray-smoke",
        type=Path,
        help="可选：验证一次当前版本生成的真实 Ray 冒烟报告。",
    )
    arguments = parser.parse_args()
    try:
        metrics = verify_variance_improvement()
        verify_agent_ray_contract()
        verify_loop_frontend_contract()
        if arguments.ray_smoke:
            verify_ray_smoke(arguments.ray_smoke)
        if arguments.run_tests:
            run_tests()
    except (VerificationError, KeyError, ValueError, csv.Error, json.JSONDecodeError) as exc:
        print(f"[失败] {exc}", file=sys.stderr)
        return 1

    print("[通过] 当前研究核心验收完成")
    print(
        "  当前 M2："
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
        f"{metrics['optimized_over_naive_geomean']:.3f}x，"
        f"胜率 {metrics['optimized_beats_naive_rate']:.1%}"
    )
    print(
        "  Ray 集群冒烟："
        f"{'已验证' if arguments.ray_smoke else '未提供'}"
    )
    print("  普通串行循环前端：已验证")
    print(f"  自动化测试：{'已运行' if arguments.run_tests else '未运行'}")
    print("  DeepSeek API：未调用，费用为 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
