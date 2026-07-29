from __future__ import annotations

from typing import Sequence

import numpy as np

NAME = "pairwise_distance"
ROWS_PER_TASK = 800
FEATURES = 32
CENTERS = 48


def make_input(size: int, seed: int) -> list[tuple[np.ndarray, np.ndarray]]:
    rng = np.random.default_rng(seed)
    centers = rng.normal(size=(CENTERS, FEATURES)).astype(np.float64)
    return [
        (
            rng.normal(size=(ROWS_PER_TASK, FEATURES)).astype(np.float64),
            centers,
        )
        for _ in range(size)
    ]


def unit(item: tuple[np.ndarray, np.ndarray]) -> np.ndarray:
    rows, centers = item
    squared = ((rows[:, None, :] - centers[None, :, :]) ** 2).sum(axis=2)
    return squared.min(axis=1)


def combine(values: Sequence[np.ndarray]) -> np.ndarray:
    return np.concatenate(values)


def equivalent(left: np.ndarray, right: np.ndarray) -> bool:
    return bool(np.allclose(left, right, rtol=1e-12, atol=1e-12))

