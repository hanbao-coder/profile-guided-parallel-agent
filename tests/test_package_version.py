from __future__ import annotations

from pathlib import Path
import re
import subprocess
import sys

import parallel_agent


ROOT = Path(__file__).resolve().parents[1]


def _declared_version() -> str:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(
        r'(?ms)^\[project\].*?^version\s*=\s*"([^"]+)"',
        text,
    )
    assert match is not None, "pyproject.toml 缺少 [project].version"
    return match.group(1)


def test_package_and_documented_release_versions_are_aligned() -> None:
    declared = _declared_version()
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert parallel_agent.__version__ == declared
    assert f"`v{declared}-" in readme


def test_cli_reports_the_declared_package_version() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "parallel_agent.cli", "--version"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == f"parallel-agent {_declared_version()}"
