from __future__ import annotations

import multiprocessing

NAME = "child_failure"


def make_input(size: int, seed: int):
    del seed
    return list(range(size))


def unit(item: int) -> int:
    if multiprocessing.current_process().name != "MainProcess":
        raise RuntimeError("intentional child-process failure")
    return item * 2


def combine(values):
    return list(values)


def equivalent(left, right):
    return left == right

