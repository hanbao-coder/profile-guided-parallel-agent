from __future__ import annotations

from typing import Sequence

import numpy as np

NAME = "mandelbrot"
WIDTH = 800
MAX_ITER = 160


def make_input(size: int, seed: int) -> list[tuple[int, int]]:
    del seed
    return [(row, size) for row in range(size)]


def unit(item: tuple[int, int]) -> np.ndarray:
    row, height = item
    y = -1.25 + 2.5 * row / max(1, height - 1)
    output = np.zeros(WIDTH, dtype=np.int16)
    for x_index, x in enumerate(np.linspace(-2.0, 1.0, WIDTH)):
        c = complex(float(x), y)
        z = 0j
        for iteration in range(MAX_ITER):
            z = z * z + c
            if abs(z) > 2.0:
                output[x_index] = iteration
                break
        else:
            output[x_index] = MAX_ITER
    return output


def combine(values: Sequence[np.ndarray]) -> np.ndarray:
    return np.stack(values, axis=0)


def equivalent(left: np.ndarray, right: np.ndarray) -> bool:
    return bool(np.array_equal(left, right))
