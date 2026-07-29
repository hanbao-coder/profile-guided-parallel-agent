from __future__ import annotations

from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def test_first_stage_release_verifier() -> None:
    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "verify_first_stage.py")],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "第一阶段科研交付包验收完成" in completed.stdout
    assert "DeepSeek API：未调用，费用为 0" in completed.stdout
