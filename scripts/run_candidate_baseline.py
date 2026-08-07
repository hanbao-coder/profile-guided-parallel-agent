"""Run a repeatable end-to-end workload for a screened real project.

This adapter deliberately calls each project's public command-line entry point
or the function used by that entry point.  It does not replace the project
implementation.  Its job is to provide the same input, timing procedure and
canonical output before and after an Agent patch.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import os
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Callable


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _python_files(root: Path, limit: int | None = None) -> list[Path]:
    files = sorted(path for path in root.rglob("*.py") if path.is_file())
    return files if limit is None else files[:limit]


def _all_data_files(root: Path, limit: int | None = None) -> list[Path]:
    files = sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and path.name != ".test-data-ref"
    )
    return files if limit is None else files[:limit]


def _radon_workload(input_root: Path, limit: int | None) -> Callable[[], Any]:
    from radon.cli import cc

    targets = [str(path) for path in _python_files(input_root, limit)]

    def run() -> Any:
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            cc(targets, json=True)
        return json.loads(stream.getvalue())

    return run


def _vulture_workload(input_root: Path, limit: int | None) -> Callable[[], Any]:
    from vulture.core import Vulture

    files = _python_files(input_root, limit)

    def run() -> Any:
        analyzer = Vulture(verbose=False)
        analyzer.scavenge(files)
        return [
            {
                "filename": str(item.filename),
                "first_lineno": item.first_lineno,
                "last_lineno": item.last_lineno,
                "name": item.name,
                "size": item.size,
                "typ": item.typ,
            }
            for item in analyzer.get_unused_code(min_confidence=0, sort_by_size=False)
        ]

    return run


def _chardet_workload(input_root: Path, limit: int | None) -> Callable[[], Any]:
    import chardet
    from chardet._utils import DEFAULT_MAX_BYTES

    files = _all_data_files(input_root, limit)

    def run() -> Any:
        results = []
        for path in files:
            data = path.read_bytes()[:DEFAULT_MAX_BYTES]
            results.append(
                {
                    "path": path.relative_to(input_root).as_posix(),
                    "result": chardet.detect(data),
                }
            )
        return results

    return run


WORKLOADS: dict[str, Callable[[Path, int | None], Callable[[], Any]]] = {
    "radon": _radon_workload,
    "vulture": _vulture_workload,
    "chardet": _chardet_workload,
}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", choices=sorted(WORKLOADS), required=True)
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--limit", type=int)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if not args.input_root.is_dir():
        raise SystemExit(f"input root does not exist: {args.input_root}")
    if args.warmups < 0 or args.repeats < 1:
        raise SystemExit("warmups must be >= 0 and repeats must be >= 1")

    for name in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
        os.environ.setdefault(name, "1")
    os.environ.setdefault("PYTHONHASHSEED", "0")

    workload = WORKLOADS[args.project](args.input_root.resolve(), args.limit)
    for _ in range(args.warmups):
        workload()

    timings: list[float] = []
    hashes: list[str] = []
    final_output: Any = None
    for _ in range(args.repeats):
        started = time.perf_counter()
        final_output = workload()
        timings.append(time.perf_counter() - started)
        hashes.append(_canonical_hash(final_output))

    result = {
        "schema_version": 1,
        "project": args.project,
        "python": sys.version,
        "input_root": str(args.input_root.resolve()),
        "limit": args.limit,
        "warmups": args.warmups,
        "repeats": args.repeats,
        "timings_seconds": timings,
        "median_seconds": statistics.median(timings),
        "output_hashes": hashes,
        "stable_output": len(set(hashes)) == 1,
        "output_items": len(final_output) if hasattr(final_output, "__len__") else None,
        "canonical_output": final_output,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {key: value for key, value in result.items() if key != "canonical_output"},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if result["stable_output"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
