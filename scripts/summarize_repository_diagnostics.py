#!/usr/bin/env python3
"""Summarize completed repository diagnostic runs without model judgment."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]


def _benchmark_summary(result: dict[str, Any]) -> dict[str, Any]:
    stdout = str(result.get("stdout", "")).strip()
    if not stdout:
        return {}
    try:
        parsed = json.loads(stdout)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _primary_outcome(
    outcome: dict[str, Any],
    *,
    serial_median: float,
) -> tuple[str, float | None]:
    agent = outcome.get("agent", {})
    events = agent.get("events", [])
    candidate = outcome.get("candidate", {})
    test_result = candidate.get("test", {})
    benchmark_result = candidate.get("benchmark", {})
    benchmark = _benchmark_summary(benchmark_result)
    candidate_median = benchmark.get("median_seconds")
    speedup = (
        serial_median / float(candidate_median)
        if serial_median > 0 and candidate_median
        else None
    )
    edit_attempts = [
        event
        for event in events
        if event.get("action", {}).get("action") == "apply_edits"
    ]
    if not outcome.get("patch_nonempty"):
        if edit_attempts:
            return "patch_application_failure", speedup
        return "analysis_nonconvergence", speedup
    if test_result.get("timed_out") or test_result.get("returncode") != 0:
        return "correctness_failure", speedup
    if (
        benchmark_result.get("timed_out")
        or benchmark_result.get("returncode") != 0
        or (
            benchmark_result.get("output_matches_baseline") is False
            and benchmark_result.get("actual_output_hash") is not None
        )
    ):
        return "integration_or_output_failure", speedup
    if speedup is None:
        return "performance_measurement_failure", speedup
    if speedup >= 1.05:
        return "effective_parallelization", speedup
    if speedup < (1 / 1.05):
        return "end_to_end_performance_regression", speedup
    return "no_meaningful_end_to_end_gain", speedup


def _load_serial_medians(config_path: Path) -> dict[str, float]:
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    return {
        str(project["id"]): float(project["workload"]["baseline_median_seconds"])
        for project in config["projects"]
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--results-root",
        type=Path,
        default=ROOT / "results" / "diagnostic",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=ROOT / "configs" / "project_diagnostic.yaml",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=ROOT / "results" / "diagnostic-summary.json",
    )
    parser.add_argument(
        "--output-csv",
        type=Path,
        default=ROOT / "results" / "diagnostic-summary.csv",
    )
    args = parser.parse_args()

    medians = _load_serial_medians(args.config)
    rows: list[dict[str, Any]] = []
    excluded: list[dict[str, str]] = []
    if args.results_root.exists():
        for run_dir in sorted(path for path in args.results_root.glob("*/*") if path.is_dir()):
            exclusion_path = run_dir / "exclusion.json"
            if exclusion_path.is_file():
                exclusion = json.loads(exclusion_path.read_text(encoding="utf-8"))
                excluded.append(
                    {
                        "path": run_dir.relative_to(args.results_root).as_posix(),
                        "status": str(exclusion.get("status", "excluded")),
                        "reason": str(exclusion.get("reason", "")),
                    }
                )
                continue
            outcome_path = run_dir / "outcome.json"
            if not outcome_path.is_file():
                continue
            outcome = json.loads(outcome_path.read_text(encoding="utf-8"))
            project = str(outcome["project"])
            category, speedup = _primary_outcome(
                outcome,
                serial_median=medians[project],
            )
            agent = outcome.get("agent", {})
            traces = agent.get("traces", [])
            rows.append(
                {
                    "project": project,
                    "run": run_dir.name,
                    "primary_outcome": category,
                    "speedup": speedup,
                    "turns": agent.get("turns"),
                    "edit_rounds": agent.get("edit_rounds"),
                    "patch_nonempty": outcome.get("patch_nonempty"),
                    "model_calls": len(traces),
                    "model_tokens": sum(
                        int(trace.get("total_tokens") or 0) for trace in traces
                    ),
                }
            )

    summary = {
        "schema_version": 1,
        "included_runs": len(rows),
        "excluded_runs": len(excluded),
        "outcome_counts": dict(Counter(row["primary_outcome"] for row in rows)),
        "runs": rows,
        "excluded": excluded,
    }
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    args.output_csv.parent.mkdir(parents=True, exist_ok=True)
    with args.output_csv.open("w", encoding="utf-8-sig", newline="") as handle:
        fieldnames = [
            "project",
            "run",
            "primary_outcome",
            "speedup",
            "turns",
            "edit_rounds",
            "patch_nonempty",
            "model_calls",
            "model_tokens",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
