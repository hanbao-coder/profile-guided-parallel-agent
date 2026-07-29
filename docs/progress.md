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
