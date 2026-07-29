from __future__ import annotations

from pathlib import Path

import pytest

from parallel_agent.artifacts import ParallelPlan
from parallel_agent.candidate_executor import execute_candidate
from parallel_agent.controlled_codegen import (
    GeneratedCodeSafetyError,
    canonical_parallel_impl,
    generate_controlled_candidate,
    validate_parallel_impl,
)


ROOT = Path(__file__).resolve().parents[1]


def _plan() -> ParallelPlan:
    return ParallelPlan(
        schema_version="1.0",
        source_path=str(
            (ROOT / "benchmarks/prime_count/workload.py").resolve()
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


def test_canonical_impl_is_safe_and_correct(tmp_path: Path) -> None:
    candidate, safety = generate_controlled_candidate(
        _plan(), canonical_parallel_impl(), tmp_path / "candidate.py"
    )
    serial = execute_candidate(
        candidate, mode="serial", size=2, seed=42, timeout_seconds=30
    )
    parallel = execute_candidate(
        candidate, mode="parallel", size=2, seed=42, timeout_seconds=30
    )
    assert safety["safe"] is True
    assert serial.error_type is None
    assert parallel.error_type is None
    assert serial.payload["result"] == parallel.payload["result"]


@pytest.mark.parametrize(
    "unsafe_code",
    [
        "import os\n" + canonical_parallel_impl(),
        canonical_parallel_impl().replace(
            "task_chunks = partition_items(items, chunks)",
            "open('leak.txt', 'w')\n    task_chunks = partition_items(items, chunks)",
        ),
        canonical_parallel_impl().replace(
            "task_chunks = partition_items(items, chunks)",
            "eval('1 + 1')\n    task_chunks = partition_items(items, chunks)",
        ),
    ],
)
def test_unsafe_generated_code_is_rejected(unsafe_code: str) -> None:
    with pytest.raises(GeneratedCodeSafetyError):
        validate_parallel_impl(unsafe_code)
