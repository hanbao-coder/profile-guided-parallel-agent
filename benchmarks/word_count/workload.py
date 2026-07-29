from __future__ import annotations

import random
from collections import Counter
from typing import Mapping, Sequence

NAME = "word_count"
VOCABULARY = [
    "agent",
    "parallel",
    "python",
    "worker",
    "chunk",
    "runtime",
    "profile",
    "schedule",
    "compute",
    "data",
    "model",
    "system",
]


def make_input(size: int, seed: int) -> list[str]:
    rng = random.Random(seed)
    return [
        " ".join(rng.choices(VOCABULARY, k=12_000))
        for _ in range(size)
    ]


def unit(document: str) -> dict[str, int]:
    return dict(Counter(document.split()))


def combine(values: Sequence[Mapping[str, int]]) -> dict[str, int]:
    total: Counter[str] = Counter()
    for value in values:
        total.update(value)
    return dict(sorted(total.items()))


def equivalent(left: Mapping[str, int], right: Mapping[str, int]) -> bool:
    return dict(left) == dict(right)

