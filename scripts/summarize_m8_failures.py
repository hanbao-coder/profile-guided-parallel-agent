#!/usr/bin/env python3
"""Verify and summarize the manually audited M8 candidate root causes."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path


def load_candidates(results_root: Path) -> dict[str, dict[str, object]]:
    candidates: dict[str, dict[str, object]] = {}
    for outcome_path in sorted(results_root.glob("*/*/outcome.json")):
        outcome = json.loads(outcome_path.read_text(encoding="utf-8"))
        project = str(outcome["project"])
        run = outcome_path.parent.name
        for event in outcome["agent"]["events"]:
            observation = event.get("observation", {})
            evaluation = observation.get("candidate_evaluation")
            if evaluation is None:
                continue
            edit_round = int(observation["edit_round"])
            candidate_id = f"{project}/{run}/edit-{edit_round:02d}"
            candidates[candidate_id] = {
                "raw_status": evaluation["status"],
                "speedup": evaluation.get("speedup"),
            }
    return candidates


def summarize(
    candidates: dict[str, dict[str, object]], labels_payload: dict[str, object]
) -> tuple[dict[str, object], list[dict[str, object]]]:
    labels = labels_payload["labels"]
    by_id = {str(item["id"]): item for item in labels}
    missing_labels = sorted(set(candidates) - set(by_id))
    stale_labels = sorted(set(by_id) - set(candidates))
    status_mismatches = [
        {
            "id": candidate_id,
            "measured": candidates[candidate_id]["raw_status"],
            "label_file": by_id[candidate_id]["raw_status"],
        }
        for candidate_id in sorted(set(candidates) & set(by_id))
        if candidates[candidate_id]["raw_status"]
        != by_id[candidate_id]["raw_status"]
    ]
    if missing_labels or stale_labels or status_mismatches:
        raise ValueError(
            json.dumps(
                {
                    "missing_labels": missing_labels,
                    "stale_labels": stale_labels,
                    "status_mismatches": status_mismatches,
                },
                ensure_ascii=False,
                indent=2,
            )
        )

    rows: list[dict[str, object]] = []
    for candidate_id in sorted(candidates):
        label = by_id[candidate_id]
        rows.append(
            {
                "id": candidate_id,
                "raw_status": candidates[candidate_id]["raw_status"],
                "root_cause": label["root_cause"],
                "worker_boundary_related": label["worker_boundary_related"],
                "speedup": candidates[candidate_id]["speedup"],
                "evidence": label["evidence"],
            }
        )

    root_counts = Counter(str(row["root_cause"]) for row in rows)
    failed_rows = [row for row in rows if row["root_cause"] != "effective"]
    boundary_failures = sum(
        bool(row["worker_boundary_related"]) for row in failed_rows
    )
    summary = {
        "schema_version": 1,
        "study": labels_payload["study"],
        "candidate_count": len(rows),
        "effective_count": root_counts["effective"],
        "non_effective_count": len(failed_rows),
        "worker_boundary_related_failures": boundary_failures,
        "worker_boundary_related_failure_fraction": (
            boundary_failures / len(failed_rows) if failed_rows else 0.0
        ),
        "root_cause_counts": dict(sorted(root_counts.items())),
        "interpretation_limit": (
            "这是对30个实际候选修改的人工主因编码，不代表所有Python项目；"
            "后续需要在公开大型项目任务上继续验证。"
        ),
    }
    return summary, rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--results-root", type=Path, default=Path("results/m5/corrected-final")
    )
    parser.add_argument(
        "--labels", type=Path, default=Path("docs/data/m8-manual-failure-labels.json")
    )
    parser.add_argument(
        "--output-json", type=Path, default=Path("docs/data/m8-failure-audit.json")
    )
    parser.add_argument(
        "--output-csv", type=Path, default=Path("docs/data/m8-failure-audit.csv")
    )
    args = parser.parse_args()

    candidates = load_candidates(args.results_root)
    labels_payload = json.loads(args.labels.read_text(encoding="utf-8"))
    summary, rows = summarize(candidates, labels_payload)

    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps({"summary": summary, "candidates": rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    with args.output_csv.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
