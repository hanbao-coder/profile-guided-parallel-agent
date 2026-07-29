from __future__ import annotations

import csv
import json
import math
from pathlib import Path
import statistics
from typing import Any


MODES = ("serial", "naive", "optimized")


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError("Cannot write an empty Ray summary")
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _mean(values: list[float]) -> float:
    return statistics.fmean(values)


def _stdev(values: list[float]) -> float:
    return statistics.stdev(values) if len(values) > 1 else 0.0


def _geometric_mean(values: list[float]) -> float:
    if not values or any(value <= 0 for value in values):
        raise ValueError("Geometric mean requires positive values")
    return math.exp(_mean([math.log(value) for value in values]))


def summarize_ray_formal_runs(
    input_dir: str | Path,
    output_dir: str | Path,
    *,
    expected_runs: int = 3,
    expected_workloads: int = 8,
) -> dict[str, Any]:
    source = Path(input_dir)
    destination = Path(output_dir)
    run_dirs = sorted(path for path in source.glob("run_*") if path.is_dir())
    if len(run_dirs) != expected_runs:
        raise ValueError(
            f"Expected {expected_runs} run directories, found {len(run_dirs)}"
        )

    all_rows: list[dict[str, Any]] = []
    startup_seconds: list[float] = []
    task_overheads: list[float] = []
    repeats_per_run: list[int] = []
    for run_index, run_dir in enumerate(run_dirs, start=1):
        suite_csv = run_dir / "suite_large.csv"
        if not suite_csv.is_file():
            raise ValueError(f"Missing suite CSV: {suite_csv}")
        rows = _read_csv(suite_csv)
        workloads = {row["benchmark"] for row in rows}
        if len(workloads) != expected_workloads:
            raise ValueError(
                f"{run_dir.name}: expected {expected_workloads} workloads, "
                f"found {len(workloads)}"
            )
        expected_pairs = {
            (workload, mode)
            for workload in workloads
            for mode in MODES
        }
        actual_pairs = {(row["benchmark"], row["mode"]) for row in rows}
        if actual_pairs != expected_pairs:
            raise ValueError(f"{run_dir.name}: workload/mode matrix is incomplete")
        for row in rows:
            normalized = dict(row)
            normalized["run"] = run_index
            all_rows.append(normalized)

        suite_manifest_path = run_dir / "suite_large_manifest.json"
        if not suite_manifest_path.is_file():
            raise ValueError(f"Missing suite manifest: {suite_manifest_path}")
        suite_manifest = json.loads(
            suite_manifest_path.read_text(encoding="utf-8")
        )
        repeats_per_run.append(int(suite_manifest["repeats"]))

        reports = sorted(run_dir.glob("*_large.json"))
        if len(reports) != expected_workloads:
            raise ValueError(
                f"{run_dir.name}: expected {expected_workloads} JSON reports, "
                f"found {len(reports)}"
            )
        first_report = json.loads(reports[0].read_text(encoding="utf-8"))
        startup_seconds.append(float(first_report["backend_startup_seconds"]))
        cpu_by_pair: dict[tuple[str, str], float] = {}
        for report_path in reports:
            report = json.loads(report_path.read_text(encoding="utf-8"))
            benchmark = report_path.name.removesuffix("_large.json")
            for mode in MODES:
                cpu_by_pair[(benchmark, mode)] = float(
                    report.get("summary", {})
                    .get(mode, {})
                    .get("cpu_mean_percent", 0.0)
                )
            calibration = report["calibrations"].get(str(report["workers"]))
            if calibration:
                task_overheads.append(
                    float(calibration["task_overhead_seconds"])
                )
        for row in all_rows:
            if int(row["run"]) == run_index and "cpu_mean_percent" not in row:
                row["cpu_mean_percent"] = cpu_by_pair[
                    (row["benchmark"], row["mode"])
                ]

    if not all(row["correct"].lower() == "true" for row in all_rows):
        raise ValueError("At least one formal Ray result failed correctness")

    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in all_rows:
        grouped.setdefault((row["benchmark"], row["mode"]), []).append(row)

    aggregate_rows: list[dict[str, Any]] = []
    for (benchmark, mode), rows in sorted(grouped.items()):
        warm_speedups = [float(row["warm_speedup"]) for row in rows]
        first_use_speedups = [float(row["first_use_speedup"]) for row in rows]
        runtimes = [float(row["warm_runtime_seconds"]) for row in rows]
        task_counts = [float(row["task_count"]) for row in rows]
        cpu_values = [float(row["cpu_mean_percent"]) for row in rows]
        serialization_ratios = [
            float(row["serialization_to_runtime_ratio"]) for row in rows
        ]
        overhead_ratios = [
            (
                float(row["parallel_overhead_ratio"])
                if row.get("parallel_overhead_ratio") not in {None, ""}
                else float(row["workers"]) / float(row["warm_speedup"]) - 1.0
            )
            for row in rows
        ]
        first_use_overhead_ratios = [
            (
                float(row["first_use_parallel_overhead_ratio"])
                if row.get("first_use_parallel_overhead_ratio")
                not in {None, ""}
                else float(row["workers"])
                / float(row["first_use_speedup"])
                - 1.0
            )
            for row in rows
        ]
        aggregate_rows.append(
            {
                "benchmark": benchmark,
                "mode": mode,
                "runs": len(rows),
                "all_correct": True,
                "selected_modes": "|".join(
                    sorted({row["selected_mode"] for row in rows})
                ),
                "warm_runtime_mean_seconds": _mean(runtimes),
                "warm_runtime_stdev_seconds": _stdev(runtimes),
                "warm_speedup_mean": _mean(warm_speedups),
                "warm_speedup_stdev": _stdev(warm_speedups),
                "first_use_speedup_mean": _mean(first_use_speedups),
                "first_use_speedup_stdev": _stdev(first_use_speedups),
                "task_count_mean": _mean(task_counts),
                "cpu_mean_percent": _mean(cpu_values),
                "serialization_ratio_mean": _mean(serialization_ratios),
                "parallel_overhead_ratio_mean": _mean(overhead_ratios),
                "first_use_parallel_overhead_ratio_mean": _mean(
                    first_use_overhead_ratios
                ),
            }
        )

    mode_summary: dict[str, dict[str, float]] = {}
    for mode in MODES:
        rows = [row for row in all_rows if row["mode"] == mode]
        warm = [float(row["warm_speedup"]) for row in rows]
        first_use = [float(row["first_use_speedup"]) for row in rows]
        mode_summary[mode] = {
            "observations": len(rows),
            "warm_speedup_macro_mean": _mean(warm),
            "warm_regression_rate": sum(value < 0.95 for value in warm)
            / len(warm),
            "warm_improvement_rate": sum(value > 1.05 for value in warm)
            / len(warm),
            "first_use_speedup_macro_mean": _mean(first_use),
            "first_use_regression_rate": sum(
                value < 0.95 for value in first_use
            )
            / len(first_use),
        }

    by_run_workload: dict[tuple[int, str], dict[str, dict[str, Any]]] = {}
    for row in all_rows:
        by_run_workload.setdefault(
            (int(row["run"]), row["benchmark"]), {}
        )[row["mode"]] = row
    optimized_over_naive: list[float] = []
    break_even_repetitions: list[int] = []
    no_warm_savings = 0
    for rows in by_run_workload.values():
        naive_runtime = float(rows["naive"]["warm_runtime_seconds"])
        optimized_runtime = float(rows["optimized"]["warm_runtime_seconds"])
        serial_runtime = float(rows["serial"]["warm_runtime_seconds"])
        optimized_over_naive.append(naive_runtime / optimized_runtime)
        savings = serial_runtime - optimized_runtime
        if savings > 0:
            run_index = int(rows["optimized"]["run"]) - 1
            break_even_repetitions.append(
                math.ceil(startup_seconds[run_index] / savings)
            )
        else:
            no_warm_savings += 1

    overall = {
        "independent_runs": expected_runs,
        "workloads": expected_workloads,
        "modes": len(MODES),
        "formal_measurements": sum(
            expected_workloads * len(MODES) * repeats
            for repeats in repeats_per_run
        ),
        "all_correct": True,
        "ray_startup_seconds_mean": _mean(startup_seconds),
        "ray_startup_seconds_stdev": _stdev(startup_seconds),
        "ray_task_overhead_seconds_mean": _mean(task_overheads),
        "ray_task_overhead_seconds_stdev": _stdev(task_overheads),
        "mode_summary": mode_summary,
        "optimized_over_naive_mean": _mean(optimized_over_naive),
        "optimized_over_naive_geometric_mean": _geometric_mean(
            optimized_over_naive
        ),
        "optimized_over_naive_median": statistics.median(
            optimized_over_naive
        ),
        "optimized_over_naive_stdev": _stdev(optimized_over_naive),
        "optimized_beats_naive_rate": sum(
            value > 1.05 for value in optimized_over_naive
        )
        / len(optimized_over_naive),
        "break_even_repetitions_mean": (
            _mean([float(value) for value in break_even_repetitions])
            if break_even_repetitions
            else None
        ),
        "break_even_repetitions_median": (
            statistics.median(break_even_repetitions)
            if break_even_repetitions
            else None
        ),
        "cases_without_warm_savings": no_warm_savings,
    }

    destination.mkdir(parents=True, exist_ok=True)
    _write_csv(destination / "ray_formal_aggregate.csv", aggregate_rows)
    (destination / "ray_formal_overall.json").write_text(
        json.dumps(overall, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    manifest = {
        "input_dir": str(source),
        "run_directories": [path.name for path in run_dirs],
        "expected_runs": expected_runs,
        "expected_workloads": expected_workloads,
        "aggregate_csv": "ray_formal_aggregate.csv",
        "overall_json": "ray_formal_overall.json",
    }
    (destination / "experiment_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return {
        "overall": overall,
        "aggregate_rows": aggregate_rows,
        "manifest": manifest,
    }
