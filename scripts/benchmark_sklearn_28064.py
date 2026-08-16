#!/usr/bin/env python3
"""Reproduce the scikit-learn #28064 bin-threshold parallelism workload.

Run this script with the isolated Python environment built from the pinned
scikit-learn source revision.  The same command is used before and after the
expert patch; only the checked-out source changes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import statistics
import time
from pathlib import Path

import numpy as np
from sklearn.datasets import make_classification
from sklearn.ensemble._hist_gradient_boosting.binning import _BinMapper


def _result_hash(mapper: _BinMapper) -> str:
    digest = hashlib.sha256()
    for thresholds in mapper.bin_thresholds_:
        array = np.ascontiguousarray(thresholds)
        digest.update(str(array.dtype).encode("ascii"))
        digest.update(str(array.shape).encode("ascii"))
        digest.update(array.tobytes())
    digest.update(np.ascontiguousarray(mapper.n_bins_non_missing_).tobytes())
    return digest.hexdigest()


def _run_once(
    X: np.ndarray,
    *,
    n_bins: int,
    n_threads: int,
) -> tuple[float, str]:
    categorical = np.zeros(X.shape[1], dtype=bool)
    mapper = _BinMapper(
        n_bins=n_bins,
        is_categorical=categorical,
        known_categories=None,
        random_state=1,
        n_threads=n_threads,
    )
    started = time.perf_counter()
    mapper.fit(X)
    elapsed = time.perf_counter() - started
    return elapsed, _result_hash(mapper)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True)
    parser.add_argument("--samples", type=int, default=200_000)
    parser.add_argument("--features", type=int, default=20)
    parser.add_argument("--bins", type=int, default=256)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    X, _ = make_classification(
        n_samples=args.samples,
        n_features=args.features,
        random_state=20260816,
    )
    for _ in range(args.warmups):
        _run_once(X, n_bins=args.bins, n_threads=args.threads)

    timings: list[float] = []
    hashes: list[str] = []
    for _ in range(args.repeats):
        elapsed, result_hash = _run_once(
            X,
            n_bins=args.bins,
            n_threads=args.threads,
        )
        timings.append(elapsed)
        hashes.append(result_hash)

    ordered = sorted(timings)
    if len(ordered) >= 2:
        q1, _, q3 = statistics.quantiles(ordered, n=4, method="inclusive")
        iqr_seconds = q3 - q1
    else:
        iqr_seconds = 0.0
    payload = {
        "schema_version": 1,
        "task": "scikit-learn__scikit-learn-28064",
        "label": args.label,
        "source_file": str(Path(__file__).resolve()),
        "configuration": {
            "samples": args.samples,
            "features": args.features,
            "bins": args.bins,
            "threads": args.threads,
            "warmups": args.warmups,
            "repeats": args.repeats,
            "random_seed": 20260816,
        },
        "timings_seconds": timings,
        "median_seconds": statistics.median(timings),
        "iqr_seconds": iqr_seconds,
        "output_hashes": hashes,
        "stable_output": len(set(hashes)) == 1,
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "logical_cpus": os.cpu_count(),
            "numpy": np.__version__,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["stable_output"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
