from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_ci_verifies_release_on_linux_python_312() -> None:
    workflow = (
        ROOT / ".github" / "workflows" / "project-verification.yml"
    ).read_text(encoding="utf-8")
    assert "runs-on: ubuntu-latest" in workflow
    assert 'python-version: "3.12"' in workflow
    assert 'python -m pip install -e ".[dev]"' in workflow
    assert "python scripts/verify_project.py --run-tests" in workflow
    assert "python scripts/verify_project.py" in workflow
    assert "--ray-smoke work/ray-smoke.json" in workflow
    assert "--backend ray" in workflow
    assert "--modes serial naive optimized" in workflow
    assert "actions/checkout@v5" in workflow
    assert "actions/setup-python@v6" in workflow
    assert "actions/upload-artifact@v6" in workflow
    assert "project-verification-${{ github.workflow }}" in workflow
    assert "work/ray-smoke.json" in workflow
    assert "work/ray-smoke.log" in workflow
    assert "GITHUB_STEP_SUMMARY" in workflow
    assert "::error title=Ray smoke failure::" in workflow
    assert "DEEPSEEK_API_KEY" not in workflow
