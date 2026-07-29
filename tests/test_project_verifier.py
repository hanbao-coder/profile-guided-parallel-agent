import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def test_project_verifier_runs_without_model_credentials() -> None:
    environment = os.environ.copy()
    environment.pop("DEEPSEEK_API_KEY", None)
    completed = subprocess.run(
        [sys.executable, "scripts/verify_project.py"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    assert "[通过] 完整项目验收完成" in completed.stdout
    assert "DeepSeek API：未调用，费用为 0" in completed.stdout
