#!/usr/bin/env python3
"""Reproduce the scikit-learn #29330 worker-boundary workload.

The base revision sends the complete dataframe to every parallel transformer
and selects columns inside the worker.  The expert patch selects each
transformer's columns before dispatch.  This script keeps the data, backend,
and correctness check fixed so that only that boundary change is compared.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pickle
import platform
import random
import statistics
import time
from pathlib import Path


def _output_hash(array: object) -> str:
    import numpy as np

    contiguous = np.ascontiguousarray(array)
    digest = hashlib.sha256()
    digest.update(str(contiguous.dtype).encode("ascii"))
    digest.update(str(contiguous.shape).encode("ascii"))
    digest.update(contiguous.tobytes())
    return digest.hexdigest()


def _make_dataframe(*, rows: int, columns: int, seed: int):
    import pandas as pd

    generator = random.Random(seed)
    return pd.DataFrame(
        {
            str(column): [
                [generator.random() for _ in range(generator.randint(1, 5))]
                for _ in range(rows)
            ]
            for column in range(columns)
        }
    )


def _list_sum(frame):
    return frame.squeeze(axis=1).apply(sum).to_numpy().reshape(-1, 1)


def _build_pipeline(*, columns: int, jobs: int):
    from sklearn.compose import ColumnTransformer
    from sklearn.pipeline import FunctionTransformer, Pipeline

    return Pipeline(
        [
            (
                "transformer",
                ColumnTransformer(
                    [
                        (
                            str(column),
                            FunctionTransformer(_list_sum, validate=False),
                            [str(column)],
                        )
                        for column in range(columns)
                    ],
                    n_jobs=jobs,
                ),
            )
        ]
    )


def _run_once(frame, *, columns: int, jobs: int) -> tuple[float, str]:
    import joblib

    pipeline = _build_pipeline(columns=columns, jobs=jobs)
    started = time.perf_counter()
    with joblib.parallel_backend(backend="loky", mmap_mode="r+"):
        output = pipeline.fit_transform(frame)
    elapsed = time.perf_counter() - started
    return elapsed, _output_hash(output)


def _boundary_proxy(frame, *, columns: int, sample_rows: int) -> dict[str, int | float]:
    """Estimate bytes crossing the old and expert worker boundaries.

    This is deliberately reported as a serialization *proxy*.  Joblib may
    batch or cache payloads internally, so these values are not presented as
    measured network traffic.  The ratio isolates the code-level difference:
    full input per task versus one selected column per task.
    """

    sample = frame.iloc[:sample_rows]
    full_bytes = len(pickle.dumps(sample, protocol=pickle.HIGHEST_PROTOCOL))
    sliced_bytes = sum(
        len(
            pickle.dumps(
                sample[[str(column)]], protocol=pickle.HIGHEST_PROTOCOL
            )
        )
        for column in range(columns)
    )
    old_boundary_bytes = full_bytes * columns
    return {
        "sample_rows": sample_rows,
        "full_dataframe_once_bytes": full_bytes,
        "old_full_dataframe_per_task_bytes": old_boundary_bytes,
        "expert_presliced_columns_total_bytes": sliced_bytes,
        "old_to_expert_ratio": old_boundary_bytes / sliced_bytes,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True)
    parser.add_argument("--rows", type=int, default=100_000)
    parser.add_argument("--columns", type=int, default=40)
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--seed", type=int, default=20260816)
    parser.add_argument("--payload-sample-rows", type=int, default=1_000)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    import joblib
    import numpy as np
    import pandas as pd
    import sklearn

    frame = _make_dataframe(rows=args.rows, columns=args.columns, seed=args.seed)
    boundary_proxy = _boundary_proxy(
        frame,
        columns=args.columns,
        sample_rows=min(args.payload_sample_rows, args.rows),
    )

    for _ in range(args.warmups):
        _run_once(frame, columns=args.columns, jobs=args.jobs)

    timings: list[float] = []
    hashes: list[str] = []
    for _ in range(args.repeats):
        elapsed, result_hash = _run_once(
            frame,
            columns=args.columns,
            jobs=args.jobs,
        )
        timings.append(elapsed)
        hashes.append(result_hash)

    if len(timings) >= 2:
        q1, _, q3 = statistics.quantiles(
            sorted(timings), n=4, method="inclusive"
        )
        iqr_seconds = q3 - q1
    else:
        iqr_seconds = 0.0
    payload = {
        "schema_version": 1,
        "task": "scikit-learn__scikit-learn-29330",
        "label": args.label,
        "configuration": {
            "rows": args.rows,
            "columns": args.columns,
            "jobs": args.jobs,
            "warmups": args.warmups,
            "repeats": args.repeats,
            "seed": args.seed,
        },
        "timings_seconds": timings,
        "median_seconds": statistics.median(timings),
        "iqr_seconds": iqr_seconds,
        "output_hashes": hashes,
        "stable_output": len(set(hashes)) == 1,
        "boundary_serialization_proxy": boundary_proxy,
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "logical_cpus": os.cpu_count(),
            "numpy": np.__version__,
            "pandas": pd.__version__,
            "joblib": joblib.__version__,
            "scikit_learn": sklearn.__version__,
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
