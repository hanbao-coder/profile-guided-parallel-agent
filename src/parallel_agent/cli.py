from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .analyzer import analyze_file
from .agent_ablation import (
    plot_agent_ablation,
    plot_agent_experiment,
    summarize_agent_runs,
)
from .agent_experiment import run_agent_experiment
from .agent_pipeline import run_agent_pipeline
from .configuration_search import run_configuration_search
from .configuration_search_experiment import (
    plot_configuration_search_experiment,
    run_configuration_search_experiment,
)
from .deepseek_adapter import DeepSeekAdapter, DeepSeekConfigurationError
from .dag_scheduler import (
    plot_dag_scheduling_experiment,
    run_dag_scheduling_experiment,
)
from .plotting import plot_suite_results
from .loop_frontend import LoopNormalizationError, normalize_serial_loop
from .paired_generation_experiment import (
    plot_paired_generation_experiment,
    run_paired_generation_experiment,
)
from .runner import benchmark
from .suite import run_suite
from .task_fusion import (
    plot_task_fusion_experiment,
    run_task_fusion_experiment,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="parallel-agent",
        description="Profile-guided Python-to-Ray research prototype.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    analyze = commands.add_parser("analyze", help="Run static dependency analysis.")
    analyze.add_argument("source")
    analyze.add_argument("--output")

    normalize = commands.add_parser(
        "normalize-loop",
        help=(
            "Convert a conservative serial map-then-combine loop into the "
            "Agent workload contract."
        ),
    )
    normalize.add_argument("source")
    normalize.add_argument("--output", required=True)
    normalize.add_argument("--metadata")
    normalize.add_argument("--entry")
    normalize.add_argument("--input-factory", default="make_input")
    normalize.add_argument("--equivalent", default="equivalent")

    loop_agent = commands.add_parser(
        "agent-loop",
        help=(
            "Normalize a supported ordinary serial loop, then run the "
            "analyze-plan-generate-validate Agent pipeline."
        ),
    )
    loop_agent.add_argument("source")
    loop_agent.add_argument("--entry")
    loop_agent.add_argument("--input-factory", default="make_input")
    loop_agent.add_argument("--equivalent", default="equivalent")
    loop_agent.add_argument("--output-dir", required=True)
    loop_agent.add_argument("--size", type=int, default=4)
    loop_agent.add_argument("--seed", type=int, default=42)
    loop_agent.add_argument("--workers", type=int, default=4)
    loop_agent.add_argument("--chunks", type=int, default=4)
    loop_agent.add_argument("--timeout", type=float, default=120.0)
    loop_agent.add_argument(
        "--feedback-mode",
        choices=["one_shot", "correctness", "performance"],
        default="correctness",
    )
    loop_agent.add_argument("--performance-repeats", type=int, default=3)
    loop_agent.add_argument("--minimum-speedup", type=float, default=1.05)
    loop_agent.add_argument(
        "--execution-backend",
        choices=["multiprocessing", "ray"],
        default="multiprocessing",
    )
    loop_agent.add_argument(
        "--adapter",
        choices=["offline", "deepseek"],
        default="offline",
    )

    bench = commands.add_parser("benchmark", help="Run benchmark modes.")
    bench.add_argument("workload")
    bench.add_argument("--size", type=int, default=24)
    bench.add_argument("--workers", type=int, default=4)
    bench.add_argument(
        "--backend",
        choices=["multiprocessing", "ray"],
        default="multiprocessing",
        help="Use multiprocessing locally; use Ray on a compatible host.",
    )
    bench.add_argument(
        "--ray-address",
        help="Connect to an existing Ray cluster, for example 'auto'.",
    )
    bench.add_argument(
        "--modes", nargs="+", default=["serial", "naive", "optimized"]
    )
    bench.add_argument("--repeats", type=int, default=3)
    bench.add_argument("--warmups", type=int, default=1)
    bench.add_argument("--seed", type=int, default=42)
    bench.add_argument("--output", default="results/raw/latest.json")
    bench.add_argument(
        "--fixed-order",
        action="store_true",
        help="Disable the default reproducible random execution order.",
    )

    suite = commands.add_parser("suite", help="Run every configured benchmark.")
    suite.add_argument("--config", default="configs/benchmarks.yaml")
    suite.add_argument("--scale", choices=["small", "large"], default="small")
    suite.add_argument("--workers", type=int, default=4)
    suite.add_argument(
        "--backend",
        choices=["multiprocessing", "ray"],
        default="multiprocessing",
    )
    suite.add_argument(
        "--ray-address",
        help="Connect to an existing Ray cluster, for example 'auto'.",
    )
    suite.add_argument("--repeats", type=int, default=3)
    suite.add_argument("--warmups", type=int, default=1)
    suite.add_argument("--seed", type=int, default=42)
    suite.add_argument("--output-dir", default="results/raw")
    suite.add_argument("--fixed-order", action="store_true")

    plot = commands.add_parser(
        "plot", help="Create report-ready figures from a suite CSV."
    )
    plot.add_argument("suite_csv")
    plot.add_argument("--output-dir", default="results/figures/latest")

    summarize = commands.add_parser(
        "summarize-agent",
        help="Aggregate Agent run directories into an ablation CSV.",
    )
    summarize.add_argument("run_dirs", nargs="+")
    summarize.add_argument("--output", required=True)

    plot_ablation = commands.add_parser(
        "plot-agent-ablation",
        help="Create a report figure from an Agent ablation CSV.",
    )
    plot_ablation.add_argument("summary_csv")
    plot_ablation.add_argument("--output", required=True)

    plot_experiment = commands.add_parser(
        "plot-agent-experiment",
        help="Create formal figures from an Agent aggregate CSV.",
    )
    plot_experiment.add_argument("aggregate_csv")
    plot_experiment.add_argument("--output-dir", required=True)

    experiment = commands.add_parser(
        "agent-experiment",
        help="Run a resumable multi-workload Agent ablation experiment.",
    )
    experiment.add_argument("config")
    experiment.add_argument("--output-dir", required=True)
    experiment.add_argument(
        "--adapter", choices=["offline", "deepseek"], default="deepseek"
    )
    experiment.add_argument("--no-resume", action="store_true")

    paired = commands.add_parser(
        "paired-generation-experiment",
        help=(
            "Compare template and LLM generators under one shared analysis "
            "and parallel plan."
        ),
    )
    paired.add_argument("config")
    paired.add_argument("--output-dir", required=True)
    paired.add_argument(
        "--adapter", choices=["offline", "deepseek"], default="deepseek"
    )
    paired.add_argument("--no-resume", action="store_true")

    plot_paired = commands.add_parser(
        "plot-paired-generation",
        help="Plot reliability and speed results for a paired generator run.",
    )
    plot_paired.add_argument("summary_csv")
    plot_paired.add_argument("aggregate_csv")
    plot_paired.add_argument("--output-dir", required=True)

    search = commands.add_parser(
        "configuration-search",
        help=(
            "Measure Worker/Chunk candidates on tuning runs and verify the "
            "selected configuration on separate holdout runs."
        ),
    )
    search.add_argument("source")
    search.add_argument("--output-dir", required=True)
    search.add_argument("--size", type=int, required=True)
    search.add_argument(
        "--tuning-size",
        type=int,
        help="Optional smaller input used only for configuration selection.",
    )
    search.add_argument("--seed", type=int, default=42)
    search.add_argument("--max-workers", type=int, default=4)
    search.add_argument(
        "--chunk-multipliers", nargs="+", type=int, default=[1, 2, 4]
    )
    search.add_argument("--tuning-repeats", type=int, default=2)
    search.add_argument("--confirmation-repeats", type=int, default=2)
    search.add_argument("--holdout-repeats", type=int, default=5)
    search.add_argument("--warmups", type=int, default=1)
    search.add_argument("--timeout", type=float, default=120.0)
    search.add_argument("--minimum-speedup", type=float, default=1.05)
    search.add_argument(
        "--minimum-relative-improvement", type=float, default=1.05
    )
    search.add_argument("--order-seed", type=int, default=42)
    search.add_argument(
        "--cache-dir",
        help=(
            "Reuse an identical source/configuration/environment search "
            "result outside formal experiments."
        ),
    )

    search_experiment = commands.add_parser(
        "configuration-search-experiment",
        help="Run a resumable multi-workload configuration-search study.",
    )
    search_experiment.add_argument("config")
    search_experiment.add_argument("--output-dir", required=True)
    search_experiment.add_argument("--no-resume", action="store_true")

    plot_search = commands.add_parser(
        "plot-configuration-search",
        help="Plot fixed versus adaptive configuration-search results.",
    )
    plot_search.add_argument("aggregate_csv")
    plot_search.add_argument("overall_json")
    plot_search.add_argument("--output-dir", required=True)

    fusion = commands.add_parser(
        "task-fusion-experiment",
        help="Compare unfused, fixed-fusion, and communication-aware pipelines.",
    )
    fusion.add_argument("config")
    fusion.add_argument("--output-dir", required=True)

    plot_fusion = commands.add_parser(
        "plot-task-fusion",
        help="Plot task-fusion runtime and communication results.",
    )
    plot_fusion.add_argument("summary_csv")
    plot_fusion.add_argument("--output-dir", required=True)

    dag = commands.add_parser(
        "dag-scheduling-experiment",
        help="Compare FIFO and communication-aware critical-path scheduling.",
    )
    dag.add_argument("config")
    dag.add_argument("--output-dir", required=True)

    plot_dag = commands.add_parser(
        "plot-dag-scheduling",
        help="Plot DAG scheduling makespan and worker idle ratio.",
    )
    plot_dag.add_argument("summary_csv")
    plot_dag.add_argument("--output-dir", required=True)

    agent = commands.add_parser("agent", help="Run the analyze-plan-generate loop.")
    agent.add_argument("source")
    agent.add_argument("--output-dir", default="generated/latest")
    agent.add_argument("--size", type=int, default=4)
    agent.add_argument("--seed", type=int, default=42)
    agent.add_argument("--workers", type=int, default=4)
    agent.add_argument("--chunks", type=int, default=4)
    agent.add_argument("--timeout", type=float, default=120.0)
    agent.add_argument("--max-repairs", type=int, default=2)
    agent.add_argument(
        "--feedback-mode",
        choices=["one_shot", "correctness", "performance"],
        default="correctness",
        help="Select the ablation group for Agent feedback.",
    )
    agent.add_argument(
        "--performance-repeats",
        "--evaluation-repeats",
        dest="performance_repeats",
        type=int,
        default=3,
        help="Repeated serial/parallel measurements for every ablation group.",
    )
    agent.add_argument("--minimum-speedup", type=float, default=1.05)
    agent.add_argument("--max-performance-attempts", type=int, default=1)
    agent.add_argument(
        "--performance-controller",
        choices=["llm_feedback", "configuration_search"],
        default="llm_feedback",
        help=(
            "Use model feedback or the deterministic multi-scale search tool "
            "for performance decisions."
        ),
    )
    agent.add_argument("--search-tuning-size", type=int)
    agent.add_argument("--search-tuning-repeats", type=int, default=2)
    agent.add_argument("--search-confirmation-repeats", type=int, default=2)
    agent.add_argument("--search-holdout-repeats", type=int, default=5)
    agent.add_argument("--search-warmups", type=int, default=1)
    agent.add_argument(
        "--search-minimum-relative-improvement",
        type=float,
        default=1.05,
    )
    agent.add_argument("--search-cache-dir")
    agent.add_argument(
        "--generation-mode",
        choices=["template", "llm"],
        default="template",
    )
    agent.add_argument("--max-code-repairs", type=int, default=2)
    agent.add_argument(
        "--execution-backend",
        choices=["multiprocessing", "ray"],
        default="multiprocessing",
        help="Backend used to execute template Agent candidates.",
    )
    agent.add_argument(
        "--adapter", choices=["offline", "deepseek"], default="offline"
    )
    return parser


def main() -> None:
    args = _parser().parse_args()
    if args.command == "analyze":
        result = analyze_file(args.source).to_dict()
        text = json.dumps(result, indent=2, ensure_ascii=False)
        if args.output:
            output = Path(args.output)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(text, encoding="utf-8")
        print(text)
        return

    if args.command == "normalize-loop":
        try:
            result = normalize_serial_loop(
                args.source,
                output_path=args.output,
                metadata_path=args.metadata,
                entry_function=args.entry,
                input_factory=args.input_factory,
                equivalent_function=args.equivalent,
            )
        except LoopNormalizationError as exc:
            print(
                json.dumps(
                    {
                        "status": "rejected",
                        "reason": str(exc),
                    },
                    ensure_ascii=False,
                )
            )
            sys.exit(2)
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
        return

    if args.command == "agent-loop":
        destination = Path(args.output_dir).resolve()
        destination.mkdir(parents=True, exist_ok=True)
        normalized_path = destination / "normalized_workload.py"
        try:
            normalization = normalize_serial_loop(
                args.source,
                output_path=normalized_path,
                entry_function=args.entry,
                input_factory=args.input_factory,
                equivalent_function=args.equivalent,
            )
            adapter = (
                DeepSeekAdapter.from_env()
                if args.adapter == "deepseek"
                else None
            )
            agent_report = run_agent_pipeline(
                normalized_path,
                output_dir=destination / "agent",
                size=args.size,
                seed=args.seed,
                workers=args.workers,
                chunks=args.chunks,
                timeout_seconds=args.timeout,
                feedback_mode=args.feedback_mode,
                performance_repeats=args.performance_repeats,
                minimum_speedup=args.minimum_speedup,
                execution_backend=args.execution_backend,
                adapter=adapter,
            )
        except LoopNormalizationError as exc:
            print(
                json.dumps(
                    {"status": "rejected", "reason": str(exc)},
                    ensure_ascii=False,
                )
            )
            sys.exit(2)
        except DeepSeekConfigurationError as exc:
            print(
                json.dumps(
                    {
                        "status": "configuration_error",
                        "message": str(exc),
                    },
                    ensure_ascii=False,
                )
            )
            sys.exit(2)
        combined = {
            "status": agent_report.get("status"),
            "normalization": normalization.to_dict(),
            "agent": agent_report,
        }
        (destination / "loop_agent_report.json").write_text(
            json.dumps(combined, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(json.dumps(combined, indent=2, ensure_ascii=False))
        return

    if args.command == "benchmark":
        report = benchmark(
            args.workload,
            args.size,
            args.workers,
            args.modes,
            args.repeats,
            args.warmups,
            args.seed,
            args.output,
            args.backend,
            not args.fixed_order,
            args.ray_address,
        )
        print(json.dumps(report["summary"], indent=2, ensure_ascii=False))
        return

    if args.command == "suite":
        result = run_suite(
            args.config,
            scale=args.scale,
            workers=args.workers,
            repeats=args.repeats,
            warmups=args.warmups,
            seed=args.seed,
            backend=args.backend,
            output_dir=args.output_dir,
            randomize_order=not args.fixed_order,
            ray_address=args.ray_address,
        )
        print(json.dumps(result["manifest"], indent=2, ensure_ascii=False))
        return

    if args.command == "plot":
        result = plot_suite_results(args.suite_csv, args.output_dir)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return

    if args.command == "summarize-agent":
        rows = summarize_agent_runs(args.run_dirs, args.output)
        print(json.dumps(rows, indent=2, ensure_ascii=False))
        return

    if args.command == "plot-agent-ablation":
        output = plot_agent_ablation(args.summary_csv, args.output)
        print(json.dumps({"figure": str(output)}, ensure_ascii=False))
        return

    if args.command == "plot-agent-experiment":
        result = plot_agent_experiment(
            args.aggregate_csv, args.output_dir
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return

    if args.command == "agent-experiment":
        result = run_agent_experiment(
            args.config,
            output_dir=args.output_dir,
            adapter_name=args.adapter,
            resume=not args.no_resume,
        )
        print(json.dumps(result["manifest"], indent=2, ensure_ascii=False))
        return

    if args.command == "paired-generation-experiment":
        result = run_paired_generation_experiment(
            args.config,
            output_dir=args.output_dir,
            adapter_name=args.adapter,
            resume=not args.no_resume,
        )
        print(json.dumps(result["manifest"], indent=2, ensure_ascii=False))
        return

    if args.command == "plot-paired-generation":
        output = plot_paired_generation_experiment(
            args.summary_csv,
            args.aggregate_csv,
            args.output_dir,
        )
        print(json.dumps({"figure": str(output)}, ensure_ascii=False))
        return

    if args.command == "configuration-search":
        report = run_configuration_search(
            args.source,
            output_dir=args.output_dir,
            size=args.size,
            tuning_size=args.tuning_size,
            seed=args.seed,
            max_workers=args.max_workers,
            chunk_multipliers=args.chunk_multipliers,
            tuning_repeats=args.tuning_repeats,
            confirmation_repeats=args.confirmation_repeats,
            holdout_repeats=args.holdout_repeats,
            warmups=args.warmups,
            timeout_seconds=args.timeout,
            minimum_speedup=args.minimum_speedup,
            minimum_relative_improvement=(
                args.minimum_relative_improvement
            ),
            order_seed=args.order_seed,
            cache_dir=args.cache_dir,
        )
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return

    if args.command == "configuration-search-experiment":
        result = run_configuration_search_experiment(
            args.config,
            output_dir=args.output_dir,
            resume=not args.no_resume,
        )
        print(json.dumps(result["manifest"], indent=2, ensure_ascii=False))
        return

    if args.command == "plot-configuration-search":
        output = plot_configuration_search_experiment(
            args.aggregate_csv,
            args.overall_json,
            args.output_dir,
        )
        print(json.dumps({"figure": str(output)}, ensure_ascii=False))
        return

    if args.command == "task-fusion-experiment":
        result = run_task_fusion_experiment(
            args.config, output_dir=args.output_dir
        )
        print(json.dumps(result["overall"], indent=2, ensure_ascii=False))
        return

    if args.command == "plot-task-fusion":
        output = plot_task_fusion_experiment(
            args.summary_csv, output_dir=args.output_dir
        )
        print(json.dumps({"figure": str(output)}, ensure_ascii=False))
        return

    if args.command == "dag-scheduling-experiment":
        result = run_dag_scheduling_experiment(
            args.config, output_dir=args.output_dir
        )
        print(json.dumps(result["overall"], indent=2, ensure_ascii=False))
        return

    if args.command == "plot-dag-scheduling":
        output = plot_dag_scheduling_experiment(
            args.summary_csv, output_dir=args.output_dir
        )
        print(json.dumps({"figure": str(output)}, ensure_ascii=False))
        return

    try:
        adapter = (
            DeepSeekAdapter.from_env()
            if args.adapter == "deepseek"
            else None
        )
        report = run_agent_pipeline(
            args.source,
            output_dir=args.output_dir,
            size=args.size,
            seed=args.seed,
            workers=args.workers,
            chunks=args.chunks,
            timeout_seconds=args.timeout,
            max_repair_attempts=args.max_repairs,
            feedback_mode=args.feedback_mode,
            performance_repeats=args.performance_repeats,
            minimum_speedup=args.minimum_speedup,
            max_performance_attempts=args.max_performance_attempts,
            performance_controller=args.performance_controller,
            search_tuning_size=args.search_tuning_size,
            search_tuning_repeats=args.search_tuning_repeats,
            search_confirmation_repeats=(
                args.search_confirmation_repeats
            ),
            search_holdout_repeats=args.search_holdout_repeats,
            search_warmups=args.search_warmups,
            search_minimum_relative_improvement=(
                args.search_minimum_relative_improvement
            ),
            search_cache_dir=args.search_cache_dir,
            generation_mode=args.generation_mode,
            max_code_repair_attempts=args.max_code_repairs,
            execution_backend=args.execution_backend,
            adapter=adapter,
        )
    except DeepSeekConfigurationError as exc:
        print(json.dumps({"status": "configuration_error", "message": str(exc)}))
        sys.exit(2)
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
