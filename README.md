# Profile-Guided Parallel Agent

基于性能剖析与依赖分析的 Python 串行代码自动并行化研究原型。

## 项目问题

LLM 很容易把循环改写为 `ray.remote`，但生成的代码不一定正确，也不一定
更快。本项目比较三种方法：

- **M0 Serial**：原始串行执行；
- **M1 Naive**：Agent 朴素转换，一条数据一个 Ray Task；
- **M2 Optimized**：根据试运行耗时估计任务粒度；若预测收益不足则回退
  串行，否则批量提交并行任务。

当前版本已经包含统一运行器、六类 Benchmark、正确性验证、CPU/内存采样、
AST 静态分析、Worker/Chunk 搜索、收益 Gate、性能回退、代码生成与
DeepSeek 在线 Agent。

## 环境

推荐 Python 3.11 或 3.12。当前项目暂不支持 Python 3.13，主要是为了避免
Ray 兼容性风险。

```powershell
conda create -n parallel-agent python=3.12 -y
conda activate parallel-agent
python -m pip install -e ".[dev]"
```

## 快速验证

运行测试：

```powershell
pytest -q
```

分析存在前缀依赖的程序：

```powershell
parallel-agent analyze benchmarks/prefix_sum/serial.py `
  --output results/raw/prefix_sum_analysis.json
```

只运行串行基线（无需 Ray）：

```powershell
parallel-agent benchmark benchmarks/prime_count/workload.py `
  --size 8 --workers 4 --modes serial `
  --output results/raw/prime_serial.json
```

运行完整三组对照：

```powershell
parallel-agent benchmark benchmarks/prime_count/workload.py `
  --size 24 --workers 4 --backend multiprocessing `
  --modes serial naive optimized `
  --output results/raw/prime_count.json
```

本机主机名含中文，而当前 Ray Windows 运行时无法处理该主机名，所以开发期
默认使用与 Ray Task 语义一致的 `multiprocessing` 后端完成正确性和性能实验。
在英文主机名的 Windows 或 Linux 环境中，将参数改为 `--backend ray` 即可。

结果文件包含中位运行时间、加速比、并行效率、CPU 利用率、任务数以及每次
原始测量数据。

复现当前首轮实验：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_first_experiment.ps1
```

首轮结果及其边界见 `docs/first-results.md`。
冷启动、热运行和自动开销标定结果见 `docs/calibrated-results.md`。
六类任务覆盖和通信代理结果见 `docs/benchmark-suite-smoke.md`。
五次重复的正式本机基线见 `docs/formal-multiprocessing-baseline.md`。
DeepSeek 首次真实闭环见 `docs/deepseek-pilot.md`。

从正式实验 CSV 生成汇报图：

```powershell
parallel-agent plot results/raw/formal_mp_large/suite_large.csv `
  --output-dir docs/assets/formal_mp_large
```

一次运行配置中的全部 Benchmark：

```powershell
parallel-agent suite --config configs/benchmarks.yaml --scale small `
  --workers 4 --backend multiprocessing --repeats 3 --warmups 1 `
  --output-dir results/raw/suite_small
```

运行 Agent 最小闭环：

```powershell
parallel-agent agent benchmarks/prime_count/workload.py `
  --output-dir generated/prime_agent --size 4 `
  --workers 2 --chunks 2
```

它会生成 `analysis.json`、`parallel_plan.json`、`candidate.py` 和
`run_report.json`。详细说明见 `docs/agent-mvp.md`。

使用 DeepSeek 在线 Agent：

1. 将 `.env.example` 复制为 `.env`；
2. 在本机 `.env` 中填写 `DEEPSEEK_API_KEY`；
3. 不要提交或分享 `.env`；
4. 运行：

```powershell
parallel-agent agent benchmarks/prime_count/workload.py `
  --adapter deepseek --output-dir generated/deepseek_prime `
  --size 2 --workers 2 --chunks 2
```

如果第一次接触科研项目，请从以下两份文档开始：

- `docs/project-control.md`：当前阶段、下一节点和汇报时间；
- `docs/user-actions.md`：只有必须由本人完成的事项才会出现在这里。

第一次导师汇报材料：

- `docs/advisor-report-01.md`：书面进展报告；
- `docs/advisor-talk-01.md`：8～10 分钟口头提纲与问答；
- `docs/advisor-message-01.md`：联系导师的消息；
- `docs/literature-notes.md`：已核验的论文依据。

## 当前目录

```text
benchmarks/        可复现实验程序
configs/           实验配置
docs/              开发日志和汇报材料
src/parallel_agent 分析、剖析、执行与优化逻辑
tests/             自动化测试
results/           实验原始数据、表格和图片
```

## 当前限制

- 目前只支持符合 `make_input/unit/combine/equivalent` 接口的基准程序；
- 当前代码生成依赖显式函数契约，还不是任意 Python 源码重构；
- 在线 Agent 尚未完成多任务、多次独立运行的正式实验；
- 本机 Ray 受中文主机名兼容问题影响，正式 Ray 结果仍需 Linux 环境；
- AST 分析器只提供保守提示，不能替代实际正确性验证。
