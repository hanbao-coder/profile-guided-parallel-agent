from __future__ import annotations

from pathlib import Path

import yaml

from parallel_agent.task_fusion import (
    execute_fusion_strategy,
    plot_task_fusion_experiment,
    profile_fusion,
    run_task_fusion_experiment,
)


ROOT = Path(__file__).resolve().parents[1]


def test_profile_fuses_single_consumer_and_preserves_shared_producer() -> None:
    chain = profile_fusion(
        ROOT / "benchmarks/fusion_chain/workload.py",
        size=2,
        seed=42,
        sample_items=1,
    )
    fanout = profile_fusion(
        ROOT / "benchmarks/fusion_fanout/workload.py",
        size=2,
        seed=42,
        sample_items=1,
    )

    assert chain.selected_strategy == "fused"
    assert fanout.selected_strategy == "unfused"


def test_fusion_strategies_preserve_results() -> None:
    source = ROOT / "benchmarks/fusion_chain/workload.py"
    profile = profile_fusion(source, size=2, seed=42, sample_items=1)
    serial = execute_fusion_strategy(
        source,
        strategy="serial",
        size=2,
        seed=42,
        workers=1,
        chunks=1,
        profile=profile,
    )
    for strategy in ("unfused", "fixed_fused", "aware"):
        run = execute_fusion_strategy(
            source,
            strategy=strategy,
            size=2,
            seed=42,
            workers=1,
            chunks=1,
            profile=profile,
        )
        assert run["result"] == serial["result"]


def test_task_fusion_experiment_writes_summary(tmp_path: Path) -> None:
    config = tmp_path / "fusion.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "workers": 1,
                "chunks": 1,
                "warmups": 0,
                "repeats": 1,
                "workloads": {
                    "chain": {
                        "path": str(
                            ROOT / "benchmarks/fusion_chain/workload.py"
                        ),
                        "size": 2,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    result = run_task_fusion_experiment(
        config, output_dir=tmp_path / "results"
    )

    assert result["overall"]["all_correct"] is True
    assert result["overall"]["aware_choices"]["chain"] == "fused"
    assert (tmp_path / "results/task_fusion_summary.csv").exists()
    figure = plot_task_fusion_experiment(
        tmp_path / "results/task_fusion_summary.csv",
        output_dir=tmp_path / "figures",
    )
    assert figure.exists()
