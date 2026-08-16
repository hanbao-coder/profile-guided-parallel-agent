#!/usr/bin/env python3
"""Build compact, checked evidence for reproduced public reference patches."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path


TASKS = (
    {
        "task": "scikit-learn__scikit-learn-28064",
        "base_commit": "619a1c1028335e9fa7abd4d7fb6477200a4bce67",
        "base": Path("work/m8/scikit-28064/base.json"),
        "expert": Path("work/m8/scikit-28064/expert.json"),
        "patch": Path("work/m8/scikit-28064/expert.patch"),
        "tests": Path("work/m8/scikit-28064/expert-tests.xml"),
        "mechanism": "按特征并行计算分箱阈值，使用线程执行能够释放GIL的底层数值计算。",
    },
    {
        "task": "scikit-learn__scikit-learn-29330",
        "base_commit": "a490ab19667988de62024eb98acd61117f8c292a",
        "base": Path("work/m8/scikit-29330/base-fixed-environment.json"),
        "expert": Path("work/m8/scikit-29330/expert.json"),
        "patch": Path("work/m8/scikit-29330/expert.patch"),
        "tests": Path("work/m8/scikit-29330/expert-tests.xml"),
        "mechanism": "在提交并行任务前先切出所需列，避免把完整DataFrame反复送入Worker。",
    },
)


def _load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _test_summary(path: Path) -> dict[str, int | float]:
    root = ET.parse(path).getroot()
    suite = root.find("testsuite") if root.tag == "testsuites" else root
    if suite is None:
        raise ValueError(f"No testsuite in {path}")
    return {
        "tests": int(suite.attrib["tests"]),
        "failures": int(suite.attrib["failures"]),
        "errors": int(suite.attrib["errors"]),
        "skipped": int(suite.attrib["skipped"]),
        "seconds": float(suite.attrib["time"]),
    }


def summarize_task(spec: dict[str, object], root: Path = Path(".")) -> dict[str, object]:
    base_path = root / spec["base"]
    expert_path = root / spec["expert"]
    patch_path = root / spec["patch"]
    tests_path = root / spec["tests"]
    base = _load_json(base_path)
    expert = _load_json(expert_path)

    if base["task"] != spec["task"] or expert["task"] != spec["task"]:
        raise ValueError(f"Task mismatch for {spec['task']}")
    if base["configuration"] != expert["configuration"]:
        raise ValueError(f"Configuration mismatch for {spec['task']}")
    if base["environment"] != expert["environment"]:
        raise ValueError(f"Environment mismatch for {spec['task']}")
    if not base["stable_output"] or not expert["stable_output"]:
        raise ValueError(f"Unstable output for {spec['task']}")
    if set(base["output_hashes"]) != set(expert["output_hashes"]):
        raise ValueError(f"Output mismatch for {spec['task']}")

    tests = _test_summary(tests_path)
    if tests["failures"] or tests["errors"]:
        raise ValueError(f"Expert patch tests failed for {spec['task']}")

    base_median = float(base["median_seconds"])
    expert_median = float(expert["median_seconds"])
    result: dict[str, object] = {
        "task": spec["task"],
        "base_commit": spec["base_commit"],
        "mechanism": spec["mechanism"],
        "result_kind": "public_expert_reference_reproduction",
        "base_median_seconds": base_median,
        "expert_median_seconds": expert_median,
        "expert_speedup": base_median / expert_median,
        "base_iqr_seconds": base["iqr_seconds"],
        "expert_iqr_seconds": expert["iqr_seconds"],
        "output_hash": base["output_hashes"][0],
        "output_equal": True,
        "expert_patch_sha256": hashlib.sha256(patch_path.read_bytes()).hexdigest(),
        "targeted_tests": tests,
        "configuration": base["configuration"],
        "environment": base["environment"],
    }
    if "boundary_serialization_proxy" in base:
        result["boundary_serialization_proxy"] = base[
            "boundary_serialization_proxy"
        ]
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument(
        "--output-json",
        type=Path,
        default=Path("docs/data/m8-reference-reproductions.json"),
    )
    parser.add_argument(
        "--output-csv",
        type=Path,
        default=Path("docs/data/m8-reference-reproductions.csv"),
    )
    args = parser.parse_args()

    tasks = [summarize_task(spec, args.root) for spec in TASKS]
    payload = {
        "schema_version": 1,
        "source_benchmark": "SWE-efficiency public task records",
        "claim_boundary": (
            "这些数字复现的是公开任务中的人工专家补丁，只用于证明研究问题真实存在，"
            "不能当作本项目Agent已经达到的结果。"
        ),
        "tasks": tasks,
    }
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    rows = [
        {
            "task": task["task"],
            "base_median_seconds": task["base_median_seconds"],
            "expert_median_seconds": task["expert_median_seconds"],
            "expert_speedup": task["expert_speedup"],
            "output_equal": task["output_equal"],
            "tests": task["targeted_tests"]["tests"],
            "failures": task["targeted_tests"]["failures"],
        }
        for task in tasks
    ]
    with args.output_csv.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
