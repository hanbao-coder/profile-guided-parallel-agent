from __future__ import annotations

from pathlib import Path

from parallel_agent.configuration_search import (
    configuration_grid,
    run_configuration_search,
    select_configuration,
)


ROOT = Path(__file__).resolve().parents[1]


def test_configuration_grid_is_ordered_and_unique() -> None:
    grid = configuration_grid(
        max_workers=4,
        chunk_multipliers=(1, 2),
    )

    assert [(item.workers, item.chunks) for item in grid] == [
        (1, 1),
        (1, 2),
        (2, 2),
        (2, 4),
        (4, 4),
        (4, 8),
    ]


def test_configuration_selector_requires_conservative_gain() -> None:
    rows = {
        "serial": {
            "valid": True,
            "speedup": 1.0,
            "conservative_speedup": 1.0,
            "median_seconds": 1.0,
        },
        "w2_c2": {
            "valid": True,
            "speedup": 1.20,
            "conservative_speedup": 0.98,
            "median_seconds": 0.83,
            "workers": 2,
            "chunks": 2,
        },
        "w4_c4": {
            "valid": True,
            "speedup": 1.10,
            "conservative_speedup": 1.06,
            "median_seconds": 0.91,
            "workers": 4,
            "chunks": 4,
        },
    }

    assert (
        select_configuration(rows, minimum_speedup=1.05)
        == "w4_c4"
    )

    rows["w4_c4"]["conservative_speedup"] = 1.04
    assert select_configuration(
        rows, minimum_speedup=1.05
    ) == "serial"


def test_configuration_search_separates_tuning_and_holdout(
    tmp_path: Path,
) -> None:
    report = run_configuration_search(
        ROOT / "benchmarks/prime_count/workload.py",
        output_dir=tmp_path,
        size=2,
        tuning_size=1,
        seed=42,
        max_workers=2,
        chunk_multipliers=(1, 2),
        tuning_repeats=1,
        confirmation_repeats=1,
        holdout_repeats=1,
        warmups=0,
        timeout_seconds=30,
        minimum_speedup=1.01,
        order_seed=123,
    )

    assert report["status"] == "completed"
    assert report["tuning_size"] == 1
    assert "preliminary_selected_label" in report["selection"]
    assert report["tuning"]["runs"]
    assert report["holdout"]["runs"]
    assert report["tuning"]["runs"] != report["holdout"]["runs"]
    assert report["selection"]["selected_label"] in {
        "serial",
        "w1_c1",
        "w1_c2",
        "w2_c2",
        "w2_c4",
    }
    assert (
        tmp_path / "configuration_search_report.json"
    ).exists()
