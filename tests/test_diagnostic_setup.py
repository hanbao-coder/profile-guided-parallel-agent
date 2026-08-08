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
    assert "M6 项目级研究设置验收完成" in completed.stdout
    assert "研究问题：已由诊断实验选定" in completed.stdout
    assert "M6 已验证真实项目：4 个" in completed.stdout
