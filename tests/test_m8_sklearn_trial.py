from __future__ import annotations

from scripts.run_m8_sklearn_trial import TASKS, _project_context


def test_control_groups_do_not_receive_worker_boundary_card() -> None:
    ordinary = _project_context("28064", "b1_ordinary")
    location = _project_context("28064", "b2_location")

    assert "candidate_region" not in ordinary
    assert "worker_boundary_evidence_card" not in ordinary
    assert "candidate_region" in location
    assert location["candidate_source_ranges"][2]["start"] == 229
    assert location["candidate_source_ranges"][2]["end"] == 247
    assert "worker_boundary_evidence_card" not in location


def test_boundary_group_receives_measured_card_without_expert_patch() -> None:
    treatment = _project_context("29330", "b3_boundary")

    card = treatment["worker_boundary_evidence_card"]
    assert card["task"] == "scikit-learn__scikit-learn-29330"
    assert card["payload_evidence"]["full_to_projected_ratio"] > 30
    serialized = str(treatment).lower()
    assert "expert.patch" not in serialized
    assert "public expert patch" in serialized


def test_registered_tasks_are_pinned_to_commits_and_hashes() -> None:
    for spec in TASKS.values():
        assert len(str(spec["commit"])) == 40
        assert len(str(spec["baseline_output_hash"])) == 64
        assert len(str(spec["quick_baseline_output_hash"])) == 64


def test_quick_and_formal_hashes_are_distinct_for_scaled_dataframe_workload() -> None:
    context = _project_context("29330", "b1_ordinary")

    assert context["quick_baseline_output_hash"] != context["baseline_output_hash"]
