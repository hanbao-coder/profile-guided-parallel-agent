#!/usr/bin/env python3
"""Summarize M9 formal trials and keep the reduced repetition count explicit."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from statistics import median
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def summarize_trial(outcome_path: Path) -> dict[str, Any]:
    outcome = _read(outcome_path)
    run_dir = outcome_path.parent
    delta_path = run_dir / "agent" / "boundary-delta.json"
    patch_path = run_dir / "agent" / "patch.diff"
    delta = _read(delta_path) if delta_path.is_file() else {}
    candidate = outcome.get("candidate", {})
    test = candidate.get("test", {})
    test_stdout = str(test.get("stdout", ""))
    paired = outcome.get("paired_formal_performance", {})
    speedup = paired.get("speedup")
    invariant_status = delta.get("invariant_report", {}).get("status")
    tests_pass = test.get("returncode") == 0
    backend_semantics_pass = '"respects_external_loky_backend": true' in test_stdout
    effective = bool(
        outcome.get("patch_nonempty")
        and tests_pass
        and backend_semantics_pass
        and invariant_status == "passed"
        and paired.get("valid")
        and isinstance(speedup, (int, float))
        and speedup >= 1.05
    )
    traces = outcome.get("agent", {}).get("traces", [])
    return {
        "run_id": run_dir.name,
        "status": outcome.get("status"),
        "effective": effective,
        "tests_pass": tests_pass,
        "project_test_summary": (
            "350 passed, 4 skipped"
            if "350 passed, 4 skipped" in test_stdout
            else None
        ),
        "backend_semantics_pass": backend_semantics_pass,
        "boundary_invariants_pass": invariant_status == "passed",
        "patch_nonempty": bool(outcome.get("patch_nonempty")),
        "paired_performance_valid": bool(paired.get("valid")),
        "baseline_seconds": paired.get("paired_baseline_median_seconds"),
        "candidate_seconds": paired.get("candidate_median_seconds"),
        "speedup": speedup,
        "turns": outcome.get("agent", {}).get("turns"),
        "edit_rounds": outcome.get("agent", {}).get("edit_rounds"),
        "prompt_tokens": sum(int(row.get("prompt_tokens", 0) or 0) for row in traces),
        "completion_tokens": sum(
            int(row.get("completion_tokens", 0) or 0) for row in traces
        ),
        "outcome_sha256": _sha256(outcome_path),
        "delta_sha256": _sha256(delta_path) if delta_path.is_file() else None,
        "patch_sha256": _sha256(patch_path) if patch_path.is_file() else None,
    }


def build_summary(root: Path, m8_summary_path: Path) -> dict[str, Any]:
    formal_paths = sorted(root.glob("formal-*/outcome.json"))
    trials = [summarize_trial(path) for path in formal_paths]
    effective = [row for row in trials if row["effective"]]
    speedups = [float(row["speedup"]) for row in effective]
    m8 = _read(m8_summary_path) if m8_summary_path.is_file() else {}
    m8_task = m8.get("by_task_and_group", {}).get("29330", {})
    return {
        "schema_version": 1,
        "research_phase": "M9 verified relational boundary-delta experiment",
        "task": "scikit-learn__scikit-learn-29330",
        "success_rule": (
            "A non-empty patch must satisfy boundary invariants, pass project checks, "
            "preserve caller-selected loky backend semantics, preserve output, and "
            "achieve paired formal speedup >= 1.05."
        ),
        "protocol": {
            "pilot_runs_excluded": len(list(root.glob("pilot-*/outcome.json"))),
            "formal_runs_preregistered": 3,
            "formal_runs_completed": len(trials),
            "deviation": (
                "The third formal repetition was cancelled after two independent, "
                "consistent runs to limit model and compute cost. Results are treated "
                "as replicated engineering evidence, not a statistical significance claim."
            ),
        },
        "formal_trials": len(trials),
        "effective_trials": len(effective),
        "effective_rate": len(effective) / len(trials) if trials else None,
        "speedup_median": median(speedups) if speedups else None,
        "speedup_min": min(speedups) if speedups else None,
        "speedup_max": max(speedups) if speedups else None,
        "all_project_tests_pass": bool(trials) and all(row["tests_pass"] for row in trials),
        "all_backend_semantics_pass": bool(trials)
        and all(row["backend_semantics_pass"] for row in trials),
        "comparison_with_m8_freeform_agent": {
            group: {
                "included_trials": values.get("included_trials"),
                "effective_trials": values.get("effective_trials"),
                "effective_rate": values.get("effective_rate"),
            }
            for group, values in m8_task.items()
        },
        "trials": trials,
    }


def write_csv(path: Path, trials: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(trials[0]) if trials else ["run_id"]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(trials)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        type=Path,
        default=ROOT / "results" / "m9" / "boundary-delta" / "29330" / "b4_verified_delta",
    )
    parser.add_argument(
        "--m8-summary",
        type=Path,
        default=ROOT / "docs" / "data" / "m8-formal-summary.json",
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        default=ROOT / "docs" / "data" / "m9-formal-summary.json",
    )
    parser.add_argument(
        "--csv-output",
        type=Path,
        default=ROOT / "docs" / "data" / "m9-formal-summary.csv",
    )
    args = parser.parse_args()
    summary = build_summary(args.input, args.m8_summary)
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    write_csv(args.csv_output, summary["trials"])
    print(
        json.dumps(
            {
                "formal_trials": summary["formal_trials"],
                "effective_trials": summary["effective_trials"],
                "speedup_median": summary["speedup_median"],
                "all_backend_semantics_pass": summary["all_backend_semantics_pass"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
