from __future__ import annotations

import math


def make_input(size: int, seed: int) -> list[tuple[int, int]]:
    del seed
    width = 12_000
    start = 1_000_000
    return [
        (start + index * width, start + (index + 1) * width)
        for index in range(size)
    ]


def is_prime(value: int) -> bool:
    if value < 2:
        return False
    if value % 2 == 0:
        return value == 2
    limit = math.isqrt(value)
    return all(value % divisor for divisor in range(3, limit + 1, 2))


def process_interval(interval: tuple[int, int]) -> int:
    start, stop = interval
    return sum(is_prime(value) for value in range(start, stop))


def aggregate_counts(values: list[int]) -> int:
    return sum(values)


def equivalent(left: int, right: int) -> bool:
    return left == right


def run_serial(items: list[tuple[int, int]]) -> int:
    results = []
    for interval in items:
        results.append(process_interval(interval))
    return aggregate_counts(results)
