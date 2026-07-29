from __future__ import annotations

import json
from pathlib import Path

from parallel_agent.agent_ablation import (
    aggregate_agent_rows,
    overall_agent_metrics,
    plot_agent_ablation,
    plot_agent_experiment,
    summarize_agent_runs,
)


def _write(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_summarize_agent_runs_accounts_for_serial_fallback(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _write(run_dir / "analysis.json", {"workload_name": "tiny_tasks"})
    _write(
        run_dir / "run_report.json",
        {
            "feedback_mode": "performance",
            "status": "accepted",
            "correct": True,
            "selected_mode": "serial",
            "repair_attempts_used": 0,
            "performance_attempts_used": 1,
            "attempts": [
                {
                    "performance": {
                        "end_to_end_speedup": 0.4,
                    }
                }
            ],
        },
    )
    _write(
        run_dir / "model_trace.json",
        {
            "calls": [
                {
                    "model": "deepseek-v4-pro",
                    "prompt_tokens": 100,
                    "completion_tokens": 20,
                    "total_tokens": 120,
                },
                {
                    "model": "deepseek-v4-flash",
                    "prompt_tokens": 80,
                    "completion_tokens": 10,
                    "total_tokens": 90,
                },
            ]
        },
    )

    rows = summarize_agent_runs([run_dir], tmp_path / "summary.csv")

    assert rows[0]["effective_speedup_after_fallback"] == 1.0
    assert rows[0]["pro_calls"] == 1
    assert rows[0]["flash_calls"] == 1
    assert rows[0]["total_tokens"] == 210
    assert rows[0]["estimated_cost_upper_usd"] > 0

    aggregate = aggregate_agent_rows(
        rows, tmp_path / "aggregate.csv"
    )
    assert aggregate[0]["correct_rate"] == 1.0
    assert aggregate[0]["performance_regression_rate"] == 0.0
    assert aggregate[0]["effective_speedup_mean"] == 1.0
    overall = overall_agent_metrics(
        aggregate, tmp_path / "overall.csv"
    )
    assert overall[0]["runs"] == 1
    assert overall[0]["performance_regression_rate"] == 0.0

    figure = plot_agent_ablation(
        tmp_path / "summary.csv", tmp_path / "ablation.png"
    )
    assert figure.stat().st_size > 1_000

    figures = plot_agent_experiment(
        tmp_path / "aggregate.csv", tmp_path / "formal_figures"
    )
    assert all(Path(path).stat().st_size > 1_000 for path in figures.values())
