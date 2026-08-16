#!/usr/bin/env python3
"""Build M9 boundary-delta evidence from the pinned base source only."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from parallel_agent.boundary_delta import BoundaryDeltaFiles, discover_projection_boundary


ROOT = Path(__file__).resolve().parents[1]
FILES = BoundaryDeltaFiles(
    caller_path="sklearn/compose/_column_transformer.py",
    caller_function="_call_func_on_transformers",
    worker_path="sklearn/pipeline.py",
    worker_functions=("_transform_one", "_fit_transform_one"),
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source",
        type=Path,
        default=ROOT / "work" / "m8" / "sources" / "scikit-29330",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "docs" / "data" / "m9-boundary-delta-evidence.json",
    )
    args = parser.parse_args()
    evidence = discover_projection_boundary(args.source.resolve(), FILES)
    evidence["task"] = "scikit-learn__scikit-learn-29330"
    evidence["source_commit"] = "a490ab19667988de62024eb98acd61117f8c292a"
    evidence["provenance"] = (
        "Generated from the pinned base source by AST inspection. The public "
        "expert patch is not read by this script or included in the evidence."
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
