from __future__ import annotations

import json
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass
class CandidateRun:
    mode: str
    returncode: int
    elapsed_seconds: float
    stdout: str
    stderr: str
    payload: dict[str, Any] | None
    error_type: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def execute_candidate(
    candidate_path: str | Path,
    *,
    mode: str,
    size: int,
    seed: int,
    timeout_seconds: float,
    workers: int | None = None,
    chunks: int | None = None,
) -> CandidateRun:
    command = [
        sys.executable,
        str(Path(candidate_path).resolve()),
        "--mode",
        mode,
        "--size",
        str(size),
        "--seed",
        str(seed),
    ]
    if workers is not None:
        command.extend(["--workers", str(workers)])
    if chunks is not None:
        command.extend(["--chunks", str(chunks)])
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return CandidateRun(
            mode=mode,
            returncode=-1,
            elapsed_seconds=time.perf_counter() - started,
            stdout=exc.stdout or "",
            stderr=exc.stderr or "",
            payload=None,
            error_type="timeout",
        )

    payload = None
    error_type = None
    if completed.returncode == 0:
        try:
            payload = json.loads(completed.stdout.strip().splitlines()[-1])
        except (json.JSONDecodeError, IndexError):
            error_type = "invalid_json_output"
    else:
        error_type = "runtime_error"
    return CandidateRun(
        mode=mode,
        returncode=completed.returncode,
        elapsed_seconds=time.perf_counter() - started,
        stdout=completed.stdout,
        stderr=completed.stderr,
        payload=payload,
        error_type=error_type,
    )
