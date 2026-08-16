"""Measured evidence about values and work crossing a parallel Worker boundary."""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
import hashlib
import pickle
import statistics
import time
from collections.abc import Callable, Iterable, Sequence
from typing import Any


def _update_output_digest(digest: Any, value: Any) -> None:
    """Hash common scientific values by content instead of pickle metadata."""
    try:
        import numpy as np
    except ImportError:  # pragma: no cover - NumPy is an optional convenience
        np = None  # type: ignore[assignment]
    if np is not None and isinstance(value, np.ndarray):
        digest.update(b"ndarray")
        digest.update(value.dtype.str.encode("ascii"))
        digest.update(repr(value.shape).encode("ascii"))
        if value.dtype.hasobject:
            _update_output_digest(digest, value.tolist())
        else:
            digest.update(np.ascontiguousarray(value).tobytes())
        return
    if np is not None and isinstance(value, np.generic):
        _update_output_digest(digest, value.item())
        return
    if isinstance(value, dict):
        digest.update(b"dict")
        for key in sorted(value, key=repr):
            _update_output_digest(digest, key)
            _update_output_digest(digest, value[key])
        return
    if isinstance(value, (list, tuple)):
        digest.update(type(value).__name__.encode("ascii"))
        digest.update(str(len(value)).encode("ascii"))
        for item in value:
            _update_output_digest(digest, item)
        return
    if isinstance(value, (str, bytes, int, float, bool, type(None))):
        digest.update(type(value).__name__.encode("ascii"))
        digest.update(repr(value).encode("utf-8"))
        return
    digest.update(b"pickle-fallback")
    digest.update(pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL))


def _hash_outputs(outputs: Sequence[Any]) -> str:
    digest = hashlib.sha256()
    _update_output_digest(digest, tuple(outputs))
    return digest.hexdigest()


def probe_serialization(value: Any, *, repeats: int = 3) -> dict[str, Any]:
    """Measure whether a representative value can cross a process boundary."""
    if repeats < 1:
        raise ValueError("repeats must be at least one")
    timings: list[float] = []
    payload_size: int | None = None
    try:
        for _ in range(repeats):
            started = time.perf_counter()
            payload = pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)
            timings.append(time.perf_counter() - started)
            payload_size = len(payload)
    except Exception as exc:  # noqa: BLE001 - evidence must retain the real error
        return {
            "picklable": False,
            "type": f"{type(value).__module__}.{type(value).__qualname__}",
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
    return {
        "picklable": True,
        "type": f"{type(value).__module__}.{type(value).__qualname__}",
        "bytes": payload_size,
        "serialization_median_seconds": statistics.median(timings),
        "serialization_timings_seconds": timings,
    }


def probe_payload_plan(
    payloads: Iterable[Any], *, repeats: int = 3
) -> dict[str, Any]:
    """Measure the sum of representative payloads in one dispatch plan."""
    measurements = [
        probe_serialization(payload, repeats=repeats) for payload in payloads
    ]
    picklable = all(item["picklable"] for item in measurements)
    result: dict[str, Any] = {
        "payload_count": len(measurements),
        "picklable": picklable,
        "payloads": measurements,
    }
    if picklable:
        result["total_bytes"] = sum(int(item["bytes"]) for item in measurements)
        result["largest_payload_bytes"] = max(
            (int(item["bytes"]) for item in measurements), default=0
        )
        result["total_serialization_median_seconds"] = sum(
            float(item["serialization_median_seconds"])
            for item in measurements
        )
    return result


def _time_serial(worker: Callable[[Any], Any], items: Sequence[Any]) -> tuple[float, list[Any]]:
    started = time.perf_counter()
    outputs = [worker(item) for item in items]
    return time.perf_counter() - started, outputs


def _time_executor(
    executor_type: type[ThreadPoolExecutor] | type[ProcessPoolExecutor],
    worker: Callable[[Any], Any],
    items: Sequence[Any],
    workers: int,
) -> tuple[float, list[Any]]:
    started = time.perf_counter()
    with executor_type(max_workers=workers) as executor:
        outputs = list(executor.map(worker, items))
    return time.perf_counter() - started, outputs


def probe_backends(
    worker: Callable[[Any], Any],
    items: Sequence[Any],
    *,
    workers: int,
    repeats: int = 3,
    include_process: bool = True,
) -> dict[str, Any]:
    """Compare serial, thread and process execution on representative tasks."""
    if not items:
        raise ValueError("items must not be empty")
    if workers < 1 or repeats < 1:
        raise ValueError("workers and repeats must be at least one")
    runners: list[
        tuple[str, Callable[[], tuple[float, list[Any]]]]
    ] = [
        ("serial", lambda: _time_serial(worker, items)),
        (
            "thread",
            lambda: _time_executor(ThreadPoolExecutor, worker, items, workers),
        ),
    ]
    if include_process:
        runners.append(
            (
                "process",
                lambda: _time_executor(ProcessPoolExecutor, worker, items, workers),
            )
        )

    results: dict[str, dict[str, Any]] = {}
    for name, runner in runners:
        timings: list[float] = []
        hashes: list[str] = []
        try:
            for _ in range(repeats):
                elapsed, outputs = runner()
                timings.append(elapsed)
                hashes.append(_hash_outputs(outputs))
            results[name] = {
                "ok": True,
                "timings_seconds": timings,
                "median_seconds": statistics.median(timings),
                "output_hashes": hashes,
                "stable_output": len(set(hashes)) == 1,
            }
        except Exception as exc:  # noqa: BLE001 - retain backend failure as evidence
            results[name] = {
                "ok": False,
                "error_type": type(exc).__name__,
                "error": str(exc),
            }

    serial = results["serial"]
    if serial["ok"]:
        serial_hash = serial["output_hashes"][0]
        serial_seconds = float(serial["median_seconds"])
        for result in results.values():
            if result["ok"]:
                result["output_matches_serial"] = bool(
                    result["stable_output"]
                    and result["output_hashes"][0] == serial_hash
                )
                result["speedup_over_serial"] = (
                    serial_seconds / float(result["median_seconds"])
                )
    return {
        "workers": workers,
        "task_count": len(items),
        "repeats": repeats,
        "backends": results,
    }
