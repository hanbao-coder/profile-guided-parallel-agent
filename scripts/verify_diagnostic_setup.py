#!/usr/bin/env python3
"""Verify the project-level diagnostic protocol and screened candidates."""

from __future__ import annotations

from pathlib import Path
import sys

import yaml


ROOT = Path(__file__).resolve().parents[1]


class VerificationError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def main() -> int:
    required_documents = {
        "科研日志": ROOT / "docs" / "research-log.md",
        "诊断实验规范": ROOT / "docs" / "diagnostic-study.md",
        "相关工作": ROOT / "docs" / "related-work.md",
        "真实项目筛选": ROOT / "docs" / "candidate-screening.md",
    }
    config_path = ROOT / "configs" / "project_diagnostic.yaml"

    try:
        for label, path in required_documents.items():
            require(path.is_file(), f"缺少{label}：{path.relative_to(ROOT)}")
            content = path.read_text(encoding="utf-8")
            require(len(content.strip()) >= 500, f"{label}内容过短，无法支持研究追溯")

        require(config_path.is_file(), "缺少项目级诊断实验配置")
        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        study = config["study"]
        agent = config["agent"]
        execution = config["execution"]
        project_rules = config["required_project_properties"]
        taxonomy = config["failure_taxonomy"]

        require(study["phase"] == "diagnostic", "当前阶段必须保持为 diagnostic")
        require(
            study["research_question_status"] == "open"
            and not study["final_hypothesis_selected"],
            "诊断实验前不得提前冻结最终研究问题或假设",
        )
        require(
            int(agent["independent_runs_per_project"]) >= 3,
            "每个项目至少需要 3 次独立 Agent 运行",
        )
        require(
            int(execution["performance_repeats"]) >= 5,
            "正式性能测量至少需要重复 5 次",
        )
        require(
            execution["preserve_failed_runs"]
            and execution["preserve_raw_model_responses"]
            and execution["preserve_patches"],
            "必须保留失败实验、模型原始回答和代码补丁",
        )
        require(
            int(project_rules["minimum_source_files"]) >= 3,
            "诊断项目必须是至少 3 个源文件的多文件项目",
        )
        require(
            all(
                project_rules[key]
                for key in (
                    "fixed_entrypoint",
                    "deterministic_input",
                    "correctness_oracle",
                    "measurable_end_to_end_runtime",
                    "cpu_or_batch_stage",
                )
            ),
            "项目筛选规则缺少可复现性或可测量性要求",
        )
        required_failures = {
            "wrong_hotspot",
            "cross_file_dependency_failure",
            "correctness_failure",
            "local_speedup_without_end_to_end_gain",
            "end_to_end_performance_regression",
            "effective_parallelization",
        }
        require(
            required_failures <= set(taxonomy),
            "失败分类没有覆盖研究目标中的关键结果",
        )

        projects = config["projects"]
        require(
            isinstance(projects, list) and len(projects) >= 3,
            "M2 至少需要三个经过验证的真实项目",
        )
        for project in projects:
            project_id = project.get("id", "<missing id>")
            require(project.get("status") == "accepted", f"项目尚未通过筛选：{project_id}")
            require(
                int(project.get("source_files", 0))
                >= int(project_rules["minimum_source_files"]),
                f"项目不是多文件项目：{project_id}",
            )
            require(
                len(str(project.get("commit", ""))) == 40,
                f"项目没有固定到提交哈希：{project_id}",
            )
            workload = project.get("workload", {})
            oracle = project.get("correctness_oracle", {})
            require(
                float(workload.get("baseline_median_seconds", 0)) > 0
                and workload.get("stable_output") is True,
                f"项目基线不稳定：{project_id}",
            )
            require(
                bool(oracle.get("project_tests")) and bool(oracle.get("output_check")),
                f"项目正确性判定不完整：{project_id}",
            )
    except (VerificationError, KeyError, TypeError, ValueError, yaml.YAMLError) as exc:
        print(f"[失败] {exc}", file=sys.stderr)
        return 1

    print("[通过] M0 项目级诊断研究设置验收完成")
    print("  最终研究问题：保持开放")
    print("  诊断重复：每项目至少 3 次 Agent 运行")
    print("  性能重复：每个正式候选至少 5 次")
    print("  证据保留：失败、原始回答和补丁均为强制项")
    print(f"  M2 已筛选真实项目：{len(config['projects'])} 个")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
