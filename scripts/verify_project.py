#!/usr/bin/env python3
"""Run every frozen and current project verification gate without an LLM."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def _run(label: str, command: list[str]) -> bool:
    print(f"[项目验收] {label}", flush=True)
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env={
            **os.environ,
            "PYTHONPATH": str(ROOT / "src")
            + os.pathsep
            + os.environ.get("PYTHONPATH", ""),
        },
        check=False,
    )
    if completed.returncode != 0:
        print(
            f"[项目验收失败] {label}，退出码 {completed.returncode}",
            file=sys.stderr,
        )
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "统一验证历史消融、调度/融合、当前 Ray 数据、普通循环前端和测试。"
        )
    )
    parser.add_argument(
        "--run-tests",
        action="store_true",
        help="在当前研究核心验收中运行一次完整 pytest。",
    )
    parser.add_argument(
        "--ray-smoke",
        type=Path,
        help="可选：同时验证一次当前代码生成的真实 Ray 冒烟报告。",
    )
    arguments = parser.parse_args()

    first_stage = [
        sys.executable,
        str(ROOT / "scripts" / "verify_first_stage.py"),
    ]
    current = [
        sys.executable,
        str(ROOT / "scripts" / "verify_research_core.py"),
    ]
    diagnostic = [
        sys.executable,
        str(ROOT / "scripts" / "verify_diagnostic_setup.py"),
    ]
    if arguments.run_tests:
        current.append("--run-tests")
    if arguments.ray_smoke:
        current.extend(
            ["--ray-smoke", str(arguments.ray_smoke.resolve())]
        )

    if not _run("历史消融、任务融合与 DAG 调度证据", first_stage):
        return 1
    if not _run("当前 Ray、Agent、普通循环前端与自动化测试", current):
        return 1
    if not _run("项目级诊断研究设置", diagnostic):
        return 1

    print("[通过] 完整项目验收完成")
    print(
        "  覆盖：历史证据 + 当前 Ray/Agent 基础设施 + "
        "项目级诊断研究设置"
    )
    print(f"  自动化测试：{'已运行' if arguments.run_tests else '未运行'}")
    print(
        "  Ray 集群冒烟："
        f"{'已验证' if arguments.ray_smoke else '未提供'}"
    )
    print("  DeepSeek API：未调用，费用为 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
