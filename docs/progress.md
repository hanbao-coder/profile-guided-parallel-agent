# Development log

## D1 — Project initialization

- Defined the P0 engineering boundary: Python map/reduce-style workloads, Ray Tasks,
  serial/naive/optimized comparison, correctness gate, and reproducible JSON output.
- Added the project package, CLI, AST analyzer, resource monitor, chunking heuristic,
  benchmark runner, and initial benchmarks.
- Added `prime_count`, `mandelbrot`, and the non-parallelizable `prefix_sum` case.
- Current machine uses Python 3.13 and does not yet have Ray. The project targets
  Python 3.11/3.12 for a stable Ray environment.
- Created an isolated Python 3.12 environment and installed Ray 2.56.1. Ray's
  Windows runtime crashes on this machine's non-ASCII hostname, so local
  experiments use the interchangeable multiprocessing backend.
- First repeatable measurements: prime counting reached 1.51x speedup with four
  processes. For 1,000 tiny tasks, naive parallelism took 0.378 s versus
  0.100 s serial. The optimized benefit gate rejected parallelism and completed
  in 0.100 s.
- Added a measured process-startup cost and benefit gate so M2 can fall back to
  serial when parallelism is not predicted to pay off.

## Next

## D2 — Calibrated execution model

- Separated worker cold start, warm execution, and total runtime.
- Automatically calibrated process startup and empty-task scheduling cost.
- Added candidate search across 1/2/4 workers and 1/2/4/8 chunks per worker.
- Prime Count selected 4 workers and 4 chunks; warm speedup was about 4.08x and
  end-to-end speedup was about 1.55x.
- Tiny Tasks rejected parallel execution and fell back to serial.
- Expanded the suite to 10 passing tests.

## Next

## D3 — Benchmark and communication coverage

- Added Word Count, Monte Carlo Pi, and Pairwise Distance.
- Defined Small/Large configurations for six runnable benchmark families.
- Added input/output serialization size and proxy-time measurements.
- Added one-command suite execution with per-case JSON and aggregate CSV.
- Fixed an invalid Mandelbrot row-coordinate definition discovered by the suite.
- Completed both Small and Large smoke suites with correct outputs.
- Expanded the suite to 13 passing tests.

## Next

## D4 — Agent minimum viable loop

- Defined versioned analysis and parallel-plan artifacts with JSON Schemas.
- Added a deterministic offline Agent adapter.
- Added deterministic candidate-code generation.
- Added subprocess execution, timeout, stdout/stderr capture, and correctness gate.
- Added structured repair feedback and bounded repair attempts.
- Prime Count was accepted; Prefix Sum was rejected before generation.
- Added a deliberate child-process failure test to verify repair logging.
- Expanded the suite to 16 passing tests.

## Next

1. Configure a real model API without storing secrets in the repository.
2. Implement an online structured-output adapter.
3. Evaluate offline rules, one-shot LLM, and feedback Agent.

## First advisor-report preparation

- Re-verified ParEval, PerfCodeGen, OpenCodeInterpreter, Ray, ParEval-Repo, and
  ParaCoder against primary paper sources.
- Prepared the first written progress report.
- Prepared an 8–10 minute oral outline, likely questions, and a contact message.
- The report will be refreshed immediately before the planned August 2 update.

## D5 — Formal local baseline

- Randomized M0/M1/M2 execution order with a reproducible seed.
- Added median, quartiles, IQR, cold/warm/total runtime, and environment metadata.
- Limited BLAS/OpenMP internal threads to one.
- Ran all six Large benchmarks with one warm-up and five measured repetitions.
- Prime Count M2 reached 1.92x median end-to-end speedup.
- Monte Carlo M2 reached 1.12x median end-to-end speedup.
- Four other workloads selected serial fallback and avoided severe M1 regressions.
- Updated the first advisor report with repeated measurements.

## D6 — Online DeepSeek pilot and report figures

- Connected the DeepSeek OpenAI-compatible API through a local `.env`.
- Completed the first real analyze/plan/generate/execute correctness loop.
- Prime Count serial and generated parallel candidates both returned `1767`.
- The candidate passed on the first execution attempt with no repair required.
- Recorded two model calls and 1,554 total tokens.
- Verified that the API key appears zero times in generated artifacts.
- Observed one empty-rationale structured-output failure and added a
  deterministic safe fallback plus a regression test.
