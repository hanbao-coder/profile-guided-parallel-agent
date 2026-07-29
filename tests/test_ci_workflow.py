from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_ci_verifies_release_on_linux_python_312() -> None:
    workflow = (
        ROOT / ".github" / "workflows" / "first-stage-verification.yml"
    ).read_text(encoding="utf-8")
    assert "runs-on: ubuntu-latest" in workflow
    assert 'python-version: "3.12"' in workflow
    assert 'python -m pip install -e ".[dev]"' in workflow
    assert "python scripts/verify_first_stage.py --run-tests" in workflow
    assert "DEEPSEEK_API_KEY" not in workflow
