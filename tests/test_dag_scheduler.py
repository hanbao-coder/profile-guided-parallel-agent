from __future__ import annotations

from pathlib import Path

from parallel_agent.dag_scheduler import (
    EdgeSpec,
    TaskSpec,
    plot_dag_scheduling_experiment,
    run_dag_scheduling_experiment,
    schedule_dag,
    upward_ranks,
)


ROOT = Path(__file__).resolve().parents[1]


def test_upward_rank_includes_communication() -> None:
    tasks = [TaskSpec("a", 1.0), TaskSpec("b", 2.0)]
    edges = [EdgeSpec("a", "b", 0.5)]

    ranks = upward_ranks(tasks, edges)

    assert ranks == {"b": 2.0, "a": 3.5}


def test_critical_path_policy_does_not_worsen_example() -> None:
    tasks = [
        TaskSpec("root", 0.1),
        TaskSpec("side", 0.5),
        TaskSpec("critical_1", 1.0),
        TaskSpec("critical_2", 1.0),
    ]
    edges = [
        EdgeSpec("root", "side", 0.0),
        EdgeSpec("root", "critical_1", 0.0),
        EdgeSpec("critical_1", "critical_2", 0.0),
    ]
    fifo = schedule_dag(tasks, edges, workers=2, policy="fifo")
    critical = schedule_dag(
        tasks, edges, workers=2, policy="critical_path"
    )

    assert critical["makespan"] <= fifo["makespan"]
    assert len(critical["schedule"]) == len(tasks)


def test_dag_experiment_and_plot(tmp_path: Path) -> None:
    result = run_dag_scheduling_experiment(
        ROOT / "configs/dag_scheduling_formal.yaml",
        output_dir=tmp_path / "results",
    )

    assert result["overall"]["graphs"] == 2
    assert result["overall"]["critical_path_better_or_equal"] is True
    figure = plot_dag_scheduling_experiment(
        tmp_path / "results/dag_scheduling_summary.csv",
        output_dir=tmp_path / "figures",
    )
    assert figure.exists()
