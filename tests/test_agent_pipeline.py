import json
from pathlib import Path

import jsonschema
import pytest

from parallel_agent.agent_pipeline import (
    _bind_execution_backend,
    run_agent_pipeline,
)
from parallel_agent.agent_adapter import OfflineHeuristicAdapter
from parallel_agent.controlled_codegen import canonical_parallel_impl


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
        performance_repeats=1,
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


def test_template_candidate_exposes_ray_execution_backend(tmp_path: Path) -> None:
    report = run_agent_pipeline(
        ROOT / "benchmarks/prime_count/workload.py",
        output_dir=tmp_path,
        size=2,
        seed=42,
        workers=2,
        chunks=2,
        timeout_seconds=30,
        performance_repeats=1,
    )
    candidate = (tmp_path / "candidate.py").read_text(encoding="utf-8")
    assert report["execution_backend"] == "multiprocessing"
    assert 'choices=["multiprocessing", "ray"]' in candidate
    assert "remote_run_chunk = ray.remote(run_chunk)" in candidate


def test_ray_execution_rejects_controlled_llm_candidate(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="ProcessPool sandbox"):
        run_agent_pipeline(
            ROOT / "benchmarks/prime_count/workload.py",
            output_dir=tmp_path,
            size=2,
            seed=42,
            workers=2,
            chunks=2,
            generation_mode="llm",
            execution_backend="ray",
        )


def test_execution_backend_is_bound_into_structured_plan() -> None:
    adapter = OfflineHeuristicAdapter()
    analysis = adapter.analyze(ROOT / "benchmarks/prime_count/workload.py")
    plan = adapter.plan(analysis, workers=2, chunks=2)
    bound = _bind_execution_backend(plan, "ray")
    assert bound.backend == "ray"
    assert bound.workers == plan.workers
    assert bound.chunks == plan.chunks
    schema = json.loads(
        (ROOT / "schemas/parallel_plan.schema.json").read_text(encoding="utf-8")
    )
    jsonschema.validate(bound.to_dict(), schema)


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
        performance_repeats=1,
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
        performance_repeats=2,
    )
    assert report["status"] == "failed"
    assert report["repair_attempts_used"] == 0
    assert len(report["attempts"]) == 1
    assert len(report["attempts"][0]["serial_runs"]) == 2
    assert len(report["attempts"][0]["parallel_runs"]) == 2
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
    performance = report["attempts"][0]["performance"]
    assert "conservative_speedup" in performance
    assert "serial_total_q1_seconds" in performance


def test_controlled_llm_generation_mode_runs(tmp_path: Path) -> None:
    report = run_agent_pipeline(
        ROOT / "benchmarks/prime_count/workload.py",
        output_dir=tmp_path,
        size=2,
        seed=42,
        workers=2,
        chunks=2,
        timeout_seconds=30,
        feedback_mode="correctness",
        performance_repeats=1,
        generation_mode="llm",
    )
    assert report["status"] == "accepted"
    assert report["correct"] is True
    assert report["generation_mode"] == "llm"
    assert report["code_repair_attempts_used"] == 0
    assert (tmp_path / "parallel_impl_attempt_1.py").exists()
    assert (tmp_path / "code_safety_attempt_1.json").exists()


class _UnsafeThenRepairAdapter(OfflineHeuristicAdapter):
    def generate_parallel_impl(self, plan):
        del plan
        return "import os\n" + canonical_parallel_impl()

    def repair_parallel_impl(
        self, plan, code, feedback, *, attempt
    ):
        del plan, code, feedback, attempt
        return canonical_parallel_impl()


def test_unsafe_llm_code_enters_code_repair_loop(tmp_path: Path) -> None:
    report = run_agent_pipeline(
        ROOT / "benchmarks/prime_count/workload.py",
        output_dir=tmp_path,
        size=2,
        seed=42,
        workers=2,
        chunks=2,
        timeout_seconds=30,
        feedback_mode="correctness",
        performance_repeats=1,
        generation_mode="llm",
        max_code_repair_attempts=1,
        adapter=_UnsafeThenRepairAdapter(),
    )
    assert report["status"] == "accepted"
    assert report["code_repair_attempts_used"] == 1
    assert report["attempts"][0]["generation_error"][
        "error_type"
    ] == "generated_code_safety_error"
    assert (tmp_path / "code_feedback_1.json").exists()


