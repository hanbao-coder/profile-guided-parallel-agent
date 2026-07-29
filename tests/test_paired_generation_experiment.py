from __future__ import annotations

from pathlib import Path

import yaml

from parallel_agent.agent_adapter import OfflineHeuristicAdapter
from parallel_agent.controlled_codegen import canonical_parallel_impl
from parallel_agent.paired_generation_experiment import (
    plot_paired_generation_experiment,
    run_paired_generation_experiment,
)


ROOT = Path(__file__).resolve().parents[1]


def test_paired_generation_experiment_shares_plan_and_resumes(
    tmp_path: Path,
) -> None:
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    config_path = config_dir / "paired.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "independent_runs": 1,
                "order_seed": 123,
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
                    "seed": 42,
                    "timeout_seconds": 30,
                    "max_code_repair_attempts": 1,
                },
                "measurement": {"warmups": 0, "repeats": 1},
                "budget": {
                    "max_model_calls": 10,
                    "max_total_tokens": 10000,
                },
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "paired"

    first = run_paired_generation_experiment(
        config_path,
        output_dir=output,
        adapter_name="offline",
    )
    second = run_paired_generation_experiment(
        config_path,
        output_dir=output,
        adapter_name="offline",
        resume=True,
    )

    assert first["manifest"]["completed_jobs"] == 1
    assert first["manifest"]["shared_analysis_and_plan"] is True
    assert first["rows"][0]["template_correct"] is True
    assert first["rows"][0]["llm_correct"] is True
    assert first["rows"][0]["shared_plan"] is True
    assert second["manifest"]["executed_this_invocation"] == 0
    assert second["manifest"]["resumed_jobs"] == 1
    assert (output / "paired_generation_summary.csv").exists()
    assert (output / "paired_generation_aggregate.csv").exists()
    assert (output / "paired_generation_overall.json").exists()
    figure = plot_paired_generation_experiment(
        output / "paired_generation_summary.csv",
        output / "paired_generation_aggregate.csv",
        tmp_path / "figures",
    )
    assert figure.exists()


class _InvalidMetadataAdapter(OfflineHeuristicAdapter):
    def generate_parallel_impl(self, plan):
        del plan
        return canonical_parallel_impl().replace(
            "return flattened, len(task_chunks)",
            "return flattened, len(flattened)",
        )


def test_failed_generator_is_included_in_summary_denominator(
    tmp_path: Path,
) -> None:
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    config_path = config_dir / "failed.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "independent_runs": 1,
                "workloads": {
                    "tiny_tasks": {
                        "path": str(
                            ROOT / "benchmarks/tiny_tasks/workload.py"
                        ),
                        "size": 8,
                    }
                },
                "execution": {
                    "workers": 2,
                    "chunks": 2,
                    "timeout_seconds": 30,
                    "max_code_repair_attempts": 0,
                },
                "measurement": {"warmups": 0, "repeats": 1},
            }
        ),
        encoding="utf-8",
    )

    result = run_paired_generation_experiment(
        config_path,
        output_dir=tmp_path / "failed",
        adapter_name="offline",
        adapter_factory=_InvalidMetadataAdapter,
    )

    assert result["manifest"]["completed_jobs"] == 0
    assert len(result["manifest"]["failed_jobs"]) == 1
    assert len(result["rows"]) == 1
    assert result["rows"][0]["status"] == "failed"
    assert result["overall"]["generation_failure_rate"] == 1.0
    assert result["overall"]["llm_correct_rate"] == 0.0
