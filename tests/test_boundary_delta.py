from __future__ import annotations

from pathlib import Path

import pytest

from parallel_agent.boundary_delta import (
    BoundaryDeltaError,
    BoundaryDeltaFiles,
    apply_projection_boundary_delta,
    discover_projection_boundary,
    validate_plan,
)


FILES = BoundaryDeltaFiles(
    caller_path="sklearn/compose/_column_transformer.py",
    caller_function="_call_func_on_transformers",
    worker_path="sklearn/pipeline.py",
    worker_functions=("_transform_one", "_fit_transform_one"),
)


def _fixture(root: Path) -> None:
    caller = root / FILES.caller_path
    worker = root / FILES.worker_path
    caller.parent.mkdir(parents=True)
    worker.parent.mkdir(parents=True, exist_ok=True)
    caller.write_bytes((
        "from ..utils._indexing import _determine_key_type, _get_column_indices\n\n"
        "class Demo:\n"
        "    def _call_func_on_transformers(self, X, y, func, transformers):\n"
        "        jobs = []\n"
        "        for name, trans, columns, weight in transformers:\n"
        "            jobs.append(\n"
        "                delayed(func)(\n"
        "                        transformer=trans,\n"
        "                        X=X,\n"
        "                        y=y,\n"
        "                        weight=weight,\n"
        "                        columns=columns,\n"
        "                        params={},\n"
        "                )\n"
        "            )\n"
        "        return Parallel(n_jobs=self.n_jobs)(jobs)\n"
    ).encode("utf-8"))
    worker.write_bytes((
        "from .utils import Bunch, _safe_indexing\n\n"
        "def _transform_one(transformer, X, y, weight, columns=None, params=None):\n"
        "    \"\"\"Transform.\n\n"
        "    columns : str, array-like of str, int, array-like of int, array-like of bool, slice\n"
        "        Columns to select before transforming.\n\n"
        "    \"\"\"\n"
        "    if columns is not None:\n"
        "        X = _safe_indexing(X, columns, axis=1)\n\n"
        "    return transformer.transform(X)\n\n"
        "def _fit_transform_one(\n"
        "    transformer,\n"
        "    X,\n"
        "    y,\n"
        "    weight,\n"
        "    columns=None,\n"
        "    message_clsname=\"\",\n"
        "    message=None,\n"
        "    params=None,\n"
        "):\n"
        "    if columns is not None:\n"
        "        X = _safe_indexing(X, columns, axis=1)\n\n"
        "    return transformer.fit_transform(X, y)\n"
    ).encode("utf-8"))


def _plan() -> dict[str, object]:
    return {
        "pattern": "hoist_projection_before_dispatch",
        "caller_function": "_call_func_on_transformers",
        "payload_argument": "X",
        "selector_argument": "columns",
        "projection_function": "_safe_indexing",
        "worker_functions": ["_transform_one", "_fit_transform_one"],
        "remove_selector_from_workers": True,
        "preserve_scheduler_policy": True,
    }


def test_discovery_and_atomic_delta_preserve_scheduler_policy(tmp_path: Path) -> None:
    _fixture(tmp_path)
    evidence = discover_projection_boundary(tmp_path, FILES)
    validate_plan(_plan(), evidence)

    result = apply_projection_boundary_delta(tmp_path, evidence)

    assert result["invariant_report"]["status"] == "passed"
    caller = (tmp_path / FILES.caller_path).read_text(encoding="utf-8")
    worker = (tmp_path / FILES.worker_path).read_text(encoding="utf-8")
    assert "X=_safe_indexing(X, columns, axis=1)" in caller
    assert "columns=columns" not in caller
    assert "Parallel(n_jobs=self.n_jobs)(jobs)" in caller
    assert "backend=" not in caller
    assert "columns=None" not in worker


def test_plan_must_name_every_worker(tmp_path: Path) -> None:
    _fixture(tmp_path)
    evidence = discover_projection_boundary(tmp_path, FILES)
    plan = _plan()
    plan["worker_functions"] = ["_transform_one"]

    with pytest.raises(BoundaryDeltaError, match="every discovered Worker"):
        validate_plan(plan, evidence)
