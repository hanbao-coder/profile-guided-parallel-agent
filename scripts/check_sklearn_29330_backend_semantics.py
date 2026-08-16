#!/usr/bin/env python3
"""Held-out check that ColumnTransformer still respects joblib backend context."""

from __future__ import annotations

import json
import os

import numpy as np
import pandas as pd
from joblib import parallel_backend
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.compose import ColumnTransformer


class ProcessIdentityTransformer(TransformerMixin, BaseEstimator):
    """Return the process id that actually ran each transformation."""

    def fit(self, X, y=None):
        return self

    def transform(self, X):
        return np.full((len(X), 1), os.getpid(), dtype=np.int64)


def main() -> int:
    frame = pd.DataFrame(
        {f"column_{index}": np.arange(32) for index in range(4)}
    )
    transformer = ColumnTransformer(
        [
            (
                f"identity_{index}",
                ProcessIdentityTransformer(),
                [f"column_{index}"],
            )
            for index in range(4)
        ],
        n_jobs=2,
    )
    main_pid = os.getpid()
    with parallel_backend("loky", n_jobs=2):
        output = transformer.fit_transform(frame)
    observed_pids = sorted({int(value) for value in output.ravel()})
    respects_external_backend = any(pid != main_pid for pid in observed_pids)
    print(
        json.dumps(
            {
                "main_pid": main_pid,
                "observed_worker_pids": observed_pids,
                "respects_external_loky_backend": respects_external_backend,
            },
            indent=2,
        )
    )
    if not respects_external_backend:
        print(
            "ColumnTransformer ignored the caller-selected loky backend; "
            "a candidate must not hard-code a conflicting backend."
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
