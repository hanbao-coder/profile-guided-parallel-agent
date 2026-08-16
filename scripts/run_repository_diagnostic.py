#!/usr/bin/env python3
"""Run one controlled repository-level Agent diagnostic trial."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import sys
import time

from dotenv import load_dotenv

from parallel_agent.repository_agent import (
    ControlledCommand,
    RepositoryAgentConfig,
    RepositoryAgentSession,
    detect_parallel_constructs,
    detect_parallel_constructs_in_files,
    run_controlled,
)


ROOT = Path(__file__).resolve().parents[1]


def _parse_command(value: str) -> tuple[str, ...]:
    parsed = json.loads(value)
    if not isinstance(parsed, list) or not parsed or not all(
        isinstance(item, str) for item in parsed
    ):
        raise argparse.ArgumentTypeError("command must be a JSON array of strings")
    return tuple(parsed)


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--trial-root", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--import-subdir")
    parser.add_argument(
        "--edit-mode",
        choices=("legacy", "anchored"),
        default="legacy",
    )
    parser.add_argument("--contract-mode", action="store_true")
    parser.add_argument("--performance-feedback-mode", action="store_true")
    parser.add_argument("--worker-boundary-mode", action="store_true")
    parser.add_argument("--boundary-evidence-mode", action="store_true")
    parser.add_argument(
        "--parallelism-mode",
        choices=("introduce", "optimize_existing"),
        default="introduce",
    )
    parser.add_argument("--test-command", type=_parse_command)
    parser.add_argument("--benchmark-command", type=_parse_command)
    parser.add_argument(
        "--final-benchmark-command",
        type=_parse_command,
        help="Optional 1-warmup/5-repeat command used for baseline and final measurement",
    )
    parser.add_argument(
        "--commands-json",
        type=Path,
        help="JSON object with test, benchmark and optional final_benchmark argv arrays",
    )
    parser.add_argument("--test-timeout", type=int, default=180)
    parser.add_argument("--benchmark-timeout", type=int, default=180)
    parser.add_argument("--context-json", type=Path, required=True)
    parser.add_argument("--skip-baseline", action="store_true")
    return parser.parse_args()


def _initialize_trial(source: Path, trial: Path) -> None:
    if trial.exists():
        raise SystemExit(f"trial root already exists: {trial}")
    trial.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        source,
        trial,
        ignore=shutil.ignore_patterns(
            ".git",
            ".pytest_cache",
            "__pycache__",
            "htmlcov",
            "build",
            "dist",
            "*.egg-info",
        ),
    )
    subprocess.run(["git", "init", "-q"], cwd=trial, check=True)
    subprocess.run(["git", "config", "user.email", "diagnostic@localhost"], cwd=trial, check=True)
    subprocess.run(["git", "config", "user.name", "Diagnostic Baseline"], cwd=trial, check=True)
    subprocess.run(["git", "config", "core.autocrlf", "false"], cwd=trial, check=True)
    subprocess.run(["git", "config", "core.safecrlf", "false"], cwd=trial, check=True)
    subprocess.run(["git", "add", "-A"], cwd=trial, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "serial baseline"], cwd=trial, check=True)


def _command(
    *,
    name: str,
    argv: tuple[str, ...],
    timeout: int,
    trial: Path,
    import_subdir: str,
) -> ControlledCommand:
    import_root = (trial / import_subdir).resolve()
    env = {"PYTHONPATH": str(import_root)}
    return ControlledCommand(
        name=name,
        argv=argv,
        timeout_seconds=timeout,
        cwd=trial,
        env=env,
    )


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _benchmark_summary(result: dict[str, object]) -> dict[str, object]:
    try:
        parsed = json.loads(str(result.get("stdout", "")))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _paired_formal_summary(
    *,
    baseline_before: dict[str, object],
    candidate: dict[str, object],
    baseline_after: dict[str, object] | None,
) -> dict[str, object]:
    before = _benchmark_summary(baseline_before)
    candidate_summary = _benchmark_summary(candidate)
    after = _benchmark_summary(baseline_after or {})
    baseline_medians = [
        float(summary["median_seconds"])
        for summary in (before, after)
        if summary.get("median_seconds") is not None
    ]
    candidate_seconds = candidate_summary.get("median_seconds")
    if not baseline_medians or candidate_seconds is None:
        return {"valid": False, "reason": "missing formal benchmark median"}
    paired_baseline = statistics.median(baseline_medians)
    candidate_median = float(candidate_seconds)
    return {
        "valid": bool(candidate_median > 0),
        "baseline_medians_seconds": baseline_medians,
        "paired_baseline_median_seconds": paired_baseline,
        "candidate_median_seconds": candidate_median,
        "speedup": paired_baseline / candidate_median,
        "method": (
            "median of before/after baseline medians divided by candidate median"
            if len(baseline_medians) == 2
            else "single before baseline median divided by candidate median"
        ),
    }


def _import_preflight(
    *,
    python: Path,
    module: str,
    trial: Path,
    import_subdir: str,
) -> dict[str, object]:
    if not module or any(not (part.isidentifier()) for part in module.split(".")):
        raise ValueError(f"invalid import module: {module!r}")
    command = _command(
        name="trial_import_preflight",
        argv=(
            str(python.resolve()),
            "-c",
            (
                "import importlib, pathlib; "
                f"m=importlib.import_module({module!r}); "
                "print(pathlib.Path(m.__file__).resolve())"
            ),
        ),
        timeout=30,
        trial=trial,
        import_subdir=import_subdir,
    )
    result = run_controlled(command)
    imported_path = str(result.get("stdout", "")).strip().splitlines()
    resolved = Path(imported_path[-1]).resolve() if imported_path else None
    belongs_to_trial = False
    if resolved is not None:
        try:
            resolved.relative_to(trial.resolve())
            belongs_to_trial = True
        except ValueError:
            pass
    return {
        **result,
        "module": module,
        "imported_path": str(resolved) if resolved is not None else None,
        "belongs_to_trial": belongs_to_trial,
        "ok": bool(
            result.get("returncode") == 0
            and not result.get("timed_out")
            and belongs_to_trial
        ),
    }


def _annotate_benchmark(
    result: dict[str, object],
    *,
    expected_output_hash: str | None,
    valid_for_performance: bool,
) -> dict[str, object]:
    annotated = dict(result)
    annotated["valid_for_performance"] = valid_for_performance
    annotated["expected_output_hash"] = expected_output_hash
    actual_hash = None
    try:
        summary = json.loads(str(result.get("stdout", "")))
        hashes = summary.get("output_hashes", [])
        if isinstance(hashes, list) and hashes:
            actual_hash = str(hashes[0])
    except (json.JSONDecodeError, AttributeError):
        pass
    annotated["actual_output_hash"] = actual_hash
    annotated["output_matches_baseline"] = bool(
        expected_output_hash
        and actual_hash
        and actual_hash == expected_output_hash
    )
    return annotated


def main() -> int:
    args = _args()
    load_dotenv(ROOT / ".env", override=False)
    api_key = os.getenv("DEEPSEEK_API_KEY", "")
    if not api_key or api_key == "replace_with_your_key":
        raise SystemExit("DEEPSEEK_API_KEY is not configured")
    model = os.getenv("DEEPSEEK_PRO_MODEL", "deepseek-v4-pro")
    flash_model = os.getenv("DEEPSEEK_FLASH_MODEL", "deepseek-v4-flash")
    base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")

    source = args.source_root.resolve()
    trial = args.trial_root.resolve()
    run_dir = args.run_dir.resolve()
    context = json.loads(args.context_json.read_text(encoding="utf-8"))
    import_subdir = str(
        args.import_subdir
        if args.import_subdir is not None
        else context.get("import_subdir", ".")
    )
    commands: dict[str, tuple[str, ...]] = {}
    if args.commands_json:
        raw_commands = json.loads(args.commands_json.read_text(encoding="utf-8"))
        if not isinstance(raw_commands, dict):
            raise SystemExit("commands JSON must be an object")
        for key in ("test", "benchmark", "final_benchmark"):
            raw_argv = raw_commands.get(key)
            if raw_argv is not None:
                if not isinstance(raw_argv, list) or not raw_argv or not all(
                    isinstance(item, str) for item in raw_argv
                ):
                    raise SystemExit(f"commands JSON field {key!r} must be a string array")
                commands[key] = tuple(raw_argv)
    test_argv = args.test_command or commands.get("test")
    benchmark_argv = args.benchmark_command or commands.get("benchmark")
    final_benchmark_argv = args.final_benchmark_command or commands.get(
        "final_benchmark"
    )
    if not test_argv or not benchmark_argv:
        raise SystemExit(
            "provide test and benchmark commands directly or through --commands-json"
        )
    _initialize_trial(source, trial)

    import_module = str(context.get("import_module", ""))
    if import_module:
        preflight = _import_preflight(
            python=args.python,
            module=import_module,
            trial=trial,
            import_subdir=import_subdir,
        )
        _write_json(run_dir / "import-preflight.json", preflight)
        if not preflight["ok"]:
            _write_json(
                run_dir / "outcome.json",
                {
                    "status": "import_preflight_failure",
                    "project": args.project,
                    "import_preflight": preflight,
                },
            )
            return 2

    test_command = _command(
        name="project_tests",
        argv=test_argv,
        timeout=args.test_timeout,
        trial=trial,
        import_subdir=import_subdir,
    )
    benchmark_command = _command(
        name="quick_end_to_end_benchmark",
        argv=benchmark_argv,
        timeout=args.benchmark_timeout,
        trial=trial,
        import_subdir=import_subdir,
    )
    final_benchmark_command = _command(
        name="formal_end_to_end_benchmark",
        argv=final_benchmark_argv or benchmark_argv,
        timeout=args.benchmark_timeout,
        trial=trial,
        import_subdir=import_subdir,
    )

    started = time.perf_counter()
    baseline: dict[str, object] = {}
    if not args.skip_baseline:
        baseline["test"] = run_controlled(test_command)
        # The Agent receives feedback from the quick benchmark after every edit.
        # Measure the unmodified project with that exact command as well.  This
        # matters when the quick workload is a smaller representative sample of
        # the formal workload: comparing a small candidate run with a large
        # baseline would create a meaningless speedup.
        baseline["quick_benchmark"] = run_controlled(benchmark_command)
        baseline["benchmark"] = run_controlled(final_benchmark_command)
        quick_baseline_summary = _benchmark_summary(baseline["quick_benchmark"])
        baseline_summary = _benchmark_summary(baseline["benchmark"])
        quick_baseline_hashes = quick_baseline_summary.get("output_hashes", [])
        baseline_hashes = baseline_summary.get("output_hashes", [])
        expected_context_hash = str(context.get("baseline_output_hash", ""))
        quick_baseline_hash_matches = bool(
            quick_baseline_hashes
            and all(
                str(value) == expected_context_hash
                for value in quick_baseline_hashes
            )
        )
        formal_baseline_hash_matches = bool(
            baseline_hashes
            and all(str(value) == expected_context_hash for value in baseline_hashes)
        )
        baseline["quick_output_matches_registered_baseline"] = (
            quick_baseline_hash_matches
        )
        baseline["output_matches_registered_baseline"] = (
            formal_baseline_hash_matches
        )
        _write_json(run_dir / "baseline" / "validation.json", baseline)
        if (
            baseline["test"]["returncode"] != 0  # type: ignore[index]
            or baseline["quick_benchmark"]["returncode"] != 0  # type: ignore[index]
            or baseline["benchmark"]["returncode"] != 0  # type: ignore[index]
            or not quick_baseline_hash_matches
            or not formal_baseline_hash_matches
        ):
            _write_json(
                run_dir / "outcome.json",
                {
                    "status": "baseline_failure",
                    "project": args.project,
                    "baseline": baseline,
                },
            )
            return 2
        context = dict(context)
        context["serial_median_seconds"] = float(
            quick_baseline_summary["median_seconds"]
        )
        context["formal_serial_median_seconds"] = float(
            baseline_summary["median_seconds"]
        )
        context["baseline_output_hash"] = str(quick_baseline_hashes[0])
        context["paired_baseline_measured_in_current_trial"] = True
        context["paired_quick_and_formal_baselines"] = True

    config = RepositoryAgentConfig(
        project_id=args.project,
        repository_root=trial,
        run_dir=run_dir / "agent",
        model=model,
        flash_model=flash_model,
        base_url=base_url,
        api_key=api_key,
        test_command=test_command,
        benchmark_command=benchmark_command,
        edit_mode=args.edit_mode,
        contract_mode=args.contract_mode,
        performance_feedback_mode=args.performance_feedback_mode,
        worker_boundary_mode=args.worker_boundary_mode,
        boundary_evidence_mode=args.boundary_evidence_mode,
        parallelism_mode=args.parallelism_mode,
    )
    agent_session = RepositoryAgentSession(config)
    agent_result = agent_session.run(context)
    final_test = run_controlled(test_command)
    patch = subprocess.run(
        ["git", "diff", "--binary"],
        cwd=trial,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    ).stdout
    (run_dir / "agent" / "patch.diff").write_text(patch, encoding="utf-8")
    introduced_parallel_constructs = detect_parallel_constructs(patch)
    retained_parallel_constructs = (
        detect_parallel_constructs_in_files(
            [
                path
                for path in trial.rglob("*.py")
                if ".git" not in path.parts
            ]
        )
        if args.parallelism_mode == "optimize_existing"
        else []
    )
    parallel_constructs = (
        introduced_parallel_constructs
        if args.parallelism_mode == "introduce"
        else retained_parallel_constructs
    )
    expected_output_hash = str(context.get("baseline_output_hash", "")) or None
    tests_passed = (
        final_test.get("returncode") == 0 and not final_test.get("timed_out")
    )
    if patch.strip() and tests_passed:
        final_benchmark = _annotate_benchmark(
            run_controlled(final_benchmark_command),
            expected_output_hash=expected_output_hash,
            valid_for_performance=True,
        )
    elif patch.strip():
        final_benchmark = _annotate_benchmark(
            run_controlled(benchmark_command),
            expected_output_hash=expected_output_hash,
            valid_for_performance=False,
        )
        final_benchmark["reason"] = (
            "Project tests failed. A single diagnostic workload run was retained "
            "to inspect output behavior, but it is excluded from performance claims."
        )
    else:
        final_benchmark = {
            "name": final_benchmark_command.name,
            "argv": list(final_benchmark_command.argv),
            "returncode": 0,
            "elapsed_seconds": 0.0,
            "timed_out": False,
            "skipped": True,
            "reason": (
                "No repository diff was produced; candidate code is byte-for-byte "
                "the serial baseline, so repeated performance measurement adds no "
                "new evidence."
            ),
            "stdout": "",
            "stderr": "",
            "valid_for_performance": False,
            "expected_output_hash": expected_output_hash,
            "actual_output_hash": expected_output_hash,
            "output_matches_baseline": True,
        }

    post_candidate_baseline: dict[str, object] | None = None
    if patch.strip() and tests_passed and agent_session.original_contents:
        candidate_contents = {
            path: path.read_bytes() for path in agent_session.original_contents
        }
        try:
            for path, content in agent_session.original_contents.items():
                path.write_bytes(content.encode("utf-8"))
            post_candidate_baseline = _annotate_benchmark(
                run_controlled(final_benchmark_command),
                expected_output_hash=expected_output_hash,
                valid_for_performance=True,
            )
        finally:
            for path, content in candidate_contents.items():
                path.write_bytes(content)
        baseline["post_candidate_benchmark"] = post_candidate_baseline
        _write_json(run_dir / "baseline" / "validation.json", baseline)

    paired_formal = _paired_formal_summary(
        baseline_before=baseline.get("benchmark", {}),
        candidate=final_benchmark,
        baseline_after=post_candidate_baseline,
    )

    outcome = {
        "schema_version": 1,
        "project": args.project,
        "status": "completed",
        "elapsed_seconds": time.perf_counter() - started,
        "agent": agent_result,
        "baseline": baseline,
        "candidate": {
            "test": final_test,
            "benchmark": final_benchmark,
        },
        "paired_formal_performance": paired_formal,
        "patch_nonempty": bool(patch.strip()),
        "parallel_constructs": parallel_constructs,
        "introduced_parallel_constructs": introduced_parallel_constructs,
        "retained_parallel_constructs": retained_parallel_constructs,
        "parallelism_mode": args.parallelism_mode,
    }
    _write_json(run_dir / "outcome.json", outcome)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
