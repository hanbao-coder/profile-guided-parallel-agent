#!/usr/bin/env python3
"""Evaluate an Agent-edited scikit-learn source tree in an isolated WSL wheel."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


TASKS = {
    "28064": {
        "tests": (
            "sklearn.ensemble._hist_gradient_boosting.tests.test_binning",
        ),
        "benchmark_script": ROOT / "scripts" / "benchmark_sklearn_28064.py",
        "style_files": (
            "ensemble/_hist_gradient_boosting/binning.py",
        ),
        "quick_args": (
            "--samples", "200000", "--features", "20", "--bins", "256",
            "--threads", "4", "--warmups", "1", "--repeats", "3",
        ),
        "formal_args": (
            "--samples", "200000", "--features", "20", "--bins", "256",
            "--threads", "4", "--warmups", "1", "--repeats", "5",
        ),
    },
    "29330": {
        "tests": (
            "sklearn.compose.tests.test_column_transformer",
            "sklearn.tests.test_pipeline",
        ),
        "benchmark_script": ROOT / "scripts" / "benchmark_sklearn_29330.py",
        "style_files": (
            "compose/_column_transformer.py",
            "pipeline.py",
        ),
        "quick_args": (
            "--rows", "10000", "--columns", "40", "--jobs", "2",
            "--warmups", "0", "--repeats", "1",
        ),
        "formal_args": (
            "--rows", "100000", "--columns", "40", "--jobs", "2",
            "--warmups", "1", "--repeats", "3",
        ),
    },
}


def windows_to_wsl_path(path: Path) -> str:
    resolved = path.resolve()
    drive = resolved.drive.rstrip(":").lower()
    if not drive or len(drive) != 1:
        raise ValueError(f"expected a drive-letter path, got {resolved}")
    tail = resolved.as_posix().split(":", 1)[1]
    return f"/mnt/{drive}{tail}"


def _run_wsl(
    *, distro: str, argv: list[str], timeout: int
) -> subprocess.CompletedProcess[str]:
    environment = [
        "PYTHONDONTWRITEBYTECODE=1",
        "PYTHONPYCACHEPREFIX=/tmp/m8-candidate-pycache",
        "OMP_NUM_THREADS=1",
        "MKL_NUM_THREADS=1",
        "OPENBLAS_NUM_THREADS=1",
        "PYTHONHASHSEED=0",
    ]
    return subprocess.run(
        ["wsl.exe", "-d", distro, "--cd", "/tmp", "--", "env", *environment, *argv],
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def _sync_candidate(args: argparse.Namespace) -> None:
    source = windows_to_wsl_path(Path.cwd() / "sklearn")
    sync_script = windows_to_wsl_path(ROOT / "scripts" / "sync_sklearn_candidate.py")
    completed = _run_wsl(
        distro=args.distro,
        argv=[
            args.wsl_python,
            sync_script,
            "--source",
            source,
            "--destination",
            args.wsl_sklearn,
        ],
        timeout=args.timeout,
    )
    if completed.returncode != 0:
        sys.stderr.write(completed.stdout)
        sys.stderr.write(completed.stderr)
        raise SystemExit(completed.returncode)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", choices=tuple(TASKS), required=True)
    parser.add_argument("--mode", choices=("test", "benchmark"), required=True)
    parser.add_argument("--formal", action="store_true")
    parser.add_argument("--distro", default="Ubuntu")
    parser.add_argument("--wsl-python", required=True)
    parser.add_argument("--wsl-sklearn", required=True)
    parser.add_argument("--timeout", type=int, default=900)
    args = parser.parse_args()

    _sync_candidate(args)
    task = TASKS[args.task]
    if args.mode == "test":
        test_argv = [
            args.wsl_python,
            "-m",
            "pytest",
            "--no-header",
            "-q",
            "--pyargs",
            *task["tests"],
        ]
        completed = _run_wsl(
            distro=args.distro, argv=test_argv, timeout=args.timeout
        )
        sys.stdout.write(completed.stdout)
        sys.stderr.write(completed.stderr)
        if completed.returncode != 0:
            return completed.returncode

        style_paths = [
            f"{args.wsl_sklearn.rstrip('/')}/{relative}"
            for relative in task["style_files"]
        ]
        style_commands = [
            [
                args.wsl_python,
                "-m",
                "ruff",
                "check",
                "--no-cache",
                "--select",
                "E,F,W,I",
                "--ignore",
                "E203,E731",
                "--line-length",
                "88",
                *style_paths,
            ],
            [
                args.wsl_python,
                "-m",
                "black",
                "--check",
                "--line-length",
                "88",
                "--target-version",
                "py39",
                *style_paths,
            ],
        ]
        for style_argv in style_commands:
            style_result = _run_wsl(
                distro=args.distro,
                argv=style_argv,
                timeout=args.timeout,
            )
            sys.stdout.write(style_result.stdout)
            sys.stderr.write(style_result.stderr)
            if style_result.returncode != 0:
                return style_result.returncode
        return 0
    else:
        benchmark_script = windows_to_wsl_path(task["benchmark_script"])
        label = "candidate-formal" if args.formal else "candidate-quick"
        output = f"/tmp/m8-{args.task}-{label}.json"
        benchmark_args = task["formal_args"] if args.formal else task["quick_args"]
        argv = [
            args.wsl_python,
            benchmark_script,
            "--label",
            label,
            *benchmark_args,
            "--output",
            output,
        ]
    completed = _run_wsl(distro=args.distro, argv=argv, timeout=args.timeout)
    sys.stdout.write(completed.stdout)
    sys.stderr.write(completed.stderr)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
