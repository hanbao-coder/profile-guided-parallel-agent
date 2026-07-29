from __future__ import annotations

import math
from typing import Sequence

NAME = "prime_count"


def make_input(size: int, seed: int) -> list[tuple[int, int]]:
    del seed
    width = 12_000
    start = 1_000_000
    return [(start + i * width, start + (i + 1) * width) for i in range(size)]


def _is_prime(value: int) -> bool:
    if value < 2:
        return False
    if value % 2 == 0:
        return value == 2
    limit = math.isqrt(value)
    for divisor in range(3, limit + 1, 2):
        if value % divisor == 0:
            return False
    return True


def unit(interval: tuple[int, int]) -> int:
    start, stop = interval
    return sum(_is_prime(value) for value in range(start, stop))


def combine(values: Sequence[int]) -> int:
    return sum(values)


def equivalent(left: int, right: int) -> bool:
    return left == right

