from __future__ import annotations

import json
from pathlib import Path

from scripts.summarize_m8_formal_trials import build_summary


def _write_outcome(path: Path, *, patch: bool, speedup: float | None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "status": "completed",
                "agent": {"turns": 4, "edit_rounds": 1, "events": [], "traces": []},
                "candidate": {"test": {"returncode": 0}},
                "patch_nonempty": patch,
                "paired_formal_performance": {
                    "valid": speedup is not None,
                    "speedup": speedup,
                },
            }
        ),
        encoding="utf-8",
    )


def test_heldout_semantic_failure_overrides_apparent_speedup(tmp_path: Path) -> None:
    outcome = tmp_path / "29330" / "b2_location" / "formal-01" / "outcome.json"
    _write_outcome(outcome, patch=True, speedup=20.0)
    audit = outcome.parent / "heldout-semantic-audit.json"
    audit.write_text(json.dumps({"passed": False}), encoding="utf-8")

    summary = build_summary(tmp_path)
    row = summary["trials"][0]

    assert row["effective"] is False
    assert row["pipeline_effective_before_semantic_audit"] is True
    assert row["classification"] == "semantic_regression_after_metric_pass"


def test_safe_fallback_is_not_counted_as_effective(tmp_path: Path) -> None:
    outcome = tmp_path / "28064" / "b1_ordinary" / "formal-01" / "outcome.json"
    _write_outcome(outcome, patch=False, speedup=None)

    summary = build_summary(tmp_path)

    assert summary["effective_trials"] == 0
    assert summary["trials"][0]["effective"] is False
