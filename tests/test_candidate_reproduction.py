from pathlib import Path

import pytest

from scripts.verify_candidate_reproduction import ROOT, _portable_evidence, _resolve_input


def test_resolve_input_uses_project_and_locked_environment(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    environment = {
        "site_packages": str(tmp_path / "site-packages"),
        "vulture_input_root": str(tmp_path / "site-packages" / "openai"),
    }

    assert _resolve_input(
        "project_test_data", source=source, input_environment=environment
    ) == (source / "tests" / "data").resolve()
    assert _resolve_input(
        "workload_openai", source=source, input_environment=environment
    ) == (tmp_path / "site-packages" / "openai").resolve()


def test_resolve_input_rejects_unknown_kind(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown input kind"):
        _resolve_input("mystery", source=tmp_path, input_environment={})


def test_portable_evidence_replaces_workspace_and_repository_paths(
    tmp_path: Path,
) -> None:
    value = {
        "workspace_file": str(tmp_path / "result.json"),
        "repository_file": str(ROOT / "configs" / "demo.yaml"),
        "escaped_json": str(tmp_path / "result.json").replace("\\", "\\\\"),
    }

    portable = _portable_evidence(value, workspace=tmp_path)

    assert portable["workspace_file"] == "{workspace}\\result.json"
    assert portable["repository_file"] == "{repository}\\configs\\demo.yaml"
    assert portable["escaped_json"] == "{workspace}\\\\result.json"
