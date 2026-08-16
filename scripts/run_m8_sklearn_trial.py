#!/usr/bin/env python3
"""Run one preregistered M8 Agent trial on a public scikit-learn task.

Machine-specific WSL paths are discovered at runtime and are written only to
the raw run directory.  The committed task description and evidence card do
not expose the public expert patch to the Agent.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


TASKS: dict[str, dict[str, object]] = {
    "28064": {
        "project": "scikit-learn__scikit-learn-28064",
        "commit": "619a1c1028335e9fa7abd4d7fb6477200a4bce67",
        "baseline_output_hash": (
            "1e8d52a1bec6856a040371e8dcca3c9c1bb53908bf29dce0c699fea1fa6bed28"
        ),
        "problem_statement": (
            "Improve the end-to-end fitting performance of the histogram "
            "gradient boosting bin mapper on a fixed dense numerical input."
        ),
        "public_entrypoint": (
            "sklearn.ensemble._hist_gradient_boosting.binning._BinMapper.fit"
        ),
        "registered_workload": (
            "Fit _BinMapper(max_bins=256) on a deterministic 200000 by 20 "
            "float64 matrix with four available parallel workers."
        ),
        "candidate_region": (
            "_BinMapper.fit: the per-feature threshold computation in "
            "sklearn/ensemble/_hist_gradient_boosting/binning.py"
        ),
        "candidate_source_ranges": [
            {
                "path": "sklearn/ensemble/_hist_gradient_boosting/binning.py",
                "start": 11,
                "end": 11,
                "purpose": "existing numpy import; extend only this line if a module-level import is needed",
            },
            {
                "path": "sklearn/ensemble/_hist_gradient_boosting/binning.py",
                "start": 22,
                "end": 22,
                "purpose": "blank line after all imports; use only if a module-level worker helper is needed",
            },
            {
                "path": "sklearn/ensemble/_hist_gradient_boosting/binning.py",
                "start": 229,
                "end": 247,
                "purpose": "result initialization, serial per-feature loop and final result assignment",
            },
        ],
        "interface_constraints": [
            "Respect the existing self.n_threads setting instead of hard-coding a worker count.",
            "Keep categorical-feature handling and feature order unchanged.",
        ],
        "evidence_card": "docs/data/m8-boundary-card-scikit-28064.json",
        "correctness_requirements": [
            "All registered scikit-learn binning tests must pass.",
            "The list of thresholds and derived bin counts must match the base revision.",
            "Continuous and categorical feature behavior and feature order must be preserved.",
        ],
    },
    "29330": {
        "project": "scikit-learn__scikit-learn-29330",
        "commit": "a490ab19667988de62024eb98acd61117f8c292a",
        "baseline_output_hash": (
            "a065e626e39a24327ed5ccb8c0cac7b73627398330fb3642d39472eba6d2908d"
        ),
        "problem_statement": (
            "Improve the end-to-end performance of a ColumnTransformer that "
            "already dispatches many object-dtype column transformations in parallel."
        ),
        "public_entrypoint": "sklearn.compose.ColumnTransformer.fit_transform",
        "registered_workload": (
            "Fit and transform a deterministic 100000-row, 40-column object "
            "DataFrame with 40 one-column transformers and n_jobs=2."
        ),
        "candidate_region": (
            "ColumnTransformer._call_func_on_transformers: construction of "
            "the delayed fit_transform/transform tasks"
        ),
        "candidate_source_ranges": [
            {
                "path": "sklearn/compose/_column_transformer.py",
                "start": 18,
                "end": 24,
                "purpose": "indexing-related imports",
            },
            {
                "path": "sklearn/compose/_column_transformer.py",
                "start": 858,
                "end": 885,
                "purpose": "construction and execution of delayed transformer jobs",
            },
            {
                "path": "sklearn/pipeline.py",
                "start": 1258,
                "end": 1325,
                "purpose": "private worker helper inputs and column selection",
            },
        ],
        "interface_constraints": [
            "Retain ColumnTransformer n_jobs behavior and transformer result order.",
            "Preserve all public estimator methods and fitted-state behavior.",
        ],
        "evidence_card": "docs/data/m8-boundary-card-scikit-29330.json",
        "correctness_requirements": [
            "All registered ColumnTransformer and Pipeline tests must pass.",
            "The transformed array must match the base revision exactly.",
            "Transformer order, column selection semantics and fitted state must be preserved.",
        ],
    },
}


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _run_wsl(distro: str, argv: list[str], *, timeout: int = 60) -> str:
    completed = subprocess.run(
        ["wsl.exe", "-d", distro, "--", *argv],
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if completed.returncode != 0:
        raise SystemExit(
            "WSL environment discovery failed:\n"
            + completed.stdout
            + completed.stderr
        )
    return completed.stdout.strip().replace("\x00", "")


def _discover_wsl_paths(distro: str, task: str) -> tuple[str, str]:
    home = _run_wsl(distro, ["sh", "-lc", "printf %s \"$HOME\""])
    environment = f"{home}/hustagent-research/scikit-{task}/.venv"
    python = f"{environment}/bin/python"
    sklearn = _run_wsl(
        distro,
        [
            python,
            "-c",
            "import sklearn; print(sklearn.__path__[0])",
        ],
    ).splitlines()[-1]
    return python, sklearn


def _project_context(task: str, group: str) -> dict[str, object]:
    spec = TASKS[task]
    context: dict[str, object] = {
        "research_phase": "M8 controlled worker-boundary experiment",
        "experimental_group": group,
        "task_kind": (
            "serial_to_parallel"
            if task == "28064"
            else "existing_parallel_boundary_optimization"
        ),
        "repository": "https://github.com/scikit-learn/scikit-learn",
        "commit": spec["commit"],
        "problem_statement": spec["problem_statement"],
        "public_entrypoint": spec["public_entrypoint"],
        "registered_workload": spec["registered_workload"],
        "baseline_output_hash": spec["baseline_output_hash"],
        "correctness_requirements": spec["correctness_requirements"],
        "interface_constraints": spec["interface_constraints"],
        "constraints": [
            "Do not edit the registered workload or test adapter.",
            "Do not hard-code the fixed input or its expected output.",
            "Use only dependencies already present in scikit-learn.",
            "The Agent cannot inspect the public expert patch.",
            "A result counts only after project tests, output comparison and paired timing.",
            "Model requests use a 120-second timeout with at most one SDK retry.",
        ],
        "api_execution_policy": {
            "timeout_seconds": 120,
            "sdk_max_retries": 1,
            "infrastructure_failures_excluded": True,
        },
    }
    if group in {"b2_location", "b3_boundary"}:
        context["candidate_region"] = spec["candidate_region"]
        context["candidate_source_ranges"] = spec["candidate_source_ranges"]
        context["location_evidence_limit"] = (
            "This identifies where the registered work is performed but does "
            "not prescribe a Worker unit, backend or data boundary."
        )
    if group == "b3_boundary":
        card_path = ROOT / str(spec["evidence_card"])
        context["worker_boundary_evidence_card"] = json.loads(
            card_path.read_text(encoding="utf-8")
        )
    return context


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", choices=tuple(TASKS), required=True)
    parser.add_argument(
        "--group",
        choices=("b1_ordinary", "b2_location", "b3_boundary"),
        required=True,
    )
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--distro", default="Ubuntu")
    parser.add_argument("--python", type=Path, default=ROOT / ".venv" / "python.exe")
    parser.add_argument("--test-timeout", type=int, default=900)
    parser.add_argument("--benchmark-timeout", type=int, default=900)
    args = parser.parse_args()

    spec = TASKS[args.task]
    source_root = ROOT / "work" / "m8" / "sources" / f"scikit-{args.task}"
    if not source_root.is_dir():
        raise SystemExit(f"missing pinned source tree: {source_root}")
    host_python = args.python.resolve()
    if not host_python.is_file():
        raise SystemExit(f"missing host project Python: {host_python}")
    wsl_python, wsl_sklearn = _discover_wsl_paths(args.distro, args.task)

    run_dir = (
        ROOT / "results" / "m8" / "agent-experiments"
        / args.task / args.group / args.run_id
    )
    trial_root = (
        ROOT / "work" / "m8" / "trials"
        / args.task / args.group / args.run_id
    )
    if run_dir.exists() or trial_root.exists():
        raise SystemExit(
            "run-id already exists; use a new run-id so evidence is not overwritten"
        )

    context_path = run_dir / "registered-context.json"
    commands_path = run_dir / "registered-commands.json"
    _write_json(context_path, _project_context(args.task, args.group))

    evaluator = ROOT / "scripts" / "evaluate_sklearn_candidate.py"
    shared = [
        str(host_python),
        str(evaluator),
        "--task", args.task,
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

    runner = ROOT / "scripts" / "run_repository_diagnostic.py"
    command = [
        str(host_python),
        str(runner),
        "--project", str(spec["project"]),
        "--source-root", str(source_root),
        "--trial-root", str(trial_root),
        "--run-dir", str(run_dir),
        "--python", str(host_python),
        "--edit-mode", "anchored",
        "--contract-mode",
        "--performance-feedback-mode",
        "--commands-json", str(commands_path),
        "--context-json", str(context_path),
        "--test-timeout", str(args.test_timeout),
        "--benchmark-timeout", str(args.benchmark_timeout),
    ]
    if args.group == "b3_boundary":
        command.append("--boundary-evidence-mode")
    if args.task == "29330":
        command.extend(["--parallelism-mode", "optimize_existing"])
    environment = os.environ.copy()
    environment.setdefault("PYTHONPATH", str(ROOT / "src"))
    completed = subprocess.run(command, cwd=ROOT, env=environment, check=False)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
