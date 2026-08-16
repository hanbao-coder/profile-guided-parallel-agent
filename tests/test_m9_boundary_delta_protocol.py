from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_generated_evidence_is_source_derived_and_backend_agnostic() -> None:
    evidence = json.loads(
        (ROOT / "docs" / "data" / "m9-boundary-delta-evidence.json").read_text(
            encoding="utf-8"
        )
    )

    assert evidence["pattern"] == "hoist_projection_before_dispatch"
    assert evidence["caller"]["scheduler"]["keywords"] == {
        "n_jobs": "self.n_jobs"
    }
    assert evidence["caller"]["scheduler"]["must_remain_backend_agnostic"] is True
    assert {worker["function"] for worker in evidence["workers"]} == {
        "_transform_one",
        "_fit_transform_one",
    }
    assert "backend=\"threading\"" not in json.dumps(evidence)
