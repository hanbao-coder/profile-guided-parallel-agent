from scripts.summarize_repository_diagnostics import _primary_outcome


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
