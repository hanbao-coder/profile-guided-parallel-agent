#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from parallel_agent.ray_formal_summary import summarize_ray_formal_runs  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="汇总多次独立的 WSL/Linux Ray 正式实验。"
    )
    parser.add_argument("input_dir", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--expected-runs", type=int, default=3)
    parser.add_argument("--expected-workloads", type=int, default=8)
    args = parser.parse_args()
    result = summarize_ray_formal_runs(
        args.input_dir,
        args.output_dir,
        expected_runs=args.expected_runs,
        expected_workloads=args.expected_workloads,
    )
    print(json.dumps(result["overall"], indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
