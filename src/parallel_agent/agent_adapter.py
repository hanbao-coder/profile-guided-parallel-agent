from __future__ import annotations

from pathlib import Path
from typing import Protocol

from .analyzer import analyze_file
from .artifacts import AnalysisArtifact, ParallelPlan


REQUIRED_CONTRACT = {"make_input", "unit", "combine", "equivalent"}


class AgentAdapter(Protocol):
    name: str

    def analyze(self, source_path: str | Path) -> AnalysisArtifact: ...

    def plan(
        self,
        analysis: AnalysisArtifact,
        *,
        workers: int,
        chunks: int,
    ) -> ParallelPlan: ...

    def repair(
        self,
        plan: ParallelPlan,
        feedback: dict[str, object],
        *,
        attempt: int,
    ) -> ParallelPlan: ...

    def optimize_performance(
        self,
        plan: ParallelPlan,
        feedback: dict[str, object],
        *,
        attempt: int,
    ) -> ParallelPlan: ...


class OfflineHeuristicAdapter:
    """Deterministic adapter used before an online LLM credential is configured."""

    name = "offline-heuristic-v1"

    def analyze(self, source_path: str | Path) -> AnalysisArtifact:
        path = Path(source_path).resolve()
        static = analyze_file(path)
        functions = set(static.functions)
        contract = sorted(REQUIRED_CONTRACT & functions)
        complete = REQUIRED_CONTRACT <= functions
        # Under the explicit contract, local sequential state inside unit(item)
        # is not shared between separate item calls. Global state remains unsafe.
        hard_hazard = "global_state" in static.hazards
        parallelizable = complete and not hard_hazard
        rationale: list[str] = []
        if complete:
            rationale.append("Detected explicit make_input/unit/combine/equivalent contract.")
        else:
            missing = sorted(REQUIRED_CONTRACT - functions)
            rationale.append("Missing supported contract functions: " + ", ".join(missing))
        if hard_hazard:
            rationale.append("Static analysis found global shared state.")
        elif complete:
            rationale.append("Each item can be mapped independently and combined afterward.")
        artifact = AnalysisArtifact(
            schema_version="1.0",
            source_path=str(path),
            workload_name=path.parent.name,
            functions=sorted(functions),
            loops=static.loops,
            hazards=static.hazards,
            contract_functions=contract,
            contract_complete=complete,
            parallelizable=parallelizable,
            rationale=rationale,
        )
        artifact.validate()
        return artifact

    def plan(
        self,
        analysis: AnalysisArtifact,
        *,
        workers: int,
        chunks: int,
    ) -> ParallelPlan:
        if analysis.parallelizable:
            plan = ParallelPlan(
                schema_version="1.0",
                source_path=analysis.source_path,
                parallelizable=True,
                backend="multiprocessing",
                strategy="map_reduce",
                workers=max(1, workers),
                chunks=max(1, chunks),
                correctness_gate=True,
                fallback="serial",
                reasons=[
                    "Use process workers for CPU-bound independent items.",
                    "Aggregate task outputs with the source combine function.",
                    "Accept candidate only after serial/parallel output equivalence.",
                ],
            )
        else:
            plan = ParallelPlan(
                schema_version="1.0",
                source_path=analysis.source_path,
                parallelizable=False,
                backend="serial",
                strategy="serial",
                workers=1,
                chunks=1,
                correctness_gate=True,
                fallback="serial",
                reasons=[
                    "The source is outside the supported contract or has a dependency hazard."
                ],
            )
        plan.validate()
        return plan

    def repair(
        self,
        plan: ParallelPlan,
        feedback: dict[str, object],
        *,
        attempt: int,
    ) -> ParallelPlan:
        """Apply a conservative offline repair; online adapters can use full feedback."""
        del feedback
        repaired = ParallelPlan(
            schema_version=plan.schema_version,
            source_path=plan.source_path,
            parallelizable=plan.parallelizable,
            backend=plan.backend,
            strategy=plan.strategy,
            workers=max(1, plan.workers // (attempt + 1)),
            chunks=max(1, plan.workers // (attempt + 1)),
            correctness_gate=plan.correctness_gate,
            fallback=plan.fallback,
            reasons=plan.reasons
            + [
                f"Repair attempt {attempt}: reduce worker and chunk count conservatively."
            ],
        )
        repaired.validate()
        return repaired

    def optimize_performance(
        self,
        plan: ParallelPlan,
        feedback: dict[str, object],
        *,
        attempt: int,
    ) -> ParallelPlan:
        """Use measured performance to avoid retaining harmful parallelism."""
        speedup = float(feedback.get("end_to_end_speedup", 0.0))
        minimum = float(feedback.get("minimum_speedup", 1.05))
        if speedup < minimum:
            optimized = ParallelPlan(
                schema_version=plan.schema_version,
                source_path=plan.source_path,
                parallelizable=False,
                backend="serial",
                strategy="serial",
                workers=1,
                chunks=1,
                correctness_gate=True,
                fallback="serial",
                reasons=plan.reasons
                + [
                    f"Performance attempt {attempt}: measured speedup "
                    f"{speedup:.3f}x is below the required {minimum:.3f}x; "
                    "fall back to serial."
                ],
            )
        else:
            optimized = plan
        optimized.validate()
        return optimized
