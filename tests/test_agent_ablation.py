from __future__ import annotations

import json
from pathlib import Path

from parallel_agent.agent_ablation import (
    plot_agent_ablation,
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

    figure = plot_agent_ablation(
        tmp_path / "summary.csv", tmp_path / "ablation.png"
    )
    assert figure.stat().st_size > 1_000
