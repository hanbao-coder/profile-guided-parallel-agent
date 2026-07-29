from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import yaml

from .runner import benchmark


def run_suite(
    config_path: str | Path,
    *,
    scale: str,
    workers: int,
    repeats: int,
    warmups: int,
    seed: int,
    backend: str,
    output_dir: str | Path,
    randomize_order: bool = True,
) -> dict[str, Any]:
    if scale not in {"small", "large"}:
        raise ValueError("scale must be 'small' or 'large'")
    config_file = Path(config_path)
    config = yaml.safe_load(config_file.read_text(encoding="utf-8"))
    entries = config.get("benchmarks", {})
    if not entries:
        raise ValueError("Benchmark config contains no benchmarks")

    root = config_file.resolve().parents[1]
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    reports: dict[str, Any] = {}
    rows: list[dict[str, Any]] = []

    for name, entry in entries.items():
        workload_path = root / entry["path"]
        report = benchmark(
            workload_path=workload_path,
            size=int(entry[scale]),
            workers=workers,
            modes=["serial", "naive", "optimized"],
            repeats=repeats,
            warmups=warmups,
            seed=seed,
            output=destination / f"{name}_{scale}.json",
            backend=backend,
            randomize_order=randomize_order,
        )
        reports[name] = report
        for mode, summary in report["summary"].items():
            rows.append(
                {
                    "benchmark": name,
                    "scale": scale,
                    "mode": mode,
                    "selected_mode": "|".join(summary["selected_modes"]),
                    "workers": summary["workers"],
                    "task_count": summary["task_count"],
                    "warm_runtime_seconds": summary["runtime_median_seconds"],
                    "cold_start_seconds": summary["cold_start_median_seconds"],
                    "total_runtime_seconds": summary[
                        "total_runtime_median_seconds"
                    ],
                    "total_runtime_iqr_seconds": summary[
                        "total_runtime_iqr_seconds"
                    ],
                    "cpu_mean_percent": summary["cpu_mean_percent"],
                    "parallel_overhead_core_seconds": summary[
                        "parallel_overhead_core_seconds"
                    ],
                    "parallel_overhead_ratio": summary[
                        "parallel_overhead_ratio"
                    ],
                    "warm_speedup": summary["speedup"],
                    "total_speedup": summary["total_speedup"],
                    "first_use_total_runtime_seconds": summary[
                        "first_use_total_runtime_seconds"
                    ],
                    "first_use_speedup": summary["first_use_speedup"],
                    "first_use_parallel_overhead_ratio": summary[
                        "first_use_parallel_overhead_ratio"
                    ],
                    "correct": summary["correct"],
                    "input_serialized_bytes": summary["input_serialized_bytes"],
                    "input_serialization_seconds": summary[
                        "input_serialization_seconds"
                    ],
                    "output_serialized_bytes": summary["output_serialized_bytes"],
                    "output_serialization_seconds": summary[
                        "output_serialization_seconds"
                    ],
                    "serialization_to_runtime_ratio": summary[
                        "serialization_to_runtime_ratio"
                    ],
                }
            )

    csv_path = destination / f"suite_{scale}.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    manifest = {
        "scale": scale,
        "workers": workers,
        "repeats": repeats,
        "warmups": warmups,
        "backend": backend,
        "randomize_order": randomize_order,
        "benchmarks": list(reports),
        "csv": str(csv_path),
    }
    (destination / f"suite_{scale}_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return {"manifest": manifest, "reports": reports, "rows": rows}
