from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class TaskSpec:
    name: str
    duration: float


@dataclass(frozen=True)
class EdgeSpec:
    source: str
    target: str
    communication: float


@dataclass(frozen=True)
class ScheduledTask:
    name: str
    worker: int
    start: float
    finish: float
    duration: float
    priority: float


def _validate_graph(
    tasks: list[TaskSpec], edges: list[EdgeSpec], workers: int
) -> None:
    if workers < 1:
        raise ValueError("workers must be positive")
    names = [task.name for task in tasks]
    if len(names) != len(set(names)):
        raise ValueError("task names must be unique")
    if any(task.duration <= 0 for task in tasks):
        raise ValueError("task durations must be positive")
    known = set(names)
    if any(
        edge.source not in known
        or edge.target not in known
        or edge.communication < 0
        for edge in edges
    ):
        raise ValueError("edges must reference tasks and have nonnegative cost")
    successors: dict[str, list[str]] = {name: [] for name in names}
    indegree = {name: 0 for name in names}
    for edge in edges:
        successors[edge.source].append(edge.target)
        indegree[edge.target] += 1
    queue = [name for name in names if indegree[name] == 0]
    visited = 0
    while queue:
        current = queue.pop(0)
        visited += 1
        for target in successors[current]:
            indegree[target] -= 1
            if indegree[target] == 0:
                queue.append(target)
    if visited != len(tasks):
        raise ValueError("task graph must be acyclic")


def upward_ranks(
    tasks: list[TaskSpec],
    edges: list[EdgeSpec],
    *,
    include_communication: bool = True,
) -> dict[str, float]:
    durations = {task.name: task.duration for task in tasks}
    successors: dict[str, list[tuple[str, float]]] = {
        task.name: [] for task in tasks
    }
    for edge in edges:
        successors[edge.source].append(
            (
                edge.target,
                edge.communication if include_communication else 0.0,
            )
        )
    memo: dict[str, float] = {}

    def rank(name: str) -> float:
        if name not in memo:
            tail = max(
                (
                    communication + rank(target)
                    for target, communication in successors[name]
                ),
                default=0.0,
            )
            memo[name] = durations[name] + tail
        return memo[name]

    for task in tasks:
        rank(task.name)
    return memo


def schedule_dag(
    tasks: list[TaskSpec],
    edges: list[EdgeSpec],
    *,
    workers: int,
    policy: str,
) -> dict[str, Any]:
    if policy not in {"fifo", "critical_path"}:
        raise ValueError("policy must be fifo or critical_path")
    _validate_graph(tasks, edges, workers)
    order = {task.name: index for index, task in enumerate(tasks)}
    task_by_name = {task.name: task for task in tasks}
    predecessors: dict[str, list[tuple[str, float]]] = {
        task.name: [] for task in tasks
    }
    for edge in edges:
        predecessors[edge.target].append(
            (edge.source, edge.communication)
        )
    ranks = upward_ranks(tasks, edges, include_communication=True)
    scheduled: dict[str, ScheduledTask] = {}
    worker_available = [0.0 for _ in range(workers)]
    while len(scheduled) < len(tasks):
        ready = [
            task
            for task in tasks
            if task.name not in scheduled
            and all(
                predecessor in scheduled
                for predecessor, _ in predecessors[task.name]
            )
        ]
        if not ready:
            raise RuntimeError("no schedulable task in a validated DAG")
        if policy == "fifo":
            selected = min(ready, key=lambda task: order[task.name])
            priority = float(-order[selected.name])
        else:
            selected = max(
                ready,
                key=lambda task: (ranks[task.name], -order[task.name]),
            )
            priority = ranks[selected.name]
        placements: list[tuple[float, float, int]] = []
        for worker in range(workers):
            dependency_ready = max(
                (
                    scheduled[pred].finish
                    + (
                        0.0
                        if scheduled[pred].worker == worker
                        else communication
                    )
                    for pred, communication in predecessors[selected.name]
                ),
                default=0.0,
            )
            start = max(worker_available[worker], dependency_ready)
            placements.append(
                (start + selected.duration, start, worker)
            )
        finish, start, worker = min(placements)
        item = ScheduledTask(
            name=selected.name,
            worker=worker,
            start=start,
            finish=finish,
            duration=selected.duration,
            priority=priority,
        )
        scheduled[selected.name] = item
        worker_available[worker] = finish
    makespan = max(item.finish for item in scheduled.values())
    total_compute = sum(task.duration for task in tasks)
    communication = sum(
        edge.communication
        for edge in edges
        if scheduled[edge.source].worker
        != scheduled[edge.target].worker
    )
    idle_ratio = 1.0 - total_compute / (workers * makespan)
    return {
        "policy": policy,
        "workers": workers,
        "makespan": makespan,
        "communication_priority_longest_path": max(ranks.values()),
        "worker_idle_ratio": idle_ratio,
        "cross_worker_communication": communication,
        "schedule": [
            asdict(item)
            for item in sorted(
                scheduled.values(), key=lambda item: (item.start, item.worker)
            )
        ],
    }


