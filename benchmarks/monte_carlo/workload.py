from __future__ import annotations

import random
from typing import Sequence

NAME = "monte_carlo_pi"
SAMPLES_PER_TASK = 120_000


def make_input(size: int, seed: int) -> list[int]:
    return [seed + index * 104_729 for index in range(size)]


def unit(task_seed: int) -> tuple[int, int]:
    rng = random.Random(task_seed)
    inside = 0
    for _ in range(SAMPLES_PER_TASK):
        x = rng.random()
        y = rng.random()
        inside += x * x + y * y <= 1.0
    return inside, SAMPLES_PER_TASK


def combine(values: Sequence[tuple[int, int]]) -> float:
    inside = sum(value[0] for value in values)
    total = sum(value[1] for value in values)
    return 4.0 * inside / total


def equivalent(left: float, right: float) -> bool:
    return abs(left - right) <= 1e-12

