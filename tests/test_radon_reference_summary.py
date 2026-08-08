from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "summarize_radon_reference_recheck.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("radon_reference_summary", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_validate_summary_rejects_missing_fields() -> None:
    module = _load_module()
    with pytest.raises(ValueError, match="missing fields"):
        module.validate_summary({"speedup": 1.0})


def test_render_creates_figure(tmp_path: Path) -> None:
    module = _load_module()
    output = tmp_path / "figure.png"
    module.render(
        {
            "b0_serial": {"median_seconds": 12.7},
            "b3_reference": {"median_seconds": 12.72},
            "speedup": 0.9984,
            "hashes_match": True,
            "effective_at_1_05": False,
        },
        output,
    )
    assert output.is_file()
    assert output.stat().st_size > 1_000
