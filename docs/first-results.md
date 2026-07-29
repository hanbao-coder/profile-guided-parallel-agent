# First experiment report

Date: 2026-07-29

Environment: Windows, Python 3.12.13, 4 worker processes. Each reported runtime
is the median of three measured runs after one warm-up.

## Results

| Workload | Method | Median time (s) | Speedup | Tasks | Decision |
|---|---|---:|---:|---:|---|
| Prime Count | M0 Serial | 0.379 | 1.00x | 1 | serial baseline |
| Prime Count | M1 Naive | 0.261 | 1.45x | 16 | parallel |
| Prime Count | M2 Optimized | 0.251 | 1.51x | 16 | parallel |
| Tiny Tasks | M0 Serial | 0.100 | 1.00x | 1 | serial baseline |
| Tiny Tasks | M1 Naive | 0.378 | 0.27x | 1000 | harmful parallelism |
| Tiny Tasks | M2 Optimized | 0.100 | 1.01x | 1 | serial fallback |

Raw measurements are stored under `results/raw/`.

## What this establishes

1. Parallel execution can improve a sufficiently coarse CPU-bound workload.
2. A correct parallel program can still be much slower than serial execution.
3. Task count is a useful explanation variable: 1,000 tiny tasks created enough
   scheduling and process overhead to make M1 about four times slower.
4. The profile-guided benefit gate rejected that harmful parallelization and
   returned to serial execution, while retaining parallel execution for Prime
   Count.
5. The prefix-sum example is independently rejected by static analysis because
   it reads values written by earlier loop iterations.

## Important caveat

These are engineering smoke-test results, not final research results. The next
experiment must separate cold startup from warm execution, calibrate task
overhead, expand the benchmark suite, and randomize method order.