- Added report-ready runtime, speedup, and benefit-gate decision figures.
- Expanded the automated suite to 22 passing tests.

## D7 — Three-case online Agent coverage

- Prefix Sum was conservatively rejected because of a true loop-carried
  dependency.
- Found and fixed a false positive where local state inside `unit()` was
  confused with cross-item state.
- Tiny Tasks then passed correctness while demonstrating a clear performance
  regression for naive process parallelism.
- Rejection paths now preserve model traces.
- Three current online cases contain five logged calls and 4,556 tokens.
- Expanded the automated suite to 23 passing tests.

## Next

1. Run the same online Agent protocol on safe, unsafe, and fine-grained cases.
2. Define one-shot LLM and feedback-Agent experiment groups.
3. Add Agent-call/token/repair metrics to the aggregate experiment table.
4. Refresh the August 2 advisor report immediately before sending.

## D8 — Performance-feedback Agent prototype

- Added one-shot, correctness-feedback, and performance-feedback modes.
- Added randomized repeated end-to-end candidate measurements.
- Added a 1.05x minimum-benefit gate and measured serial fallback.
- Routed analysis/repair/performance decisions to DeepSeek V4 Pro and routine
  plan formatting to V4 Flash.
- Disabled thinking mode and reduced output budget for Flash planning.
- Routing smoke test: Flash planning used 98 completion tokens versus 884 in
  an earlier default-thinking planning call; inputs were similar but not
  identical, so this is a configuration check rather than a formal cost result.
- Tiny Tasks: one-shot 0.45x, correctness feedback 0.46x, performance feedback
  candidate 0.47x followed by serial fallback (effective 1.00x).
- Prime Count Large: performance feedback retained parallel execution at 1.78x.
- Added automatic ablation CSV aggregation and a report figure.
- Expanded the automated suite to 28 passing tests.

## D9 — Formal online Agent ablation

- Added a resumable multi-workload experiment runner with call/token budgets.
- Added equal three-repeat measurements to every feedback group.
- Added uncertainty-aware benefit gating using median and Q1/Q3 runtimes.
- Ran 4 workloads × 3 modes × 3 independent model runs (36 jobs).
- All 36 jobs were correct; no model, execution, or budget failures.
- One-shot and correctness feedback each had 50% performance regression.
- Performance feedback reduced regression to 0% and increased macro effective
  speedup from about 1.08x to 1.27x.
- Logged 81 model calls and 79,659 tokens; conservative API cost upper bound was
  about USD 0.047.
- Added per-run, per-workload, and overall CSV statistics plus three verified
  report figures.
- Expanded the automated suite to 29 passing tests.

## D10 — Controlled LLM code generation

- Replaced template-only candidate generation with an optional controlled LLM
  implementation mode.
- Restricted generated code to task partitioning and process execution functions
  inside a trusted candidate scaffold.
- Added AST signature, import, call allowlist, and dangerous-operation checks
  before candidate execution.
- Added bounded code-level repair for safety, runtime, and correctness failures.
- In a real Prime Count run, the safety gate rejected a non-allowlisted `divmod`
  call; DeepSeek repaired the implementation and produced the correct result.
- Completed a four-workload preflight: template and LLM generation were both
  4/4 correct with no final failures.
- The template group used 8 calls and 7,762 tokens; the LLM group used 15 calls
  and 22,832 tokens, including earlier invalid/empty response retries.
- Disabled thinking mode for code generation and repair after calibration; the
  resumed workloads then produced valid code in one generation call.
- Expanded the automated suite to 37 passing tests.

## D11 — Shared-plan paired generator experiment

- Added a paired experiment protocol where template and LLM candidates share
  exactly the same analysis artifact and parallel plan.
- Added randomized interleaved Serial/Template/LLM measurements with warm-ups,
  repeated medians, quartiles, budgets, failure artifacts, and resume support.
- Found that result equality alone was insufficient: a Tiny Tasks candidate
  returned the item count instead of the submitted task count.
- Added a task-count semantic gate and demonstrated a real DeepSeek repair.
- Ran 4 workloads × 3 independent generations (12 paired jobs).
- Template generation was correct in 12/12 jobs; controlled LLM generation was
  correct in 11/12.
- The LLM had a 1.021x macro runtime ratio over template among measured pairs,
  but only 3/11 comparisons remained favorable under Q1/Q3 conservative bounds.
