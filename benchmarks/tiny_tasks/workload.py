from __future__ import annotations

from typing import Sequence

NAME = "tiny_tasks"


def make_input(size: int, seed: int) -> list[int]:
    del seed
    return list(range(size))


def unit(item: int) -> int:
    # Deliberately small CPU task: one task per item creates excessive overhead.
    value = item + 1
    total = 0
    for index in range(1_200):
        total = (total + value * index * index) % 1_000_000_007
    return total


def combine(values: Sequence[int]) -> int:
    return sum(values) % 1_000_000_007


def equivalent(left: int, right: int) -> bool:
    return left == right