def test_pipeline_requires_both_shared_artifact_overrides(
    tmp_path: Path,
) -> None:
    source = ROOT / "benchmarks/prime_count/workload.py"
    adapter = OfflineHeuristicAdapter()
    analysis = adapter.analyze(source)

    with pytest.raises(
        ValueError,
        match="analysis_override and plan_override",
    ):
        run_agent_pipeline(
            source,
            output_dir=tmp_path / "invalid_override",
            size=2,
            seed=42,
            workers=2,
            chunks=2,
            analysis_override=analysis,
        )


class _WrongTaskCountThenRepairAdapter(OfflineHeuristicAdapter):
    def generate_parallel_impl(self, plan):
        del plan
        return canonical_parallel_impl().replace(
            "return flattened, len(task_chunks)",
            "return flattened, len(flattened)",
        )

    def repair_parallel_impl(
        self, plan, code, feedback, *, attempt
    ):
        del plan, code, attempt
        assert feedback["outputs_equal"] is True
        assert feedback["task_count_valid"] is False
        return canonical_parallel_impl()


def test_invalid_task_count_enters_code_repair_loop(
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
        feedback_mode="correctness",
        performance_repeats=1,
        generation_mode="llm",
        max_code_repair_attempts=1,
        adapter=_WrongTaskCountThenRepairAdapter(),
    )

    assert report["status"] == "accepted"
    assert report["code_repair_attempts_used"] == 1
    assert report["attempts"][0]["result_correct"] is True
    assert report["attempts"][0]["task_count_valid"] is False
    assert report["attempts"][1]["task_count_valid"] is True


def test_configuration_search_controller_can_select_serial(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_search(*args, **kwargs):
        del args, kwargs
        return {
            "status": "completed",
            "selection": {
                "selected_label": "serial",
                "selected_configuration": None,
            },
            "holdout": {
                "selected_speedup": 1.0,
                "fixed_speedup": 0.5,
                "selected_over_fixed": 2.0,
            },
            "cache": {"enabled": False, "hit": False, "key": "test"},
        }

    monkeypatch.setattr(
        "parallel_agent.agent_pipeline.run_configuration_search",
        fake_search,
    )
    report = run_agent_pipeline(
        ROOT / "benchmarks/tiny_tasks/workload.py",
        output_dir=tmp_path,
        size=8,
        seed=42,
        workers=2,
        chunks=2,
        feedback_mode="performance",
        performance_controller="configuration_search",
        search_warmups=0,
    )

    assert report["status"] == "accepted"
    assert report["selected_mode"] == "serial"
    assert report["performance_controller"] == "configuration_search"
    assert report["configuration_search"]["selected_label"] == "serial"
    assert not (tmp_path / "candidate.py").exists()


def test_configuration_search_controller_deploys_selected_plan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_search(*args, **kwargs):
        del args, kwargs
        return {
            "status": "completed",
            "selection": {
                "selected_label": "w1_c1",
                "selected_configuration": {"workers": 1, "chunks": 1},
            },
            "holdout": {
                "selected_speedup": 1.1,
                "fixed_speedup": 0.9,
                "selected_over_fixed": 1.2,
            },
            "cache": {"enabled": True, "hit": True, "key": "test"},
        }

    monkeypatch.setattr(
        "parallel_agent.agent_pipeline.run_configuration_search",
        fake_search,
    )
    report = run_agent_pipeline(
        ROOT / "benchmarks/prime_count/workload.py",
        output_dir=tmp_path,
        size=2,
        seed=42,
        workers=2,
        chunks=2,
        timeout_seconds=30,
        feedback_mode="performance",
        performance_repeats=1,
        performance_controller="configuration_search",
        search_warmups=0,
    )

    assert report["status"] == "accepted"
    assert report["selected_mode"] == "parallel"
    assert report["final_plan"]["workers"] == 1
    assert report["final_plan"]["chunks"] == 1
    assert report["configuration_search"]["cache"]["hit"] is True