- LLM code generation and repair consumed 16,978 incremental tokens and required
  8 repairs; one Pairwise Distance candidate remained incorrect after two repairs.
- Added a report-ready paired reliability/performance figure.
- Expanded the automated suite to 41 passing tests.

## D12 — Multi-scale configuration search

- Added a measured grid search across 1/2/4 workers and 1/2/4 chunks per worker.
- Separated tuning measurements from five-repeat holdout evaluation.
- Added full-scale confirmation to prevent unsafe extrapolation from small inputs.
- Added a 5% relative-improvement gate against the fixed 4/4 baseline.
- Added result fingerprints and task-count semantic validation without storing
  multi-megabyte outputs in experiment reports.
- Added Load Imbalance and Large Payload boundary benchmarks.
- Ran 8 workloads × 3 independent runs (24 jobs), with no execution failures.
- Fixed 4/4 parallelism regressed in 62.5% of runs; adaptive selection regressed
  in 0% and increased macro effective speedup from 0.965x to 1.186x.
- Load Imbalance improved by 1.315x over fixed configuration on average.
- Large Payload selected serial and was 2.231x faster than fixed parallelism.
- Added explicit search-cost amortization against serial and fixed baselines.

## D13 — Agent-controlled deterministic performance tool

- Added `performance_controller=configuration_search` to the end-to-end Agent.
- DeepSeek Pro handles code analysis and Flash produces the structured plan.
- Worker/Chunk decisions come from measured multi-scale search instead of model
  guesses.
- Added cache keys over source, scale, thresholds, Python, and machine environment.
- Formal experiments leave the cache disabled; repeated deployment runs may reuse it.
- A real DeepSeek smoke run on Load Imbalance selected 4 workers / 8 chunks:
  - adaptive holdout speedup: 1.108x;
  - fixed configuration speedup: 0.861x;
  - adaptive-over-fixed ratio: 1.286x;
  - final independent validation: 1.117x with correct output.
- The model made two text-only calls and consumed 2,115 tokens.

## D14 — Formal configuration-search ablation

- Extended every holdout schedule to evaluate fixed, small-sample-only, and
  full three-stage decisions on the same measurements.
- Ran 8 workloads × 3 independent runs with no failed jobs.
- Fixed 4/4 achieved 0.926x macro speedup and regressed in 70.8% of runs.
- Small-sample-only selection achieved 1.000x with no regressions, but selected
  serial in all 24 runs and missed useful parallelism.
- Full-scale confirmation recovered profitable parallelism in 7/24 runs,
  reached 1.149x macro speedup, and kept the regression rate at 0%.
- Small-sample search averaged 6.12 seconds per job; scale confirmation added
  2.42 seconds per job.
- Added a three-way report figure and versioned paired holdout data.

## D15 — Communication- and reuse-aware task fusion

- Added explicit single-consumer chain and shared-heavy-fanout DAG workloads.
- Added unfused, fixed edge-fusion, and communication-aware strategies.
- Reused one warmed process pool and randomized five repeated measurements to
  isolate task-fusion effects from process cold start.
- The single-consumer chain eliminated 8.0 MiB of intermediate transfer, reduced
  task count from 16 to 8, and achieved 22.02x over unfused execution.
- Fixed edge fusion duplicated the heavy producer in the fanout case and fell
  to 0.545x; the aware policy preserved producer reuse and avoided that regression.
- All strategies matched the serial golden output.
- Added versioned raw reports, a comparison figure, and 3 automated tests.
- Expanded the automated suite to 51 passing tests.

## D16 — Communication-aware critical-path DAG scheduling

- Added a deterministic homogeneous-worker list-scheduling model.
- Compared FIFO with upward-rank critical-path priority including edge
  communication estimates.
- Added compute-critical and communication-critical DAGs.
- Compute-critical makespan fell from 2.18 to 1.85 modeled seconds (1.178x);
  idle ratio fell from 35.6% to 24.1%.
- Communication-critical makespan fell from 0.98 to 0.78 modeled seconds
  (1.256x); idle ratio fell from 39.8% to 24.4%.
- Renamed the upward-rank field to avoid presenting it as a makespan lower bound.
- Added versioned schedules, a comparison figure, and 3 automated tests.
- Expanded the automated suite to 54 passing tests.
