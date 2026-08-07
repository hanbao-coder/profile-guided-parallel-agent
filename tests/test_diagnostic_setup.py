from __future__ import annotations

from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def test_diagnostic_setup_verifier() -> None:
    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "verify_diagnostic_setup.py")],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "M0 项目级诊断研究设置验收完成" in completed.stdout
    assert "最终研究问题：保持开放" in completed.stdout
    assert "M2 已筛选真实项目：3 个" in completed.stdout
