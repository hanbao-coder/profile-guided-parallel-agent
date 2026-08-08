#!/usr/bin/env python3
"""Rebuild and verify the Radon manual reference from a committed patch."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import time


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
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _compact_baseline(result: dict[str, object]) -> dict[str, object]:
    return {
        key: value
        for key, value in result.items()
        if key not in {"canonical_output", "input_root", "python"}
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--serial-source", type=Path, required=True)
    parser.add_argument("--project-python", type=Path, required=True)
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument(
        "--patch",
        type=Path,
        default=ROOT / "docs/data/radon-manual-reference.patch",
    )
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--summary-output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args()

    serial_source = args.serial_source.resolve()
    project_python = args.project_python.resolve()
    input_root = args.input_root.resolve()
    patch = args.patch.resolve()
    workspace = args.workspace.resolve()
    if workspace.exists():
        raise SystemExit(f"refusing to overwrite workspace: {workspace}")
    workspace.mkdir(parents=True)
    reference_source = workspace / "reference-source"
    shutil.copytree(serial_source, reference_source)

    apply_result = _run(
        ["git", "apply", "--check", str(patch)],
        cwd=reference_source,
        timeout=args.timeout,
    )
    if apply_result["returncode"] != 0:
        raise SystemExit(f"patch check failed: {apply_result['stderr']}")
    apply_result = _run(
        ["git", "apply", str(patch)], cwd=reference_source, timeout=args.timeout
    )
    if apply_result["returncode"] != 0:
        raise SystemExit(f"patch apply failed: {apply_result['stderr']}")

    preflight = _run(
        [
            str(project_python),
            "-c",
            "import json, radon; print(json.dumps({'module': radon.__file__}))",
        ],
        cwd=reference_source,
        timeout=args.timeout,
    )
    preflight_record = json.loads(preflight["stdout"])
    imported = Path(preflight_record["module"]).resolve()
    try:
        imported.relative_to(reference_source)
    except ValueError as exc:
        raise SystemExit(f"reference source was not imported: {imported}") from exc

    test = _run(
        [
            str(project_python),
            "-m",
            "pytest",
            "-q",
            "--basetemp",
            ".reference-pytest",
        ],
        cwd=reference_source,
        timeout=args.timeout,
    )
    (workspace / "project-test.json").write_text(
        json.dumps(test, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    def run_baseline(label: str, cwd: Path) -> tuple[dict[str, object], dict[str, object]]:
        output = workspace / f"{label}.json"
        command = [
            str(project_python),
            str(ROOT / "scripts/run_candidate_baseline.py"),
            "--project",
            "radon",
            "--input-root",
            str(input_root),
            "--output",
            str(output),
            "--warmups",
            "1",
            "--repeats",
            str(args.repeats),
            "--limit",
            "1800",
        ]
        execution = _run(command, cwd=cwd, timeout=args.timeout)
        if execution["returncode"] != 0 or not output.is_file():
            raise SystemExit(f"{label} baseline failed: {execution['stderr']}")
        return execution, json.loads(output.read_text(encoding="utf-8"))

    serial_execution, serial = run_baseline("b0-serial", serial_source)
    reference_execution, reference = run_baseline("b3-reference", reference_source)
    hashes_match = (
        serial.get("stable_output") is True
        and reference.get("stable_output") is True
        and set(serial["output_hashes"]) == set(reference["output_hashes"])
    )
    speedup = float(serial["median_seconds"]) / float(reference["median_seconds"])
    summary = {
        "schema_version": 1,
        "project": "radon",
        "comparison": "B0 serial vs B3 manual reference",
        "patch": {
            "path": patch.relative_to(ROOT).as_posix(),
            "sha256": _sha256(patch),
        },
        "source_import_preflight_passed": True,
        "project_tests_passed": test["returncode"] == 0,
        "project_test_stdout_tail": "\n".join(str(test["stdout"]).splitlines()[-10:]),
        "hashes_match": hashes_match,
        "speedup": speedup,
        "effective_at_1_05": (
            test["returncode"] == 0 and hashes_match and speedup >= 1.05
        ),
        "b0_serial": _compact_baseline(serial),
        "b3_reference": _compact_baseline(reference),
        "execution_seconds": {
            "project_tests": test["elapsed_seconds"],
            "b0_serial": serial_execution["elapsed_seconds"],
            "b3_reference": reference_execution["elapsed_seconds"],
        },
        "interpretation": (
            "The manual patch is a correctness reference. It is an effective "
            "performance upper bound only when effective_at_1_05 is true."
        ),
    }
    args.summary_output.parent.mkdir(parents=True, exist_ok=True)
    args.summary_output.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if test["returncode"] == 0 and hashes_match else 1


if __name__ == "__main__":
    raise SystemExit(main())
