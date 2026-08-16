#!/usr/bin/env python3
"""Summarize frozen M8 formal trials without treating fallback as success."""

from __future__ import annotations

import argparse
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
GROUPS = ("b1_ordinary", "b2_location", "b3_boundary")
TASKS = ("28064", "29330")


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _candidate_statuses(outcome: dict[str, Any]) -> list[str]:
    statuses: list[str] = []
    for event in outcome.get("agent", {}).get("events", []):
        observation = event.get("observation", {})
        if not isinstance(observation, dict):
            continue
        evaluation = observation.get("candidate_evaluation", {})
        if isinstance(evaluation, dict) and evaluation.get("status"):
            statuses.append(str(evaluation["status"]))
    return statuses


def summarize_trial(outcome_path: Path) -> dict[str, Any]:
    outcome = _read(outcome_path)
    trial_dir = outcome_path.parent
    task = outcome_path.parts[-4]
    group = outcome_path.parts[-3]
    run_id = outcome_path.parts[-2]
    excluded = bool(outcome.get("excluded_from_research_metrics"))
    agent = outcome.get("agent", {})
    candidate = outcome.get("candidate", {})
    paired = outcome.get("paired_formal_performance", {})
    statuses = _candidate_statuses(outcome)
    contract_path = trial_dir / "agent" / "parallelization-contract.json"
    contract = _read(contract_path) if contract_path.is_file() else {}
    audit_path = trial_dir / "heldout-semantic-audit.json"
    audit = _read(audit_path) if audit_path.is_file() else {}

    tests_pass = candidate.get("test", {}).get("returncode") == 0
    speedup = paired.get("speedup")
    pipeline_effective = bool(
        outcome.get("patch_nonempty")
        and tests_pass
        and paired.get("valid")
        and isinstance(speedup, (int, float))
        and speedup >= 1.05
    )
    semantic_pass = audit.get("passed") is not False
    effective = bool(pipeline_effective and semantic_pass and not excluded)

    edit_rounds = int(agent.get("edit_rounds", 0) or 0)
    if excluded:
        classification = "infrastructure_excluded"
    elif effective:
        classification = "effective_patch"
    elif pipeline_effective and not semantic_pass:
        classification = "semantic_regression_after_metric_pass"
    elif edit_rounds == 0:
        classification = "no_candidate_edit"
    elif statuses:
        last = statuses[-1]
        if last == "patch_quality_failure":
            classification = "structural_failure_then_fallback"
        elif last == "correctness_failure":
            classification = "correctness_failure_then_fallback"
        elif last in {"insufficient_end_to_end_gain", "performance_regression"}:
            classification = "performance_failure_then_fallback"
        elif last == "non_parallel_candidate":
            classification = "nonparallel_candidate_then_fallback"
        else:
            classification = f"{last}_then_fallback"
    else:
        classification = "edited_then_fallback"

    traces = agent.get("traces", [])
    return {
        "task": task,
        "group": group,
        "run_id": run_id,
        "status": outcome.get("status"),
        "excluded": excluded,
        "classification": classification,
        "effective": effective,
        "pipeline_effective_before_semantic_audit": pipeline_effective,
        "heldout_semantic_pass": semantic_pass if audit else None,
        "turns": agent.get("turns"),
        "edit_rounds": edit_rounds,
        "contract_accepted": contract_path.is_file(),
        "contract_backend": contract.get("backend"),
        "candidate_statuses": statuses,
        "patch_nonempty": bool(outcome.get("patch_nonempty")),
        "tests_pass": tests_pass,
        "paired_speedup": speedup,
        "prompt_tokens": sum(int(item.get("prompt_tokens", 0) or 0) for item in traces),
        "completion_tokens": sum(
            int(item.get("completion_tokens", 0) or 0) for item in traces
        ),
        "outcome_sha256": _sha256(outcome_path),
        "semantic_audit_sha256": _sha256(audit_path) if audit_path.is_file() else None,
    }


def build_summary(root: Path) -> dict[str, Any]:
    trials: list[dict[str, Any]] = []
    for task in TASKS:
        for group in GROUPS:
            pattern = root / task / group
            for outcome_path in sorted(pattern.glob("formal-*/outcome.json")):
                trials.append(summarize_trial(outcome_path))

    included = [row for row in trials if not row["excluded"]]
    grouped: dict[str, Any] = {}
    for task in TASKS:
        grouped[task] = {}
        for group in GROUPS:
            rows = [
                row
                for row in included
                if row["task"] == task and row["group"] == group
            ]
            evaluation_counts: Counter[str] = Counter()
            for row in rows:
                evaluation_counts.update(row["candidate_statuses"])
            grouped[task][group] = {
                "included_trials": len(rows),
                "effective_trials": sum(bool(row["effective"]) for row in rows),
                "effective_rate": (
                    sum(bool(row["effective"]) for row in rows) / len(rows)
                    if rows
                    else None
                ),
                "contracts_accepted": sum(bool(row["contract_accepted"]) for row in rows),
                "trials_with_no_edit": sum(row["edit_rounds"] == 0 for row in rows),
                "evaluation_status_counts": dict(sorted(evaluation_counts.items())),
                "classifications": dict(
                    sorted(Counter(row["classification"] for row in rows).items())
                ),
            }

    overall_classifications = Counter(row["classification"] for row in included)
    return {
        "schema_version": 1,
        "research_phase": "M8 frozen worker-boundary evidence experiment",
        "success_rule": (
            "Non-empty patch, project checks pass, paired formal speedup >= 1.05, "
            "and any held-out semantic audit passes. Safe fallback is not success."
        ),
        "included_trials": len(included),
        "excluded_trials": len(trials) - len(included),
        "effective_trials": sum(bool(row["effective"]) for row in included),
        "overall_classifications": dict(sorted(overall_classifications.items())),
        "by_task_and_group": grouped,
        "trials": trials,
    }


def write_csv(path: Path, trials: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "task",
        "group",
        "run_id",
        "excluded",
        "classification",
        "effective",
        "turns",
        "edit_rounds",
        "contract_accepted",
        "contract_backend",
        "patch_nonempty",
        "tests_pass",
        "paired_speedup",
        "heldout_semantic_pass",
        "prompt_tokens",
        "completion_tokens",
        "outcome_sha256",
        "semantic_audit_sha256",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for trial in trials:
            writer.writerow({field: trial.get(field) for field in fields})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        type=Path,
        default=ROOT / "results" / "m8" / "agent-experiments",
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        default=ROOT / "docs" / "data" / "m8-formal-summary.json",
    )
    parser.add_argument(
        "--csv-output",
        type=Path,
        default=ROOT / "docs" / "data" / "m8-formal-summary.csv",
    )
    args = parser.parse_args()
    summary = build_summary(args.input)
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    write_csv(args.csv_output, summary["trials"])
    print(json.dumps({key: summary[key] for key in (
        "included_trials", "excluded_trials", "effective_trials", "overall_classifications"
    )}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
