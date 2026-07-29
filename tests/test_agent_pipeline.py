import json
from pathlib import Path

import jsonschema

from parallel_agent.agent_pipeline import run_agent_pipeline


ROOT = Path(__file__).resolve().parents[1]


def test_agent_pipeline_generates_and_validates_candidate(tmp_path: Path) -> None:
    report = run_agent_pipeline(
        ROOT / "benchmarks/prime_count/workload.py",
        output_dir=tmp_path,
        size=2,
        seed=42,
        workers=2,
        chunks=2,
        timeout_seconds=30,
    )
    assert report["status"] == "accepted"
    assert report["correct"] is True
    assert (tmp_path / "candidate.py").exists()
    analysis = json.loads((tmp_path / "analysis.json").read_text(encoding="utf-8"))
    plan = json.loads(
        (tmp_path / "parallel_plan.json").read_text(encoding="utf-8")
    )
    assert analysis["contract_complete"] is True
    assert plan["strategy"] == "map_reduce"
    analysis_schema = json.loads(
        (ROOT / "schemas/analysis.schema.json").read_text(encoding="utf-8")
    )
    plan_schema = json.loads(
        (ROOT / "schemas/parallel_plan.schema.json").read_text(encoding="utf-8")
    )
    jsonschema.validate(analysis, analysis_schema)
    jsonschema.validate(plan, plan_schema)


def test_agent_pipeline_rejects_dependency_case(tmp_path: Path) -> None:
    report = run_agent_pipeline(
        ROOT / "benchmarks/prefix_sum/serial.py",
        output_dir=tmp_path,
        size=2,
        seed=42,
        workers=2,
        chunks=2,
    )
    assert report["status"] == "rejected"
    assert not (tmp_path / "candidate.py").exists()


def test_agent_pipeline_records_repair_feedback(tmp_path: Path) -> None:
    report = run_agent_pipeline(
        ROOT / "tests/fixtures/child_failure_workload.py",
        output_dir=tmp_path,
        size=2,
        seed=42,
        workers=2,
        chunks=2,
        timeout_seconds=30,
        max_repair_attempts=1,
    )
    assert report["status"] == "failed"
    assert report["repair_attempts_used"] == 1
    assert len(report["attempts"]) == 2
    assert (tmp_path / "repair_feedback_1.json").exists()
    assert (tmp_path / "candidate_attempt_2.py").exists()


def test_one_shot_group_does_not_repair(tmp_path: Path) -> None:
    report = run_agent_pipeline(
        ROOT / "tests/fixtures/child_failure_workload.py",
        output_dir=tmp_path,
        size=2,
        seed=42,
        workers=2,
        chunks=2,
        timeout_seconds=30,
        max_repair_attempts=2,
        feedback_mode="one_shot",
    )
    assert report["status"] == "failed"
    assert report["repair_attempts_used"] == 0
    assert len(report["attempts"]) == 1
    assert not (tmp_path / "repair_feedback_1.json").exists()


def test_performance_feedback_falls_back_for_tiny_tasks(
    tmp_path: Path,
) -> None:
    report = run_agent_pipeline(
        ROOT / "benchmarks/tiny_tasks/workload.py",
        output_dir=tmp_path,
        size=8,
        seed=42,
        workers=2,
        chunks=2,
        timeout_seconds=30,
        feedback_mode="performance",
        performance_repeats=1,
        minimum_speedup=1.05,
        max_performance_attempts=1,
    )
    assert report["status"] == "accepted"
    assert report["correct"] is True
    assert report["selected_mode"] == "serial"
    assert report["performance_gate_passed"] is False
    assert report["performance_attempts_used"] == 1
    assert report["final_plan"]["strategy"] == "serial"
    assert (tmp_path / "performance_feedback_1.json").exists()
