from __future__ import annotations

from pathlib import Path

from .artifacts import ParallelPlan


_CANDIDATE_TEMPLATE = '''\
from __future__ import annotations

import argparse
import importlib.util
import json
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

DEFAULT_SOURCE = {source_path!r}
DEFAULT_WORKERS = {workers}
DEFAULT_CHUNKS = {chunks}


def load_source(path: str):
    file_path = Path(path).resolve()
    spec = importlib.util.spec_from_file_location("agent_candidate_source", file_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load source: {{file_path}}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def split_evenly(items, chunk_count: int):
    if not items:
        return []
    actual = min(len(items), max(1, chunk_count))
    width = (len(items) + actual - 1) // actual
    return [list(items[index:index + width]) for index in range(0, len(items), width)]


def run_chunk(source_path: str, chunk):
    module = load_source(source_path)
    return [module.unit(item) for item in chunk]


def normalize(value: Any):
    if hasattr(value, "tolist"):
        return value.tolist()
    if isinstance(value, dict):
        return {{str(key): normalize(item) for key, item in value.items()}}
    if isinstance(value, (list, tuple)):
        return [normalize(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def execute(mode: str, source_path: str, size: int, seed: int, workers: int, chunks: int):
    module = load_source(source_path)
    items = module.make_input(size, seed)
    started = time.perf_counter()
    if mode == "serial":
        result = module.combine([module.unit(item) for item in items])
        task_count = 1
    else:
        task_chunks = split_evenly(items, chunks)
        with ProcessPoolExecutor(max_workers=workers) as pool:
            nested = list(
                pool.map(
                    run_chunk,
                    [source_path] * len(task_chunks),
                    task_chunks,
                )
            )
        result = module.combine([item for group in nested for item in group])
        task_count = len(task_chunks)
    return {{
        "mode": mode,
        "result": normalize(result),
        "runtime_seconds": time.perf_counter() - started,
        "task_count": task_count,
    }}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["serial", "parallel"], required=True)
    parser.add_argument("--source", default=DEFAULT_SOURCE)
    parser.add_argument("--size", type=int, default=4)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--chunks", type=int, default=DEFAULT_CHUNKS)
    args = parser.parse_args()
    payload = execute(
        args.mode, args.source, args.size, args.seed, args.workers, args.chunks
    )
    print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    main()
'''


def generate_candidate(plan: ParallelPlan, output_path: str | Path) -> Path:
    plan.validate()
    if not plan.parallelizable:
        raise ValueError("Cannot generate parallel candidate for a rejected plan")
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        _CANDIDATE_TEMPLATE.format(
            source_path=plan.source_path,
            workers=plan.workers,
            chunks=plan.chunks,
        ),
        encoding="utf-8",
    )
    return output

