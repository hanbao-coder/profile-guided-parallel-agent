from __future__ import annotations

from pathlib import Path

import yaml

from parallel_agent.configuration_search_experiment import (
    plot_configuration_search_experiment,
    run_configuration_search_experiment,
)


ROOT = Path(__file__).resolve().parents[1]


def test_configuration_search_experiment_runs_and_resumes(
    tmp_path: Path,
) -> None:
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    config_path = config_dir / "search.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "independent_runs": 1,
                "workloads": {
                    "prime_count": {
                        "path": str(
                            ROOT / "benchmarks/prime_count/workload.py"
                        ),
                        "size": 2,
                        "tuning_size": 1,
                    }
                },
                "execution": {
                    "max_workers": 2,
                    "chunk_multipliers": [1],
                    "tuning_repeats": 1,
                    "confirmation_repeats": 1,
                    "holdout_repeats": 1,
                    "warmups": 0,
                    "timeout_seconds": 30,
                    "minimum_speedup": 1.01,
                },
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "experiment"

    first = run_configuration_search_experiment(
        config_path,
        output_dir=output,
    )
    second = run_configuration_search_experiment(
        config_path,
        output_dir=output,
        resume=True,
    )

    assert first["manifest"]["completed_jobs"] == 1
    assert first["manifest"]["tuning_and_holdout_separated"] is True
    assert first["manifest"]["small_sample_scale_confirmation"] is True
    assert len(first["rows"]) == 1
    assert "no_scale_speedup" in first["rows"][0]
    assert "no_scale_speedup_macro_mean" in first["overall"]
    assert "no_scale_regression_rate" in first["overall"]
    assert second["manifest"]["executed_this_invocation"] == 0
    assert second["manifest"]["resumed_jobs"] == 1
    assert (output / "configuration_search_summary.csv").exists()
    assert (output / "configuration_search_aggregate.csv").exists()
    assert (output / "configuration_search_overall.json").exists()
    figure = plot_configuration_search_experiment(
        output / "configuration_search_aggregate.csv",
        output / "configuration_search_overall.json",
        tmp_path / "figures",
    )
    assert figure.exists()
