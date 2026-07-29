from __future__ import annotations

from typing import Iterable


def make_input(size: int, seed: int) -> list[tuple[int, int]]:
    del seed
    count = max(4, size)
    heavy_count = max(1, count // 4)
    heavy_iterations = 180_000
    light_iterations = 8_000
    return [
        (
            heavy_iterations
            if index < heavy_count
            else light_iterations,
            index + 1,
        )
        for index in range(count)
    ]


def unit(item: tuple[int, int]) -> int:
    iterations, value = item
    accumulator = value
    for index in range(iterations):
        accumulator = (
            accumulator * 1_664_525
            + 1_013_904_223
            + index
        ) & 0xFFFFFFFF
    return accumulator


def combine(values: Iterable[int]) -> int:
    return sum(values) & 0xFFFFFFFF


def equivalent(left: int, right: int) -> bool:
    return left == right
