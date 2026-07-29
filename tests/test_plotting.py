from __future__ import annotations

import csv
from pathlib import Path

from parallel_agent.plotting import plot_suite_results


def test_plot_suite_results_creates_three_figures(tmp_path: Path) -> None:
    csv_path = tmp_path / "suite.csv"
    fields = [
        "benchmark",
        "mode",
        "total_runtime_seconds",
        "total_runtime_iqr_seconds",
        "total_speedup",
        "selected_mode",
    ]
    rows = []
    for mode, runtime, speedup, selected in [
        ("serial", 1.0, 1.0, "serial"),
        ("naive", 0.8, 1.25, "naive"),
        ("optimized", 0.5, 2.0, "optimized"),
    ]:
        rows.append(
            {
                "benchmark": "example",
                "mode": mode,
                "total_runtime_seconds": runtime,
                "total_runtime_iqr_seconds": 0.1,
                "total_speedup": speedup,
                "selected_mode": selected,
            }
        )
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    result = plot_suite_results(csv_path, tmp_path / "figures")

    assert len(result) == 3
    assert all(Path(path).stat().st_size > 1_000 for path in result.values())
