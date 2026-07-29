from pathlib import Path

import pytest
import yaml

from parallel_agent.runner import (
    _pilot_item_profile,
    benchmark,
    load_workload,
    ray_temp_directory,
    run_once,
)


ROOT = Path(__file__).resolve().parents[1]


def test_load_prime_workload() -> None:
    workload = load_workload(ROOT / "benchmarks/prime_count/workload.py")
    items = workload.make_input(2, 42)
    assert workload.combine([workload.unit(item) for item in items]) > 0


def test_all_runnable_workloads_satisfy_contract() -> None:
    config = yaml.safe_load(
        (ROOT / "configs/benchmarks.yaml").read_text(encoding="utf-8")
    )
    paths = [
        ROOT / entry["path"]
        for entry in config["benchmarks"].values()
    ]
    assert len(paths) == 8
    for path in paths:
        workload = load_workload(path)
        items = workload.make_input(2, 42)
        result = workload.combine([workload.unit(item) for item in items])
        assert workload.equivalent(result, result)


def test_serial_benchmark(tmp_path: Path) -> None:
    report = benchmark(
        ROOT / "benchmarks/prime_count/workload.py",
        size=2,
        workers=2,
        modes=["serial"],
        repeats=1,
        warmups=0,
        seed=42,
        output=tmp_path / "result.json",
        backend="multiprocessing",
    )
    assert report["summary"]["serial"]["correct"]
    assert report["summary"]["serial"]["speedup"] == 1.0
    assert report["summary"]["serial"]["total_speedup"] == 1.0
    assert report["summary"]["serial"]["parallel_overhead_ratio"] == 0.0
    assert report["summary"]["serial"]["runtime_iqr_seconds"] == 0.0
    assert report["environment"]["cpu_logical"] >= 1


def test_parallel_summary_reports_standard_overhead_metrics(
    tmp_path: Path,
) -> None:
    report = benchmark(
        ROOT / "benchmarks/prime_count/workload.py",
        size=2,
        workers=2,
        modes=["serial", "naive"],
        repeats=1,
        warmups=0,
        seed=42,
        output=tmp_path / "result.json",
        backend="multiprocessing",
    )
    serial = report["summary"]["serial"]["runtime_median_seconds"]
    naive = report["summary"]["naive"]
    expected = naive["workers"] * naive["runtime_median_seconds"] - serial
    assert naive["parallel_overhead_core_seconds"] == pytest.approx(expected)
    assert naive["parallel_overhead_ratio"] == pytest.approx(expected / serial)
    assert "first_use_parallel_overhead_ratio" in naive


def test_benchmark_order_is_reproducibly_randomized(tmp_path: Path) -> None:
    kwargs = dict(
        workload_path=ROOT / "benchmarks/prime_count/workload.py",
        size=1,
        workers=1,
        modes=["serial", "optimized"],
        repeats=3,
        warmups=0,
        seed=42,
        backend="multiprocessing",
    )
    first = benchmark(output=tmp_path / "first.json", **kwargs)
    second = benchmark(output=tmp_path / "second.json", **kwargs)
    assert first["execution_order"] == second["execution_order"]
    assert sorted(first["execution_order"]) == [
        "optimized",
        "optimized",
        "optimized",
        "serial",
        "serial",
        "serial",
    ]


def test_ray_temp_directory_leaves_room_for_unix_socket_suffix() -> None:
    ray_temp = ray_temp_directory()
    representative_socket = (
        ray_temp
        / "session_2026-07-29_14-43-37_420070_2377"
        / "sockets"
        / "plasma_store"
    )
    assert ray_temp.is_absolute()
    assert len(str(representative_socket).encode("utf-8")) < 107


def test_benefit_gate_falls_back_for_large_startup_cost() -> None:
    workload = load_workload(ROOT / "benchmarks/tiny_tasks/workload.py")
    items = workload.make_input(10, 42)
    golden = workload.combine([workload.unit(item) for item in items])
    metric, result = run_once(
        workload,
        items,
        mode="optimized",
        workers=4,
        golden=golden,
        backend="multiprocessing",
        backend_startup_seconds=10.0,
    )
    assert metric.selected_mode == "serial_fallback"
    assert metric.task_count == 1
    assert workload.equivalent(golden, result)


def test_stratified_pilot_detects_load_imbalance() -> None:
    workload = load_workload(ROOT / "benchmarks/load_imbalance/workload.py")
    mean, coefficient_of_variation, samples = _pilot_item_profile(
        workload, workload.make_input(16, 42)
    )
    assert samples == 16
    assert mean > 0
    assert coefficient_of_variation > 0.5
