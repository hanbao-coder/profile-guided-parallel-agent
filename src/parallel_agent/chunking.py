from __future__ import annotations

import math
from collections.abc import Sequence
from typing import TypeVar

T = TypeVar("T")


def split_evenly(items: Sequence[T], chunk_count: int) -> list[list[T]]:
    if chunk_count <= 0:
        raise ValueError("chunk_count must be positive")
    if not items:
        return []
    actual = min(len(items), chunk_count)
    width = math.ceil(len(items) / actual)
    return [list(items[i : i + width]) for i in range(0, len(items), width)]


def estimate_chunk_count(
    item_count: int,
    workers: int,
    item_runtime_seconds: float,
    task_overhead_seconds: float,
    target_overhead_ratio: float = 0.05,
) -> int:
    """Choose enough work per task that fixed overhead stays near the target."""
    if item_count <= 0:
        return 0
    if workers <= 0:
        raise ValueError("workers must be positive")
    safe_item_runtime = max(item_runtime_seconds, 1e-9)
    min_task_compute = task_overhead_seconds * (1 - target_overhead_ratio) / max(
        target_overhead_ratio, 1e-6
    )
    items_per_chunk = max(1, math.ceil(min_task_compute / safe_item_runtime))
    desired = math.ceil(item_count / items_per_chunk)
    return max(1, min(item_count, max(workers, desired)))

