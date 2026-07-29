from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class StaticAnalysis:
    source: str
    functions: list[str] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)
    loops: int = 0
    read_names: list[str] = field(default_factory=list)
    written_names: list[str] = field(default_factory=list)
    global_names: list[str] = field(default_factory=list)
    hazards: list[str] = field(default_factory=list)
    parallelizable: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RunMetrics:
    benchmark: str
    mode: str
    size: int
    workers: int
    chunks: int
    runtime_seconds: float
    cpu_mean_percent: float
    cpu_peak_percent: float
    peak_rss_bytes: int
    task_count: int
    correct: bool
    selected_mode: str | None = None
    cold_start_seconds: float = 0.0
    total_runtime_seconds: float = 0.0
    task_overhead_seconds: float = 0.0
    input_serialized_bytes: int = 0
    input_serialization_seconds: float = 0.0
    output_serialized_bytes: int = 0
    output_serialization_seconds: float = 0.0
    execution_node_counts: dict[str, int] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
