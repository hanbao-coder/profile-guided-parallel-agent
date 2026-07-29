from __future__ import annotations

from typing import Iterable


PAYLOAD_BYTES = 128 * 1024


def make_input(size: int, seed: int) -> list[bytes]:
    count = max(1, size)
    return [
        bytes([(seed + index) % 256]) * PAYLOAD_BYTES
        for index in range(count)
    ]


def unit(item: bytes) -> int:
    return sum(item)


def combine(values: Iterable[int]) -> int:
    return sum(values)


def equivalent(left: int, right: int) -> bool:
    return left == right
