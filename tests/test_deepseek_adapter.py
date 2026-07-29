import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from parallel_agent.deepseek_adapter import (
    DeepSeekAdapter,
    DeepSeekConfigurationError,
)
from parallel_agent.loop_frontend import normalize_serial_loop


ROOT = Path(__file__).resolve().parents[1]


class FakeCompletions:
    def __init__(self, contents: list[str]) -> None:
        self.contents = iter(contents)
        self.calls = 0
        self.requests: list[dict] = []

    def create(self, **kwargs):
        self.requests.append(kwargs)
        self.calls += 1
        content = next(self.contents)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(message=SimpleNamespace(content=content))
            ],
            usage=SimpleNamespace(
                prompt_tokens=100,
                completion_tokens=20,
                total_tokens=120,
            ),
        )


def fake_client(contents: list[str]):
    completions = FakeCompletions(contents)
    return SimpleNamespace(
        chat=SimpleNamespace(completions=completions),
        fake_completions=completions,
    )


def test_missing_key_is_rejected() -> None:
    with pytest.raises(DeepSeekConfigurationError):
        DeepSeekAdapter(api_key="")


def test_invalid_json_is_retried() -> None:
    client = fake_client(
        [
            "not-json",
            json.dumps(
                {
                    "parallelizable": True,
                    "hazards": [],
                    "rationale": ["Independent workload contract."],
                }
            ),
        ]
    )
    adapter = DeepSeekAdapter(api_key="test-key", client=client)
    analysis = adapter.analyze(ROOT / "benchmarks/prime_count/workload.py")
    assert analysis.parallelizable
    assert client.fake_completions.calls == 2
    assert adapter.traces[0]["valid_json"] is False
    assert adapter.traces[1]["valid_json"] is True


def test_static_gate_overrides_unsafe_model_recommendation() -> None:
    client = fake_client(
        [
            json.dumps(
                {
                    "parallelizable": True,
                    "hazards": [],
                    "rationale": ["Model says parallel."],
                }
            )
        ]
    )
    adapter = DeepSeekAdapter(api_key="test-key", client=client)
    analysis = adapter.analyze(ROOT / "benchmarks/prefix_sum/serial.py")
    assert not analysis.parallelizable
    assert any("overrode" in reason for reason in analysis.rationale)


def test_empty_model_rationale_gets_a_safe_fallback() -> None:
    client = fake_client(
        [
            json.dumps(
                {
                    "parallelizable": True,
                    "hazards": [],
                    "rationale": [],
                }
            )
        ]
    )
    adapter = DeepSeekAdapter(api_key="test-key", client=client)
    analysis = adapter.analyze(ROOT / "benchmarks/prime_count/workload.py")
    assert analysis.parallelizable
    assert analysis.rationale


def test_contract_boundary_allows_loop_local_state() -> None:
    client = fake_client(
        [
            json.dumps(
                {
                    "parallelizable": True,
                    "hazards": [],
                    "rationale": ["Separate unit calls are independent."],
                }
            )
        ]
    )
    adapter = DeepSeekAdapter(api_key="test-key", client=client)
    analysis = adapter.analyze(ROOT / "benchmarks/tiny_tasks/workload.py")
    assert analysis.parallelizable
    assert any("unit contract" in reason for reason in analysis.rationale)


def test_stage_model_router_uses_pro_for_analysis_and_flash_for_plan() -> None:
    client = fake_client(
        [
            json.dumps(
                {
                    "parallelizable": True,
                    "hazards": [],
                    "rationale": ["Independent."],
                }
            ),
            json.dumps({"workers": 2, "chunks": 2, "reasons": ["Plan."]}),
        ]
    )
    adapter = DeepSeekAdapter(api_key="test-key", client=client)
    analysis = adapter.analyze(ROOT / "benchmarks/prime_count/workload.py")
    adapter.plan(analysis, workers=2, chunks=2)
    assert adapter.traces[0]["model"] == "deepseek-v4-pro"
    assert adapter.traces[1]["model"] == "deepseek-v4-flash"
    assert adapter.traces[0]["thinking_enabled"] is True
    assert adapter.traces[1]["thinking_enabled"] is False


def test_normalized_loop_analysis_uses_original_source(
    tmp_path: Path,
) -> None:
    wrapper = tmp_path / "normalized.py"
    normalize_serial_loop(
        ROOT / "examples/simple_serial_loop.py",
        output_path=wrapper,
    )
    client = fake_client(
        [
            json.dumps(
                {
                    "parallelizable": True,
                    "hazards": [],
                    "rationale": ["Original per-item function is pure."],
                }
            )
        ]
    )
    adapter = DeepSeekAdapter(api_key="test-key", client=client)
    analysis = adapter.analyze(wrapper)
    request = client.fake_completions.requests[0]
    user_content = request["messages"][1]["content"]
    assert analysis.parallelizable
    assert analysis.source_path == str(wrapper.resolve())
    assert analysis.loops == 1
    assert "verified_normalization" in user_content
    assert "def run_serial" in user_content


def test_performance_controller_can_choose_serial() -> None:
    client = fake_client(
        [
            json.dumps(
                {
                    "parallelizable": True,
                    "hazards": [],
                    "rationale": ["Independent."],
                }
            ),
            json.dumps({"workers": 2, "chunks": 2, "reasons": ["Plan."]}),
            json.dumps(
                {
                    "action": "serial",
                    "workers": 1,
                    "chunks": 1,
                    "reasons": ["Measured parallel runtime is slower."],
                }
            ),
        ]
    )
    adapter = DeepSeekAdapter(api_key="test-key", client=client)
    analysis = adapter.analyze(ROOT / "benchmarks/prime_count/workload.py")
    plan = adapter.plan(analysis, workers=2, chunks=2)
    optimized = adapter.optimize_performance(
        plan,
        {
            "end_to_end_speedup": 0.5,
            "minimum_speedup": 1.05,
        },
        attempt=1,
    )
    assert not optimized.parallelizable
    assert optimized.strategy == "serial"
    assert adapter.traces[-1]["model"] == "deepseek-v4-pro"


def test_code_generation_uses_pro_and_returns_code() -> None:
    generated_code = (
        "def partition_items(items, chunk_count):\n"
        "    return [list(items)]\n\n"
        "def execute_parallel(source_path, items, workers, chunks):\n"
        "    task_chunks = partition_items(items, chunks)\n"
        "    with ProcessPoolExecutor(max_workers=workers) as pool:\n"
        "        nested = list(pool.map(_safe_run_chunk, "
        "[source_path] * len(task_chunks), task_chunks))\n"
        "    return [item for group in nested for item in group], "
        "len(task_chunks)\n"
    )
    client = fake_client([json.dumps({"code": generated_code})])
    adapter = DeepSeekAdapter(api_key="test-key", client=client)
    from parallel_agent.artifacts import ParallelPlan

    plan = ParallelPlan(
        schema_version="1.0",
        source_path=str(
            ROOT / "benchmarks/prime_count/workload.py"
        ),
        parallelizable=True,
        backend="multiprocessing",
        strategy="map_reduce",
        workers=2,
        chunks=2,
        correctness_gate=True,
        fallback="serial",
        reasons=["test"],
    )
    result = adapter.generate_parallel_impl(plan)
    assert "def execute_parallel" in result
    assert adapter.traces[-1]["model"] == "deepseek-v4-pro"
    assert adapter.traces[-1]["thinking_enabled"] is False
