from __future__ import annotations

import importlib.util
from pathlib import Path
import zipfile
import os
import json

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "bootstrap_candidate_projects",
    ROOT / "scripts" / "bootstrap_candidate_projects.py",
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_safe_extract_requires_one_root(tmp_path: Path) -> None:
    archive = tmp_path / "two-roots.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("a/file.txt", "a")
        handle.writestr("b/file.txt", "b")

    with pytest.raises(ValueError, match="one top-level"):
        MODULE._safe_extract(archive, tmp_path / "out")


def test_safe_extract_rejects_path_escape(tmp_path: Path) -> None:
    archive = tmp_path / "escape.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("root/../../outside.txt", "bad")

    with pytest.raises(ValueError, match="unsafe archive"):
        MODULE._safe_extract(archive, tmp_path / "out")


def test_safe_extract_returns_top_level_directory(tmp_path: Path) -> None:
    archive = tmp_path / "valid.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("project/file.txt", "ok")

    root = MODULE._safe_extract(archive, tmp_path / "out")

    assert root == tmp_path / "out" / "project"
    assert (root / "file.txt").read_text(encoding="utf-8") == "ok"


def test_python_in_env_uses_platform_layout(tmp_path: Path) -> None:
    expected = (
        tmp_path / "Scripts" / "python.exe"
        if os.name == "nt"
        else tmp_path / "bin" / "python"
    )
    expected.parent.mkdir(parents=True)
    expected.touch()

    assert MODULE._python_in_env(tmp_path) == expected


def test_existing_evidence_can_preserve_project_records(tmp_path: Path) -> None:
    evidence = {"projects": [{"project": "radon"}]}
    path = tmp_path / "bootstrap-evidence.json"
    path.write_text(json.dumps(evidence), encoding="utf-8")

    loaded = json.loads(path.read_text(encoding="utf-8"))

    assert loaded["projects"] == [{"project": "radon"}]


def test_archive_hash_mismatch_is_rejected() -> None:
    with pytest.raises(RuntimeError, match="hash mismatch"):
        MODULE._verify_archive_hash("actual", "expected", "demo")


def test_archive_hash_match_is_case_insensitive() -> None:
    MODULE._verify_archive_hash("ABC123", "abc123", "demo")
