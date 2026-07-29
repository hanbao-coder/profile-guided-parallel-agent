from __future__ import annotations

import zlib


FANOUT = 1


def make_input(size: int, seed: int) -> list[int]:
    return [seed + index for index in range(max(1, size))]


def produce(item: int) -> bytes:
    return bytes([item & 0xFF]) * 262_144


def consume_a(intermediate: bytes) -> int:
    checksum = 0
    for _ in range(8):
        checksum = zlib.crc32(intermediate, checksum)
    return checksum


def consume_b(intermediate: bytes) -> int:
    del intermediate
    raise RuntimeError("single-consumer workload has no second branch")


def combine(outputs_a: list[int], outputs_b: list[int] | None) -> int:
    del outputs_b
    return sum(outputs_a) & 0xFFFFFFFF


def equivalent(left: int, right: int) -> bool:
    return left == right
