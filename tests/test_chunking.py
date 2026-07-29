from parallel_agent.chunking import estimate_chunk_count, split_evenly


def test_split_evenly_preserves_order() -> None:
    chunks = split_evenly(list(range(10)), 3)
    assert [item for chunk in chunks for item in chunk] == list(range(10))
    assert len(chunks) == 3


def test_tiny_items_are_batched() -> None:
    count = estimate_chunk_count(
        item_count=10_000,
        workers=4,
        item_runtime_seconds=0.00001,
        task_overhead_seconds=0.001,
    )
    assert 4 <= count < 10_000