def run_dag_scheduling_experiment(
    config_path: str | Path,
    *,
    output_dir: str | Path,
) -> dict[str, Any]:
    import yaml

    config = yaml.safe_load(
        Path(config_path).read_text(encoding="utf-8")
    )
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for graph_name, graph in config["graphs"].items():
        tasks = [
            TaskSpec(name=name, duration=float(duration))
            for name, duration in graph["tasks"].items()
        ]
        edges = [
            EdgeSpec(
                source=str(edge["source"]),
                target=str(edge["target"]),
                communication=float(edge.get("communication", 0.0)),
            )
            for edge in graph["edges"]
        ]
        workers = int(graph.get("workers", config.get("workers", 2)))
        graph_results: dict[str, Any] = {}
        for policy in ("fifo", "critical_path"):
            result = schedule_dag(
                tasks, edges, workers=workers, policy=policy
            )
            graph_results[policy] = result
            rows.append(
                {
                    "graph": graph_name,
                    "policy": policy,
                    "workers": workers,
                    "makespan": result["makespan"],
                    "communication_priority_longest_path": result[
                        "communication_priority_longest_path"
                    ],
                    "worker_idle_ratio": result["worker_idle_ratio"],
                    "cross_worker_communication": result[
                        "cross_worker_communication"
                    ],
                    "speedup_over_fifo": 1.0,
                }
            )
        fifo_makespan = float(graph_results["fifo"]["makespan"])
        for row in rows:
            if row["graph"] == graph_name:
                row["speedup_over_fifo"] = (
                    fifo_makespan / float(row["makespan"])
                )
        (destination / f"{graph_name}_schedule.json").write_text(
            json.dumps(
                {
                    "graph": graph_name,
                    "tasks": [asdict(task) for task in tasks],
                    "edges": [asdict(edge) for edge in edges],
                    "results": graph_results,
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    summary = destination / "dag_scheduling_summary.csv"
    with summary.open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    overall = {
        "graphs": len(config["graphs"]),
        "critical_path_better_or_equal": all(
            float(row["speedup_over_fifo"]) >= 1.0
            for row in rows
            if row["policy"] == "critical_path"
        ),
    }
    (destination / "dag_scheduling_overall.json").write_text(
        json.dumps(overall, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return {"rows": rows, "overall": overall}


def plot_dag_scheduling_experiment(
    summary_csv: str | Path,
    *,
    output_dir: str | Path,
) -> Path:
    import matplotlib.pyplot as plt
    import numpy as np

    with Path(summary_csv).open(
        "r", encoding="utf-8-sig", newline=""
    ) as handle:
        rows = list(csv.DictReader(handle))
    graphs = list(dict.fromkeys(row["graph"] for row in rows))
    grouped = {
        (row["graph"], row["policy"]): row for row in rows
    }
    x = np.arange(len(graphs))
    width = 0.34
    fig, axes = plt.subplots(
        1, 2, figsize=(11.8, 5.2), constrained_layout=True
    )
    for index, (policy, label, color) in enumerate(
        [
            ("fifo", "FIFO", "#9CA3AF"),
            ("critical_path", "Critical path", "#2563EB"),
        ]
    ):
        offset = (index - 0.5) * width
        makespans = [
            float(grouped[(graph, policy)]["makespan"])
            for graph in graphs
        ]
        idle = [
            float(grouped[(graph, policy)]["worker_idle_ratio"])
            for graph in graphs
        ]
        bars = axes[0].bar(
            x + offset, makespans, width, label=label, color=color
        )
        axes[0].bar_label(bars, fmt="%.2f", padding=2)
        axes[1].bar(
            x + offset, idle, width, label=label, color=color
        )
    axes[0].set_title("DAG Makespan")
    axes[0].set_ylabel("Modeled seconds")
    axes[1].set_title("Worker Idle Ratio")
    axes[1].set_ylabel("Idle fraction")
    for axis in axes:
        axis.set_xticks(
            x,
            [name.replace("_", " ").title() for name in graphs],
        )
        axis.grid(axis="y", linestyle="--", alpha=0.3)
        axis.legend(frameon=False)
    fig.suptitle(
        "FIFO vs Communication-Aware Critical-Path Scheduling",
        fontsize=15,
        fontweight="bold",
    )
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    output = destination / "dag_scheduling_comparison.png"
    fig.savefig(output, dpi=220, bbox_inches="tight")
    plt.close(fig)
    return output
