#!/usr/bin/env python3
"""Prepare pinned real-project sources and isolated Python environments."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.request
import zipfile

import yaml


ROOT = Path(__file__).resolve().parents[1]


def _safe_extract(archive: Path, destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=False)
    resolved_destination = destination.resolve()
    with zipfile.ZipFile(archive) as handle:
        members = handle.infolist()
        roots = {Path(member.filename).parts[0] for member in members if member.filename}
        if len(roots) != 1:
            raise ValueError(f"archive must have one top-level directory: {archive}")
        for member in members:
            target = (destination / member.filename).resolve()
            try:
                target.relative_to(resolved_destination)
            except ValueError as exc:
                raise ValueError(f"unsafe archive member: {member.filename}") from exc
        handle.extractall(destination)
    return destination / next(iter(roots))


def _download(url: str, target: Path) -> str:
    target.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "parallel-agent-repro/1"})
    with urllib.request.urlopen(request, timeout=120) as response, target.open("wb") as output:
        shutil.copyfileobj(response, output)
    return hashlib.sha256(target.read_bytes()).hexdigest()


def _verify_archive_hash(actual: str, expected: object, label: str) -> None:
    if expected is not None and actual.lower() != str(expected).lower():
        raise RuntimeError(
            f"archive hash mismatch for {label}: expected {expected}, got {actual}"
        )


def _python_in_env(environment: Path) -> Path:
    windows = environment / "Scripts" / "python.exe"
    return windows if windows.is_file() else environment / "bin" / "python"


def _run(command: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> None:
    completed = subprocess.run(command, cwd=cwd, env=env, check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"command failed ({completed.returncode}): {command}")


def _prepare_project(
    project_id: str,
    config: dict[str, object],
    *,
    workspace: Path,
    host_python: Path,
) -> dict[str, object]:
    archives = workspace / "archives"
    sources = workspace / "sources"
    environments = workspace / "envs"
    archive = archives / f"{project_id}.zip"
    source = sources / str(config["source_dir"])
    environment = environments / project_id
    if source.exists() or environment.exists():
        raise RuntimeError(
            f"refusing to overwrite existing project paths: {source}, {environment}"
        )

    archive_sha256 = _download(str(config["archive_url"]), archive)
    _verify_archive_hash(archive_sha256, config.get("archive_sha256"), project_id)
    extraction = sources / f".{project_id}-extract"
    extracted_root = _safe_extract(archive, extraction)
    source.parent.mkdir(parents=True, exist_ok=True)
    extracted_root.rename(source)
    extraction.rmdir()

    test_data_record = None
    test_data = config.get("test_data")
    if isinstance(test_data, dict):
        data_archive = archives / f"{project_id}-test-data.zip"
        data_sha256 = _download(str(test_data["archive_url"]), data_archive)
        _verify_archive_hash(
            data_sha256,
            test_data.get("archive_sha256"),
            f"{project_id} test data",
        )
        data_extraction = sources / f".{project_id}-data-extract"
        data_root = _safe_extract(data_archive, data_extraction)
        destination = source / str(test_data["destination"])
        if destination.exists():
            shutil.rmtree(destination)
        data_root.rename(destination)
        data_extraction.rmdir()
        (destination / ".test-data-ref").write_text(
            str(test_data.get("cache_label", test_data["commit"])) + "\n",
            encoding="utf-8",
        )
        test_data_record = {
            "commit": test_data["commit"],
            "archive_sha256": data_sha256,
            "cache_label": test_data.get("cache_label", test_data["commit"]),
        }

    _run([str(host_python), "-m", "venv", str(environment)], cwd=ROOT)
    project_python = _python_in_env(environment)
    requirements = (ROOT / str(config["requirements"])).resolve()
    _run(
        [str(project_python), "-m", "pip", "install", "-r", str(requirements)],
        cwd=ROOT,
    )
    install_env = os.environ.copy()
    version = config.get("editable_version")
    if version:
        install_env["SETUPTOOLS_SCM_PRETEND_VERSION"] = str(version)
    _run(
        [str(project_python), "-m", "pip", "install", "--no-deps", "-e", str(source)],
        cwd=ROOT,
        env=install_env,
    )
    import_subdir = str(config.get("import_subdir", "."))
    return {
        "project": project_id,
        "commit": config["commit"],
        "archive_sha256": archive_sha256,
        "source": str(source.resolve()),
        "environment": str(environment.resolve()),
        "python": str(project_python.resolve()),
        "import_root": str((source / import_subdir).resolve()),
        "test_data": test_data_record,
    }


def _prepare_input_environment(
    config: dict[str, object],
    *,
    workspace: Path,
    host_python: Path,
    resume: bool = False,
) -> dict[str, object]:
    """Create the pinned environment that supplies Radon/Vulture inputs."""
    environment = workspace / "envs" / "workload-input"
    if environment.exists() and not resume:
        raise RuntimeError(f"refusing to overwrite input environment: {environment}")
    if not environment.exists():
        _run([str(host_python), "-m", "venv", str(environment)], cwd=ROOT)
    input_python = _python_in_env(environment)
    requirements = (ROOT / str(config["requirements"])).resolve()
    _run(
        [str(input_python), "-m", "pip", "install", "-r", str(requirements)],
        cwd=ROOT,
    )
    completed = subprocess.run(
        [str(input_python), "-m", "pip", "freeze", "--all"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    freeze = completed.stdout.strip().splitlines()
    site_packages = next(
        path for path in input_python.parents if path.name in {"Scripts", "bin"}
    ).parent / ("Lib/site-packages" if os.name == "nt" else "lib")
    if os.name != "nt":
        candidates = sorted(site_packages.glob("python*/site-packages"))
        if len(candidates) != 1:
            raise RuntimeError("could not resolve input environment site-packages")
        site_packages = candidates[0]
    return {
        "environment": str(environment.resolve()),
        "python": str(input_python.resolve()),
        "requirements": str(requirements),
        "freeze": freeze,
        "site_packages": str(site_packages.resolve()),
        "radon_input_root": str(site_packages.resolve()),
        "vulture_input_root": str((site_packages / "openai").resolve()),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--manifest",
        type=Path,
        default=ROOT / "configs/candidate_bootstrap.yaml",
    )
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--project", action="append", dest="projects")
    parser.add_argument(
        "--input-environment",
        action="store_true",
        help="also create the pinned workload-input environment",
    )
    parser.add_argument(
        "--input-environment-only",
        action="store_true",
        help="create only the pinned workload-input environment",
    )
    parser.add_argument(
        "--resume-input-environment",
        action="store_true",
        help="resume package installation in an existing input environment",
    )
    parser.add_argument("--host-python", type=Path, default=Path(sys.executable))
    args = parser.parse_args()

    manifest = yaml.safe_load(args.manifest.read_text(encoding="utf-8"))
    configured = manifest["projects"]
    selected = [] if args.input_environment_only else (args.projects or list(configured))
    unknown = sorted(set(selected) - set(configured))
    if unknown:
        raise SystemExit(f"unknown projects: {', '.join(unknown)}")
    workspace = args.workspace.resolve()
    if workspace == ROOT.resolve() or ROOT.resolve() in workspace.parents:
        pass
    elif workspace == Path(workspace.anchor):
        raise SystemExit("workspace cannot be a filesystem root")
    workspace.mkdir(parents=True, exist_ok=True)
    records = []
    for project_id in selected:
        print(f"[prepare] {project_id}", flush=True)
        records.append(
            _prepare_project(
                project_id,
                configured[project_id],
                workspace=workspace,
                host_python=args.host_python.resolve(),
            )
        )
    input_environment = None
    if args.input_environment or args.input_environment_only:
        print("[prepare] workload-input", flush=True)
        input_environment = _prepare_input_environment(
            manifest["workload_input_environment"],
            workspace=workspace,
            host_python=args.host_python.resolve(),
            resume=args.resume_input_environment,
        )
    evidence_path = workspace / "bootstrap-evidence.json"
    previous_evidence = None
    if evidence_path.is_file():
        previous_evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    project_records = records
    if args.input_environment_only and previous_evidence:
        project_records = previous_evidence.get("projects", [])
    evidence = {
        "schema_version": 1,
        "manifest": str(args.manifest.resolve()),
        "host_python": str(args.host_python.resolve()),
        "projects": project_records,
        "input_environment": input_environment
        if input_environment is not None
        else (previous_evidence or {}).get("input_environment"),
    }
    evidence_path.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
