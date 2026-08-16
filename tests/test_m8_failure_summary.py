from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "summarize_m8_failures", ROOT / "scripts" / "summarize_m8_failures.py"
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_summary_checks_labels_and_counts_boundary_failures() -> None:
    candidates = {
        "demo/run-01/edit-01": {"raw_status": "ok", "speedup": 2.0},
        "demo/run-01/edit-02": {"raw_status": "bad", "speedup": None},
    }
    labels = {
        "study": "demo",
        "labels": [
            {
                "id": "demo/run-01/edit-01",
                "raw_status": "ok",
                "root_cause": "effective",
                "worker_boundary_related": False,
                "evidence": "passed",
            },
            {
                "id": "demo/run-01/edit-02",
                "raw_status": "bad",
                "root_cause": "unserializable_worker_input",
                "worker_boundary_related": True,
                "evidence": "pickle error",
            },
        ],
    }

    summary, rows = MODULE.summarize(candidates, labels)

    assert len(rows) == 2
    assert summary["candidate_count"] == 2
    assert summary["non_effective_count"] == 1
    assert summary["worker_boundary_related_failures"] == 1
    assert summary["worker_boundary_related_failure_fraction"] == 1.0
