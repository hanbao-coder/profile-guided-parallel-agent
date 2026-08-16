#!/usr/bin/env python3
"""Run the pre-registered M9 verified boundary-delta treatment."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess

from run_m8_sklearn_trial import (
    ROOT,
    TASKS,
    _discover_wsl_paths,
    _project_context,
    _write_json,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--distro", default="Ubuntu")
    parser.add_argument("--python", type=Path, default=ROOT / ".venv" / "python.exe")
    parser.add_argument("--test-timeout", type=int, default=900)
    parser.add_argument("--benchmark-timeout", type=int, default=900)
    args = parser.parse_args()

    task = "29330"
    spec = TASKS[task]
    source_root = ROOT / "work" / "m8" / "sources" / "scikit-29330"
    evidence_path = ROOT / "docs" / "data" / "m9-boundary-delta-evidence.json"
    if not source_root.is_dir() or not evidence_path.is_file():
        raise SystemExit("missing pinned source or generated M9 evidence")
    host_python = args.python.resolve()
    wsl_python, wsl_sklearn = _discover_wsl_paths(args.distro, task)

    run_dir = (
        ROOT / "results" / "m9" / "boundary-delta" / task
        / "b4_verified_delta" / args.run_id
    )
    trial_root = (
        ROOT / "work" / "m9" / "trials" / task
        / "b4_verified_delta" / args.run_id
    )
    if run_dir.exists() or trial_root.exists():
        raise SystemExit("run-id already exists; evidence is never overwritten")

    context = _project_context(task, "b3_boundary")
    context["research_phase"] = "M9 verified relational boundary-delta experiment"
    context["experimental_group"] = "b4_verified_delta"
    context["boundary_delta_evidence"] = json.loads(
        evidence_path.read_text(encoding="utf-8")
    )
    context["method_difference"] = (
        "The Agent must declare a relational caller/Worker delta. A guarded tool "
        "applies the paired change atomically and rejects scheduler-policy drift."
    )
    context_path = run_dir / "registered-context.json"
    commands_path = run_dir / "registered-commands.json"
    _write_json(context_path, context)

    evaluator = ROOT / "scripts" / "evaluate_sklearn_candidate.py"
    shared = [
        str(host_python),
        str(evaluator),
        "--task", task,
        "--distro", args.distro,
        "--wsl-python", wsl_python,
        "--wsl-sklearn", wsl_sklearn,
        "--timeout", str(max(args.test_timeout, args.benchmark_timeout)),
    ]
    commands = {
        "test": [*shared, "--mode", "test"],
        "benchmark": [*shared, "--mode", "benchmark"],
        "final_benchmark": [*shared, "--mode", "benchmark", "--formal"],
    }
    _write_json(commands_path, commands)

    command = [
        str(host_python),
        str(ROOT / "scripts" / "run_repository_diagnostic.py"),
        "--project", str(spec["project"]),
        "--source-root", str(source_root),
        "--trial-root", str(trial_root),
        "--run-dir", str(run_dir),
        "--python", str(host_python),
        "--edit-mode", "anchored",
        "--contract-mode",
        "--performance-feedback-mode",
        "--boundary-evidence-mode",
        "--boundary-delta-mode",
        "--parallelism-mode", "optimize_existing",
        "--commands-json", str(commands_path),
        "--context-json", str(context_path),
        "--test-timeout", str(args.test_timeout),
        "--benchmark-timeout", str(args.benchmark_timeout),
    ]
    environment = os.environ.copy()
    environment.setdefault("PYTHONPATH", str(ROOT / "src"))
    completed = subprocess.run(command, cwd=ROOT, env=environment, check=False)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
