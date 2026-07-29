from __future__ import annotations

import csv
import json
from pathlib import Path

from parallel_agent.ray_formal_summary import summarize_ray_formal_runs


def _write_fixture_run(path: Path, speed: float) -> None:
    path.mkdir(parents=True)
    rows = []
    for benchmark in ("a", "b"):
        for mode, warm_speedup, task_count in (
            ("serial", 1.0, 1),
            ("naive", speed, 8),
            ("optimized", speed + 0.2, 4),
        ):
            rows.append(
                {
                    "benchmark": benchmark,
                    "mode": mode,
                    "selected_mode": mode,
                    "warm_runtime_seconds": 1.0 / warm_speedup,
                    "warm_speedup": warm_speedup,
                    "first_use_speedup": 0.2 if mode != "serial" else 1.0,
                    "task_count": task_count,
                    "workers": 1 if mode == "serial" else 4,
                    "cpu_mean_percent": 100.0,
                    "serialization_to_runtime_ratio": 0.01,
                    "correct": True,
                }
            )
    with (path / "suite_large.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (path / "suite_large_manifest.json").write_text(
        json.dumps({"repeats": 5}), encoding="utf-8"
    )
    for benchmark in ("a", "b"):
        report = {
            "workers": 4,
            "backend_startup_seconds": 3.0,
            "calibrations": {
                "4": {
                    "workers": 4,
                    "startup_seconds": 0.0,
                    "task_overhead_seconds": 0.0004,
                }
            },
        }
        (path / f"{benchmark}_large.json").write_text(
            json.dumps(report), encoding="utf-8"
        )


def test_summarize_ray_formal_runs(tmp_path: Path) -> None:
    source = tmp_path / "raw"
    _write_fixture_run(source / "run_01", 1.1)
    _write_fixture_run(source / "run_02", 1.2)
    result = summarize_ray_formal_runs(
        source,
        tmp_path / "summary",
        expected_runs=2,
        expected_workloads=2,
    )
    assert result["overall"]["all_correct"] is True
    assert result["overall"]["mode_summary"]["optimized"][
        "warm_speedup_macro_mean"
    ] > result["overall"]["mode_summary"]["naive"][
        "warm_speedup_macro_mean"
    ]
    assert result["overall"]["optimized_over_naive_geometric_mean"] > 1.0
    assert result["overall"]["optimized_over_naive_median"] > 1.0
    assert result["overall"]["optimized_beats_naive_rate"] == 1.0
    assert len(result["aggregate_rows"]) == 6
    assert (tmp_path / "summary/ray_formal_aggregate.csv").is_file()
