from __future__ import annotations

from pathlib import Path

import yaml

from parallel_agent.agent_experiment import run_agent_experiment


ROOT = Path(__file__).resolve().parents[1]


def test_agent_experiment_runs_and_resumes(tmp_path: Path) -> None:
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    config_path = config_dir / "experiment.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "feedback_modes": ["one_shot", "performance"],
                "independent_runs": 1,
                "workloads": {
                    "prime_count": {
                        "path": str(
                            ROOT / "benchmarks/prime_count/workload.py"
                        ),
                        "size": 2,
                    }
                },
                "execution": {
                    "workers": 2,
                    "chunks": 2,
                    "timeout_seconds": 30,
                    "performance_repeats": 1,
                    "minimum_speedup": 1.05,
                    "max_performance_attempts": 1,
                },
                "budget": {
                    "max_model_calls": 10,
                    "max_total_tokens": 10000,
                },
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "experiment"

    first = run_agent_experiment(
        config_path,
        output_dir=output,
        adapter_name="offline",
    )
    second = run_agent_experiment(
        config_path,
        output_dir=output,
        adapter_name="offline",
        resume=True,
    )

    assert first["manifest"]["completed_jobs"] == 2
    assert first["manifest"]["executed_this_invocation"] == 2
    assert second["manifest"]["completed_jobs"] == 2
    assert second["manifest"]["executed_this_invocation"] == 0
    assert second["manifest"]["resumed_jobs"] == 2
    assert (output / "agent_experiment_summary.csv").exists()
    assert (output / "experiment_manifest.json").exists()
    assert len(list(output.rglob("run_report.json"))) == 2
