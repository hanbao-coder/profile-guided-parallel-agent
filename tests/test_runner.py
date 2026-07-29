from pathlib import Path

from parallel_agent.runner import (
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
    paths = [
        ROOT / "benchmarks/prime_count/workload.py",
        ROOT / "benchmarks/mandelbrot/workload.py",
        ROOT / "benchmarks/tiny_tasks/workload.py",
        ROOT / "benchmarks/word_count/workload.py",
        ROOT / "benchmarks/monte_carlo/workload.py",
        ROOT / "benchmarks/pairwise_distance/workload.py",
    ]
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
    assert report["summary"]["serial"]["runtime_iqr_seconds"] == 0.0
    assert report["environment"]["cpu_logical"] >= 1


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
