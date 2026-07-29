from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class AnalysisArtifact:
    schema_version: str
    source_path: str
    workload_name: str
    functions: list[str]
    loops: int
    hazards: list[str]
    contract_functions: list[str]
    contract_complete: bool
    parallelizable: bool
    rationale: list[str] = field(default_factory=list)

    def validate(self) -> None:
        if self.schema_version != "1.0":
            raise ValueError("Unsupported analysis schema version")
        if not self.source_path:
            raise ValueError("analysis.source_path is required")
        if self.parallelizable and not self.contract_complete:
            raise ValueError("Incomplete workload contract cannot be parallelized")
        if self.parallelizable and not self.rationale:
            raise ValueError("Parallelizable analysis requires rationale")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return asdict(self)


@dataclass(frozen=True)
class ParallelPlan:
    schema_version: str
    source_path: str
    parallelizable: bool
    backend: str
    strategy: str
    workers: int
    chunks: int
    correctness_gate: bool
    fallback: str
    reasons: list[str] = field(default_factory=list)

    def validate(self) -> None:
        if self.schema_version != "1.0":
            raise ValueError("Unsupported plan schema version")
        if self.backend not in {"multiprocessing", "serial"}:
            raise ValueError(f"Unsupported backend: {self.backend}")
        if self.strategy not in {"map_reduce", "serial"}:
            raise ValueError(f"Unsupported strategy: {self.strategy}")
        if self.workers < 1 or self.chunks < 1:
            raise ValueError("workers and chunks must be positive")
        if self.parallelizable and self.strategy == "serial":
            raise ValueError("Parallelizable plan cannot use serial strategy")
        if not self.parallelizable and self.strategy != "serial":
            raise ValueError("Rejected plan must use serial strategy")
        if not self.correctness_gate:
            raise ValueError("Correctness gate is mandatory")
        if self.fallback != "serial":
            raise ValueError("Only serial fallback is currently supported")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return asdict(self)

