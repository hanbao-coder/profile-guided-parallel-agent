from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .analyzer import analyze_file
from .agent_ablation import (
    plot_agent_ablation,
    plot_agent_experiment,
    summarize_agent_runs,
)
from .agent_experiment import run_agent_experiment
from .agent_pipeline import run_agent_pipeline
from .deepseek_adapter import DeepSeekAdapter, DeepSeekConfigurationError
from .plotting import plot_suite_results
from .runner import benchmark
from .suite import run_suite


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="parallel-agent",
        description="Profile-guided Python-to-Ray research prototype.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    analyze = commands.add_parser("analyze", help="Run static dependency analysis.")
    analyze.add_argument("source")
    analyze.add_argument("--output")

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
            adapter=adapter,
        )
    except DeepSeekConfigurationError as exc:
        print(json.dumps({"status": "configuration_error", "message": str(exc)}))
        sys.exit(2)
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
