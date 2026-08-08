from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.audit_research_evidence import (
    AUDITED_RESEARCH_ARTIFACTS,
    REQUIRED_FILES,
    _audit_run,
    audit_research_artifacts,
)


def _write_minimal_run(root: Path) -> None:
    for relative in REQUIRED_FILES:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix == ".json":
            payload = {"project": "demo", "status": "complete"}
            path.write_text(json.dumps(payload), encoding="utf-8")
        elif path.suffix == ".jsonl":
            path.write_text(json.dumps({"event": "done"}) + "\n", encoding="utf-8")
        else:
            path.write_text("diff --git a/a.py b/a.py\n", encoding="utf-8")


def test_audit_run_requires_complete_raw_evidence(tmp_path: Path) -> None:
    run = tmp_path / "results" / "run-01"
    _write_minimal_run(run)

    record = _audit_run(run, repository=tmp_path)

    assert record["project"] == "demo"
    assert record["file_count"] == len(REQUIRED_FILES)
    assert all(len(item["sha256"]) == 64 for item in record["files"])


def test_audit_run_rejects_missing_prompt(tmp_path: Path) -> None:
    run = tmp_path / "results" / "run-01"
    _write_minimal_run(run)
    (run / "agent" / "prompt.json").unlink()

    with pytest.raises(FileNotFoundError, match="prompt.json"):
        _audit_run(run, repository=tmp_path)


def test_additional_artifacts_are_hashed(tmp_path: Path) -> None:
    for relative in AUDITED_RESEARCH_ARTIFACTS:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}" if path.suffix == ".json" else "evidence", encoding="utf-8")

    records = audit_research_artifacts(tmp_path)

    assert len(records) == len(AUDITED_RESEARCH_ARTIFACTS)
    assert all(len(record["sha256"]) == 64 for record in records)
