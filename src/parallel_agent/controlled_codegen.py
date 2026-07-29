from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from .artifacts import ParallelPlan


class GeneratedCodeSafetyError(ValueError):
    pass


EXPECTED_SIGNATURES = {
    "partition_items": ["items", "chunk_count"],
    "execute_parallel": ["source_path", "items", "workers", "chunks"],
}
ALLOWED_NAME_CALLS = {
    "ProcessPoolExecutor",
    "_safe_run_chunk",
    "enumerate",
    "len",
    "list",
    "max",
    "min",
    "partition_items",
    "range",
    "tuple",
    "zip",
}
ALLOWED_ATTRIBUTE_CALLS = {
    "append",
    "extend",
    "map",
    "result",
    "submit",
}
BANNED_NODES = (
    ast.AsyncFunctionDef,
    ast.Await,
    ast.ClassDef,
    ast.Delete,
    ast.Global,
    ast.Import,
    ast.ImportFrom,
    ast.Lambda,
    ast.Nonlocal,
    ast.While,
)
BANNED_NAMES = {
    "__import__",
    "breakpoint",
    "compile",
    "eval",
    "exec",
    "exit",
    "globals",
    "help",
    "input",
    "locals",
    "open",
    "quit",
    "vars",
}
BANNED_ATTRIBUTES = {
    "chmod",
    "connect",
    "dump",
    "dumps",
    "mkdir",
    "open",
    "popen",
    "remove",
    "rename",
    "replace",
    "request",
    "rmdir",
    "send",
    "socket",
    "system",
    "unlink",
    "write",
    "write_bytes",
    "write_text",
}


def canonical_parallel_impl() -> str:
    return """\
def partition_items(items, chunk_count):
    if not items:
        return []
    actual = min(len(items), max(1, chunk_count))
    width = (len(items) + actual - 1) // actual
    return [
        list(items[index:index + width])
        for index in range(0, len(items), width)
    ]


def execute_parallel(source_path, items, workers, chunks):
    task_chunks = partition_items(items, chunks)
    with ProcessPoolExecutor(max_workers=workers) as pool:
        nested = list(
            pool.map(
                _safe_run_chunk,
                [source_path] * len(task_chunks),
                task_chunks,
            )
        )
    flattened = [item for group in nested for item in group]
    return flattened, len(task_chunks)
"""


def validate_parallel_impl(code: str) -> dict[str, Any]:
    try:
        tree = ast.parse(code, filename="<generated_parallel_impl>")
    except SyntaxError as exc:
        raise GeneratedCodeSafetyError(f"syntax_error: {exc}") from exc

    functions: dict[str, ast.FunctionDef] = {}
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            raise GeneratedCodeSafetyError(
                "Only top-level function definitions are allowed."
            )
        if node.name not in EXPECTED_SIGNATURES:
            raise GeneratedCodeSafetyError(
                f"Unexpected top-level function: {node.name}"
            )
        if node.name in functions:
            raise GeneratedCodeSafetyError(
                f"Duplicate function definition: {node.name}"
            )
        functions[node.name] = node

    missing = set(EXPECTED_SIGNATURES) - set(functions)
    if missing:
        raise GeneratedCodeSafetyError(
            f"Missing required functions: {sorted(missing)}"
        )
    for name, expected_args in EXPECTED_SIGNATURES.items():
        function = functions[name]
        actual_args = [argument.arg for argument in function.args.args]
        if (
            actual_args != expected_args
            or function.args.vararg
            or function.args.kwarg
            or function.args.kwonlyargs
        ):
            raise GeneratedCodeSafetyError(
                f"Invalid signature for {name}: {actual_args}"
            )

    used_name_calls: set[str] = set()
    used_attribute_calls: set[str] = set()
    used_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, BANNED_NODES):
            raise GeneratedCodeSafetyError(
                f"Banned syntax node: {type(node).__name__}"
            )
        if isinstance(node, ast.Name) and node.id in BANNED_NAMES:
            raise GeneratedCodeSafetyError(f"Banned name: {node.id}")
        if isinstance(node, ast.Name):
            used_names.add(node.id)
        if isinstance(node, ast.Attribute):
            if node.attr.startswith("__") or node.attr in BANNED_ATTRIBUTES:
                raise GeneratedCodeSafetyError(
                    f"Banned attribute: {node.attr}"
                )
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                called = node.func.id
                used_name_calls.add(called)
                if called not in ALLOWED_NAME_CALLS:
                    raise GeneratedCodeSafetyError(
                        f"Call is not allowlisted: {called}"
                    )
            elif isinstance(node.func, ast.Attribute):
                called = node.func.attr
                used_attribute_calls.add(called)
                if called not in ALLOWED_ATTRIBUTE_CALLS:
                    raise GeneratedCodeSafetyError(
                        f"Method call is not allowlisted: {called}"
                    )
            else:
                raise GeneratedCodeSafetyError(
                    "Dynamic or indirect calls are not allowed."
                )

    if "ProcessPoolExecutor" not in used_name_calls:
        raise GeneratedCodeSafetyError(
            "execute_parallel must use ProcessPoolExecutor."
        )
    if "_safe_run_chunk" not in used_names:
        raise GeneratedCodeSafetyError(
            "execute_parallel must submit the safe worker helper."
        )
    return {
        "safe": True,
        "functions": sorted(functions),
        "name_calls": sorted(used_name_calls),
        "attribute_calls": sorted(used_attribute_calls),
    }


_CONTROLLED_CANDIDATE = '''\
from __future__ import annotations

import argparse
import importlib.util
import json
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

DEFAULT_SOURCE = __SOURCE_PATH__
DEFAULT_WORKERS = __WORKERS__
DEFAULT_CHUNKS = __CHUNKS__


def _load_source(path: str):
    file_path = Path(path).resolve()
    spec = importlib.util.spec_from_file_location(
        "controlled_candidate_source", file_path
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load source: {file_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _safe_run_chunk(source_path: str, chunk):
    module = _load_source(source_path)
    return [module.unit(item) for item in chunk]


__IMPL_CODE__


def _normalize(value: Any):
    if hasattr(value, "tolist"):
        return value.tolist()
    if isinstance(value, dict):
        return {str(key): _normalize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def execute(mode, source_path, size, seed, workers, chunks):
    module = _load_source(source_path)
    items = module.make_input(size, seed)
    started = time.perf_counter()
    if mode == "serial":
        values = [module.unit(item) for item in items]
        task_count = 1
    else:
        values, task_count = execute_parallel(
            source_path, items, workers, chunks
        )
    result = module.combine(values)
    return {
        "mode": mode,
        "result": _normalize(result),
        "runtime_seconds": time.perf_counter() - started,
        "task_count": task_count,
    }


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


def generate_controlled_candidate(
    plan: ParallelPlan,
    impl_code: str,
    output_path: str | Path,
) -> tuple[Path, dict[str, Any]]:
    plan.validate()
    if not plan.parallelizable:
        raise ValueError("Cannot generate a candidate for a serial plan")
    safety_report = validate_parallel_impl(impl_code)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    candidate = (
        _CONTROLLED_CANDIDATE.replace(
            "__SOURCE_PATH__", repr(plan.source_path)
        )
        .replace("__WORKERS__", str(plan.workers))
        .replace("__CHUNKS__", str(plan.chunks))
        .replace("__IMPL_CODE__", impl_code.strip())
    )
    output.write_text(candidate, encoding="utf-8")
    return output, safety_report
