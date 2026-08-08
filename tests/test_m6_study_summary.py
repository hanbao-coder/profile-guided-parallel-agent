from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "summarize_m6_study", ROOT / "scripts" / "summarize_m6_study.py"
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_group_counts_keep_safe_fallback_separate_from_success() -> None:
    summary = {
        "runs": [
            {"primary_outcome": "effective_parallelization"},
            {"primary_outcome": "safe_serial_fallback"},
            {"primary_outcome": "correctness_failure"},
            {"primary_outcome": "patch_application_failure"},
        ]
    }

    counts = MODULE._group_counts(summary)

    assert counts["有效并行化"] == 1
    assert counts["安全回退"] == 1
    assert counts["错误修改"] == 1
    assert counts["未形成方案"] == 1


def test_feedback_counts_use_every_candidate_evaluation(tmp_path: Path) -> None:
    run_dir = tmp_path / "mkdocs" / "run-01"
    run_dir.mkdir(parents=True)
    outcome = {
        "agent": {
            "events": [
                {
                    "observation": {
                        "candidate_evaluation": {"status": "correctness_failure"}
                    }
                },
                {
                    "observation": {
                        "candidate_evaluation": {
                            "status": "effective_end_to_end_gain"
                        }
                    }
                },
            ]
        }
    }
    (run_dir / "outcome.json").write_text(json.dumps(outcome), encoding="utf-8")

    counts = MODULE._full_feedback_counts(tmp_path)

    assert counts == {
        "correctness_failure": 1,
        "effective_end_to_end_gain": 1,
    }
