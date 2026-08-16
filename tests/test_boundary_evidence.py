from __future__ import annotations

from parallel_agent.boundary_evidence import (
    _hash_outputs,
    probe_backends,
    probe_payload_plan,
    probe_serialization,
)

import numpy as np


def _square(value: int) -> int:
    return value * value


def test_serialization_reports_size_and_unpicklable_lambda() -> None:
    safe = probe_serialization({"items": [1, 2, 3]}, repeats=2)
    unsafe = probe_serialization(lambda value: value, repeats=1)

    assert safe["picklable"] is True
    assert safe["bytes"] > 0
    assert len(safe["serialization_timings_seconds"]) == 2
    assert unsafe["picklable"] is False
    assert unsafe["error_type"] in {"AttributeError", "PicklingError"}


def test_payload_plan_and_backend_probe_preserve_outputs() -> None:
    plan = probe_payload_plan([{"x": 1}, {"x": 2}], repeats=1)
    backends = probe_backends(
        _square,
        [1, 2, 3, 4],
        workers=2,
        repeats=1,
        include_process=False,
    )

    assert plan["picklable"] is True
    assert plan["payload_count"] == 2
    assert plan["total_bytes"] > 0
    assert backends["backends"]["serial"]["output_matches_serial"] is True
    assert backends["backends"]["thread"]["output_matches_serial"] is True


def test_output_hash_ignores_numpy_memory_layout() -> None:
    c_order = np.array([[1.0, 2.0], [3.0, 4.0]], order="C")
    f_order = np.array([[1.0, 2.0], [3.0, 4.0]], order="F")

    assert _hash_outputs([c_order]) == _hash_outputs([f_order])
