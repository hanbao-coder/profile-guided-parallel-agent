#!/usr/bin/env python3
"""Re-run pinned project tests and path-independent serial baselines."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import time

import yaml


ROOT = Path(__file__).resolve().parents[1]


def _run(command: list[str], *, cwd: Path, timeout: int) -> dict[str, object]:
    started = time.perf_counter()
    completed = subprocess.run(
        command,
        cwd=cwd,
        env={
            **os.environ,
            "OMP_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
            "PYTHONHASHSEED": "0",
        },
        capture_output=True,
        text=True,
        errors="replace",
        timeout=timeout,
        check=False,
    )
    return {
        "argv": command,
        "returncode": completed.returncode,
        "elapsed_seconds": time.perf_counter() - started,
        "stdout_tail": "\n".join(completed.stdout.splitlines()[-30:]),
        "stderr_tail": "\n".join(completed.stderr.splitlines()[-30:]),
    }


def _resolve_input(
    input_kind: str,
    *,
    source: Path,
    input_environment: dict[str, object],
) -> Path:
    known = {
        "workload_site_packages",
        "workload_openai",
        "project_test_data",
        "project_source",
    }
    if input_kind not in known:
        raise ValueError(f"unknown input kind: {input_kind}")
    choices = {
        "workload_site_packages": Path(str(input_environment["site_packages"])),
        "workload_openai": Path(str(input_environment["vulture_input_root"])),
        "project_test_data": source / "tests" / "data",
        "project_source": source,
    }
    return choices[input_kind].resolve()


def _portable_evidence(value: object, *, workspace: Path) -> object:
    """Replace local absolute prefixes before committing compact evidence."""
    if isinstance(value, dict):
        return {
            key: _portable_evidence(item, workspace=workspace)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_portable_evidence(item, workspace=workspace) for item in value]
    if isinstance(value, str):
        replacements = (
            (str(workspace.resolve()), "{workspace}"),
            (str(ROOT.resolve()), "{repository}"),
        )
        portable = value
        for absolute, label in replacements:
            portable = portable.replace(absolute, label)
            portable = portable.replace(absolute.replace("\\", "\\\\"), label)
        return portable
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument(
        "--config",
        type=Path,
        default=ROOT / "configs" / "candidate_reproduction.yaml",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--skip-tests", action="store_true")
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args()

    workspace = args.workspace.resolve()
    bootstrap = json.loads(
        (workspace / "bootstrap-evidence.json").read_text(encoding="utf-8")
    )
    config = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    records_by_project = {item["project"]: item for item in bootstrap["projects"]}
    input_environment = bootstrap.get("input_environment")
    if not input_environment:
        raise SystemExit("bootstrap evidence has no workload input environment")

    audit_records = []
    baseline_dir = workspace / "reproduction-baselines"
    baseline_dir.mkdir(parents=True, exist_ok=True)
    all_passed = True
    for project, project_config in config["projects"].items():
        print(f"[verify] {project}", flush=True)
        prepared = records_by_project[project]
        source = Path(prepared["source"])
        python = Path(prepared["python"])
        project_record: dict[str, object] = {"project": project}
        if not args.skip_tests:
            test = _run(
                [str(python), *map(str, project_config["test_args"])],
                cwd=source,
                timeout=args.timeout,
            )
            test["passed"] = test["returncode"] == 0
            project_record["test"] = test
            all_passed = all_passed and bool(test["passed"])

        input_root = _resolve_input(
            project_config["input"],
            source=source,
            input_environment=input_environment,
        )
        baseline_output = baseline_dir / f"{project}.json"
        command = [
            str(python),
            str(ROOT / "scripts" / "run_candidate_baseline.py"),
            "--project",
            project,
            "--input-root",
            str(input_root),
            "--output",
            str(baseline_output),
            "--warmups",
            str(args.warmups),
            "--repeats",
            str(args.repeats),
        ]
        if project_config.get("limit") is not None:
            command.extend(["--limit", str(project_config["limit"])])
        run = _run(command, cwd=source, timeout=args.timeout)
        result = (
            json.loads(baseline_output.read_text(encoding="utf-8"))
            if run["returncode"] == 0 and baseline_output.is_file()
            else {}
        )
        hashes = result.get("output_hashes", [])
        expected_hash = str(project_config["expected_output_hash"])
        hash_matches = bool(hashes) and set(hashes) == {expected_hash}
        baseline_passed = (
            run["returncode"] == 0
            and result.get("stable_output") is True
            and result.get("output_schema_version")
            == config["output_schema_version"]
            and hash_matches
        )
        compact_run = {
            key: value
            for key, value in run.items()
            if key != "stdout_tail" and (key != "stderr_tail" or value)
        }
        project_record["baseline"] = {
            **compact_run,
            "passed": baseline_passed,
            "stable_output": result.get("stable_output"),
            "median_seconds": result.get("median_seconds"),
            "output_items": result.get("output_items"),
            "actual_output_hash": hashes[0] if hashes else None,
            "expected_output_hash": expected_hash,
            "hash_matches": hash_matches,
        }
        all_passed = all_passed and baseline_passed
        audit_records.append(project_record)

    evidence = {
        "schema_version": 1,
        "bootstrap_evidence": str((workspace / "bootstrap-evidence.json").resolve()),
        "configuration": str(args.config.resolve()),
        "all_passed": all_passed,
        "projects": audit_records,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    portable_evidence = _portable_evidence(evidence, workspace=workspace)
    args.output.write_text(
        json.dumps(portable_evidence, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(portable_evidence, ensure_ascii=False, indent=2))
    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
