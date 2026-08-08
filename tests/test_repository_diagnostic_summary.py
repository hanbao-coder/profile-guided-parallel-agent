from scripts.summarize_repository_diagnostics import (
    _feedback_summary,
    _primary_outcome,
)


def test_primary_outcome_ignores_events_without_an_action():
    outcome = {
        "agent": {
            "events": [
                {"turn": 1, "action": None},
                {"turn": 2, "model": "deepseek-v4-pro"},
            ]
        },
        "candidate": {
            "test": {"returncode": 0},
            "benchmark": {"returncode": 0},
        },
        "patch_nonempty": False,
    }

    category, speedup = _primary_outcome(outcome, serial_median=10.0)

    assert category == "analysis_nonconvergence"
    assert speedup is None


def test_primary_outcome_detects_failed_edit_attempt():
    outcome = {
        "agent": {
            "events": [
                {
                    "turn": 1,
                    "action": {"action": "apply_edits", "edits": []},
                }
            ]
        },
        "candidate": {
            "test": {"returncode": 0},
            "benchmark": {"returncode": 0},
        },
        "patch_nonempty": False,
    }

    category, speedup = _primary_outcome(outcome, serial_median=10.0)

    assert category == "patch_application_failure"
    assert speedup is None


def test_primary_outcome_distinguishes_safe_fallback_from_edit_failure():
    outcome = {
        "agent": {
            "events": [
                {"turn": 1, "action": {"action": "apply_edits"}},
                {"turn": 2, "action": {"action": "automatic_safe_fallback"}},
            ]
        },
        "candidate": {
            "test": {"returncode": 0},
            "benchmark": {"returncode": 0, "skipped": True},
        },
        "patch_nonempty": False,
    }

    category, speedup = _primary_outcome(outcome, serial_median=10.0)

    assert category == "safe_serial_fallback"
    assert speedup is None


def test_feedback_summary_keeps_accepted_quick_measurement():
    events = [
        {
            "observation": {
                "candidate_evaluation": {
                    "status": "end_to_end_performance_regression",
                    "speedup": 0.8,
                }
            }
        },
        {
            "observation": {
                "candidate_evaluation": {
                    "status": "effective_end_to_end_gain",
                    "speedup": 1.2,
                }
            }
        },
    ]

    summary = _feedback_summary(events)

    assert summary == {"feedback_rounds": 2, "accepted_quick_speedup": 1.2}
