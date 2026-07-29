import importlib.util
from pathlib import Path

import pytest

from parallel_agent.loop_frontend import (
    LoopNormalizationError,
    analyze_serial_loop,
    load_verified_normalization,
    normalize_serial_loop,
)
from parallel_agent.runner import load_workload


ROOT = Path(__file__).resolve().parents[1]


def _load_module(path: Path):
    spec = importlib.util.spec_from_file_location("serial_example", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_normalize_serial_loop_preserves_result(tmp_path: Path) -> None:
    source = ROOT / "examples/simple_serial_loop.py"
    output = tmp_path / "normalized_workload.py"
    normalization = normalize_serial_loop(
        source,
        output_path=output,
        entry_function="run_serial",
    )
    assert normalization.unit_function == "process_interval"
    assert normalization.combine_function == "aggregate_counts"
    assert output.exists()
    assert output.with_suffix(".normalization.json").exists()
    verified = load_verified_normalization(output)
    assert verified is not None
    assert verified.output_sha256 == normalization.output_sha256

    original = _load_module(source)
    workload = load_workload(output)
    items = workload.make_input(2, 42)
    expected = original.run_serial(items)
    actual = workload.combine([workload.unit(item) for item in items])
    assert workload.equivalent(expected, actual)


def test_serial_loop_is_auto_detected() -> None:
    analysis = analyze_serial_loop(
        ROOT / "examples/simple_serial_loop.py"
    )
    assert analysis.entry_function == "run_serial"
    assert analysis.parallel_pattern == "independent_map_then_combine"


def test_modified_wrapper_is_rejected(tmp_path: Path) -> None:
    output = tmp_path / "normalized_workload.py"
    normalize_serial_loop(
        ROOT / "examples/simple_serial_loop.py",
        output_path=output,
    )
    output.write_text(
        output.read_text(encoding="utf-8") + "\n# modified\n",
        encoding="utf-8",
    )
    with pytest.raises(
        LoopNormalizationError,
        match="wrapper changed",
    ):
        load_verified_normalization(output)


def test_loop_carried_reduction_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "dependent.py"
    source.write_text(
        """
def make_input(size, seed):
    return list(range(size))

def equivalent(left, right):
    return left == right

def run_serial(items):
    total = 0
    for item in items:
        total += item
    return total
""".strip(),
        encoding="utf-8",
    )
    with pytest.raises(
        LoopNormalizationError,
        match="outside the supported",
    ):
        analyze_serial_loop(source, entry_function="run_serial")


def test_global_worker_state_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "global_state.py"
    source.write_text(
        """
COUNTER = 0

def make_input(size, seed):
    return list(range(size))

def process(item):
    global COUNTER
    COUNTER += 1
    return item

def aggregate(values):
    return sum(values)

def equivalent(left, right):
    return left == right

def run_serial(items):
    results = []
    for item in items:
        results.append(process(item))
    return aggregate(results)
""".strip(),
        encoding="utf-8",
    )
    with pytest.raises(
        LoopNormalizationError,
        match="global/nonlocal",
    ):
        analyze_serial_loop(source, entry_function="run_serial")
