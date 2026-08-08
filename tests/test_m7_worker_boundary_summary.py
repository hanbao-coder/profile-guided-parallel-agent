from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "summarize_m7_worker_boundary",
    ROOT / "scripts" / "summarize_m7_worker_boundary.py",
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_candidate_statuses_count_boundary_feedback(tmp_path: Path) -> None:
    run = tmp_path / "radon" / "run-01"
    run.mkdir(parents=True)
    (run / "outcome.json").write_text(
        json.dumps(
            {
                "agent": {
                    "events": [
                        {
                            "observation": {
                                "candidate_evaluation": {
                                    "status": "worker_boundary_failure"
                                }
                            }
                        },
                        {
                            "observation": {
                                "candidate_evaluation": {
                                    "status": "integration_or_output_failure"
                                }
                            }
                        },
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    counts = MODULE._candidate_statuses(tmp_path)

    assert counts["worker_boundary_failure"] == 1
    assert counts["integration_or_output_failure"] == 1
