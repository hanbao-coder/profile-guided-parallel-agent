"""Discover and apply a verified data-projection boundary migration.

The supported pattern is deliberately narrow: a parallel caller sends a full
payload plus a selector to Worker helpers, and each Worker projects the payload
locally.  The transformation hoists that projection to the caller while keeping
the scheduler/backend expression unchanged.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Any


class BoundaryDeltaError(RuntimeError):
    """Raised when discovery, a plan, or a transformed source violates the pattern."""


@dataclass(frozen=True)
class BoundaryDeltaFiles:
    caller_path: str
    caller_function: str
    worker_path: str
    worker_functions: tuple[str, ...]


def _read(path: Path) -> str:
    return path.read_bytes().decode("utf-8")


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _function(tree: ast.AST, name: str) -> ast.FunctionDef:
    matches = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    if len(matches) != 1:
        raise BoundaryDeltaError(f"expected one function {name!r}, found {len(matches)}")
    return matches[0]


def _name(node: ast.AST | None) -> str | None:
    return node.id if isinstance(node, ast.Name) else None


def _call_name(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _call_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return None


def _delayed_calls(function: ast.FunctionDef) -> list[ast.Call]:
    return [
        node
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Call)
        and _call_name(node.func.func) == "delayed"
    ]


def _parallel_calls(function: ast.FunctionDef) -> list[ast.Call]:
    return [
        node
        for node in ast.walk(function)
        if isinstance(node, ast.Call) and _call_name(node.func) == "Parallel"
    ]


def _projection_if(function: ast.FunctionDef) -> ast.If:
    candidates: list[ast.If] = []
    for node in ast.walk(function):
        if not isinstance(node, ast.If):
            continue
        calls = [
            child
            for child in ast.walk(node)
            if isinstance(child, ast.Call) and _call_name(child.func) == "_safe_indexing"
        ]
        if calls:
            candidates.append(node)
    if len(candidates) != 1:
        raise BoundaryDeltaError(
            f"expected one guarded _safe_indexing block in {function.name}, "
            f"found {len(candidates)}"
        )
    return candidates[0]


def discover_projection_boundary(
    root: Path,
    files: BoundaryDeltaFiles,
) -> dict[str, Any]:
    """Extract a relational caller/Worker boundary from unmodified source."""
    caller_file = root / files.caller_path
    worker_file = root / files.worker_path
    caller_source = _read(caller_file)
    worker_source = _read(worker_file)
    caller_tree = ast.parse(caller_source, filename=str(caller_file))
    worker_tree = ast.parse(worker_source, filename=str(worker_file))
    caller = _function(caller_tree, files.caller_function)
    delayed = _delayed_calls(caller)
    if len(delayed) != 1:
        raise BoundaryDeltaError(
            f"expected one delayed dispatch call, found {len(delayed)}"
        )
    delayed_call = delayed[0]
    keywords = {item.arg: item.value for item in delayed_call.keywords if item.arg}
    if _name(keywords.get("X")) != "X" or _name(keywords.get("columns")) != "columns":
        raise BoundaryDeltaError(
            "registered caller does not send X and columns across the Worker boundary"
        )

    scheduler_calls = _parallel_calls(caller)
    if len(scheduler_calls) != 1:
        raise BoundaryDeltaError(
            f"expected one Parallel scheduler call, found {len(scheduler_calls)}"
        )
    scheduler = scheduler_calls[0]
    scheduler_keywords = {
        item.arg: ast.unparse(item.value) for item in scheduler.keywords if item.arg
    }

    workers: list[dict[str, Any]] = []
    for worker_name in files.worker_functions:
        function = _function(worker_tree, worker_name)
        arguments = [argument.arg for argument in function.args.args]
        if "columns" not in arguments:
            raise BoundaryDeltaError(f"{worker_name} has no columns parameter")
        projection = _projection_if(function)
        workers.append(
            {
                "function": worker_name,
                "parameters": arguments,
                "projection_block": {
                    "start": projection.lineno,
                    "end": projection.end_lineno,
                    "operation": "X = _safe_indexing(X, columns, axis=1)",
                },
            }
        )

    return {
        "schema_version": 1,
        "pattern": "hoist_projection_before_dispatch",
        "source_evidence": {
            "caller_file_sha256": _sha(caller_source),
            "worker_file_sha256": _sha(worker_source),
        },
        "caller": {
            "path": files.caller_path,
            "function": files.caller_function,
            "delayed_call_range": {
                "start": delayed_call.lineno,
                "end": delayed_call.end_lineno,
            },
            "payload_argument": "X",
            "payload_before": "X",
            "selector_argument": "columns",
            "projection_function": "_safe_indexing",
            "scheduler": {
                "call": "Parallel",
                "keywords": scheduler_keywords,
                "source": ast.unparse(scheduler),
                "must_remain_backend_agnostic": True,
            },
        },
        "workers": workers,
        "required_atomic_delta": [
            "Project X with columns at the delayed-call site before dispatch.",
            "Remove columns from the delayed Worker call.",
            "Remove columns from every registered Worker signature.",
            "Remove the now-redundant Worker-side projection blocks.",
            "Keep the Parallel scheduler call backend-agnostic and preserve ordering.",
        ],
        "files": {
            "caller_path": files.caller_path,
            "caller_function": files.caller_function,
            "worker_path": files.worker_path,
            "worker_functions": list(files.worker_functions),
        },
    }


def validate_plan(plan: dict[str, Any], evidence: dict[str, Any]) -> None:
    """Require the Agent plan to name every side of the relational delta."""
    expected = {
        "pattern": evidence["pattern"],
        "caller_function": evidence["caller"]["function"],
        "payload_argument": evidence["caller"]["payload_argument"],
        "selector_argument": evidence["caller"]["selector_argument"],
        "projection_function": evidence["caller"]["projection_function"],
    }
    for key, value in expected.items():
        if plan.get(key) != value:
            raise BoundaryDeltaError(
                f"plan field {key!r} must equal discovered evidence {value!r}"
            )
    expected_workers = {
        worker["function"] for worker in evidence.get("workers", [])
    }
    if set(plan.get("worker_functions", [])) != expected_workers:
        raise BoundaryDeltaError(
            "plan must update every discovered Worker function atomically"
        )
    if plan.get("remove_selector_from_workers") is not True:
        raise BoundaryDeltaError("plan must remove the migrated selector from Workers")
    if plan.get("preserve_scheduler_policy") is not True:
        raise BoundaryDeltaError("plan must preserve caller-selected scheduler policy")


def _replace_once(source: str, old: str, new: str, *, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise BoundaryDeltaError(f"{label}: expected one guarded source match, found {count}")
    return source.replace(old, new, 1)


def _replace_first_of(
    source: str,
    old: str,
    new: str,
    *,
    expected_count: int,
    label: str,
) -> str:
    count = source.count(old)
    if count != expected_count:
        raise BoundaryDeltaError(
            f"{label}: expected {expected_count} guarded matches, found {count}"
        )
    return source.replace(old, new, 1)


def apply_projection_boundary_delta(
    root: Path,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    """Apply the validated pattern as guarded, atomic paired edits."""
    files = evidence["files"]
    caller_path = root / str(files["caller_path"])
    worker_path = root / str(files["worker_path"])
    caller_before = _read(caller_path)
    worker_before = _read(worker_path)

    caller_after = _replace_once(
        caller_before,
        "from ..utils._indexing import _determine_key_type, _get_column_indices",
        "from ..utils._indexing import _determine_key_type, _get_column_indices, _safe_indexing",
        label="caller import",
    )
    caller_after = _replace_once(
        caller_after,
        "                        X=X,\n",
        "                        X=_safe_indexing(X, columns, axis=1),\n",
        label="caller payload projection",
    )
    caller_after = _replace_once(
        caller_after,
        "                        columns=columns,\n",
        "",
        label="caller selector removal",
    )

    worker_after = _replace_once(
        worker_before,
        "from .utils import Bunch, _safe_indexing",
        "from .utils import Bunch",
        label="worker import",
    )
    worker_after = _replace_once(
        worker_after,
        "def _transform_one(transformer, X, y, weight, columns=None, params=None):",
        "def _transform_one(transformer, X, y, weight, params=None):",
        label="transform Worker signature",
    )
    worker_after = _replace_once(
        worker_after,
        "    columns : str, array-like of str, int, array-like of int, array-like of bool, slice\n"
        "        Columns to select before transforming.\n\n",
        "",
        label="transform Worker selector docs",
    )
    projection_block = (
        "    if columns is not None:\n"
        "        X = _safe_indexing(X, columns, axis=1)\n\n"
    )
    worker_after = _replace_first_of(
        worker_after,
        projection_block,
        "",
        expected_count=2,
        label="transform Worker projection",
    )
    worker_after = _replace_once(
        worker_after,
        "def _fit_transform_one(\n"
        "    transformer,\n"
        "    X,\n"
        "    y,\n"
        "    weight,\n"
        "    columns=None,\n"
        "    message_clsname=\"\",\n"
        "    message=None,\n"
        "    params=None,\n"
        "):",
        "def _fit_transform_one(\n"
        "    transformer, X, y, weight, message_clsname=\"\", message=None, params=None\n"
        "):",
        label="fit-transform Worker signature",
    )
    worker_after = _replace_once(
        worker_after,
        projection_block,
        "",
        label="fit-transform Worker projection",
    )

    caller_path.write_bytes(caller_after.encode("utf-8"))
    worker_path.write_bytes(worker_after.encode("utf-8"))
    report = validate_transformed_boundary(root, evidence)
    return {
        "files": [str(files["caller_path"]), str(files["worker_path"])],
        "before_sha256": {
            str(files["caller_path"]): _sha(caller_before),
            str(files["worker_path"]): _sha(worker_before),
        },
        "after_sha256": {
            str(files["caller_path"]): _sha(caller_after),
            str(files["worker_path"]): _sha(worker_after),
        },
        "invariant_report": report,
    }


def validate_transformed_boundary(
    root: Path,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    """Check the caller/Worker relation and execution-policy invariants."""
    files = evidence["files"]
    caller_tree = ast.parse(_read(root / str(files["caller_path"])))
    worker_tree = ast.parse(_read(root / str(files["worker_path"])))
    caller = _function(caller_tree, str(files["caller_function"]))
    delayed = _delayed_calls(caller)
    findings: list[str] = []
    if len(delayed) != 1:
        findings.append("expected exactly one delayed Worker call after migration")
    else:
        keywords = {item.arg: item.value for item in delayed[0].keywords if item.arg}
        payload = keywords.get("X")
        if not (
            isinstance(payload, ast.Call)
            and _call_name(payload.func) == "_safe_indexing"
            and len(payload.args) >= 2
            and _name(payload.args[0]) == "X"
            and _name(payload.args[1]) == "columns"
        ):
            findings.append("caller does not project X by columns before dispatch")
        if "columns" in keywords:
            findings.append("caller still sends the columns selector to the Worker")

    schedulers = _parallel_calls(caller)
    if len(schedulers) != 1:
        findings.append("Parallel scheduler call was removed or duplicated")
    else:
        forbidden = {
            item.arg for item in schedulers[0].keywords
            if item.arg in {"backend", "prefer", "require"}
        }
        if forbidden:
            findings.append(
                "candidate hard-codes scheduler policy: " + ", ".join(sorted(forbidden))
            )
        keyword_map = {
            item.arg: ast.unparse(item.value)
            for item in schedulers[0].keywords
            if item.arg
        }
        if keyword_map.get("n_jobs") != "self.n_jobs":
            findings.append("candidate changed the existing n_jobs control")

    for worker_name in files["worker_functions"]:
        function = _function(worker_tree, str(worker_name))
        if "columns" in {argument.arg for argument in function.args.args}:
            findings.append(f"{worker_name} still accepts columns")
        if any(
            isinstance(node, ast.Call) and _call_name(node.func) == "_safe_indexing"
            for node in ast.walk(function)
        ):
            findings.append(f"{worker_name} still projects inside the Worker")

    return {
        "status": "passed" if not findings else "failed",
        "findings": findings,
        "checked_invariants": [
            "payload projected once before delayed dispatch",
            "selector removed from caller and all Workers",
            "Parallel backend policy remains caller-controlled",
            "n_jobs and result ordering remain unchanged",
        ],
    }
