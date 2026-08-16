from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "summarize_m8_reference_tasks",
    ROOT / "scripts" / "summarize_m8_reference_tasks.py",
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_reference_summary_rejects_neither_equal_outputs_nor_valid_tests(
    tmp_path: Path,
) -> None:
    base = {
        "task": "demo",
        "configuration": {"workers": 2},
        "environment": {"python": "3"},
        "stable_output": True,
        "output_hashes": ["same"],
        "median_seconds": 4.0,
        "iqr_seconds": 0.2,
    }
    expert = {**base, "median_seconds": 2.0, "iqr_seconds": 0.1}
    (tmp_path / "base.json").write_text(json.dumps(base), encoding="utf-8")
    (tmp_path / "expert.json").write_text(json.dumps(expert), encoding="utf-8")
    (tmp_path / "expert.patch").write_text("diff", encoding="utf-8")
    (tmp_path / "tests.xml").write_text(
        '<testsuites><testsuite tests="3" failures="0" errors="0" '
        'skipped="1" time="0.5" /></testsuites>',
        encoding="utf-8",
    )
    spec = {
        "task": "demo",
        "base_commit": "abc",
        "base": Path("base.json"),
        "expert": Path("expert.json"),
        "patch": Path("expert.patch"),
        "tests": Path("tests.xml"),
        "mechanism": "demo mechanism",
    }

    result = MODULE.summarize_task(spec, tmp_path)

    assert result["expert_speedup"] == 2.0
    assert result["output_equal"] is True
    assert result["targeted_tests"]["tests"] == 3
    assert result["targeted_tests"]["failures"] == 0
