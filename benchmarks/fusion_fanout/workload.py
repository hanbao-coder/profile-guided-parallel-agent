from __future__ import annotations


FANOUT = 2


def make_input(size: int, seed: int) -> list[int]:
    return [seed + index for index in range(max(1, size))]


def produce(item: int) -> tuple[int, bytes]:
    value = item
    for index in range(180_000):
        value = (
            value * 1_664_525 + 1_013_904_223 + index
        ) & 0xFFFFFFFF
    return value, bytes([value & 0xFF]) * 1_024


def consume_a(intermediate: tuple[int, bytes]) -> int:
    value, payload = intermediate
    return (value + payload[0] + len(payload)) & 0xFFFFFFFF


def consume_b(intermediate: tuple[int, bytes]) -> int:
    value, payload = intermediate
    return (value ^ payload[-1] ^ len(payload)) & 0xFFFFFFFF


def combine(outputs_a: list[int], outputs_b: list[int] | None) -> int:
    assert outputs_b is not None
    return (sum(outputs_a) + sum(outputs_b)) & 0xFFFFFFFF


def equivalent(left: int, right: int) -> bool:
    return left == right
