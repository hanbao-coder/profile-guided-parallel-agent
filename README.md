# Profile-Guided Parallel Agent

[![First-stage verification](https://github.com/hanbao-coder/profile-guided-parallel-agent/actions/workflows/first-stage-verification.yml/badge.svg)](https://github.com/hanbao-coder/profile-guided-parallel-agent/actions/workflows/first-stage-verification.yml)

基于性能剖析与依赖分析的 Python 串行代码自动并行化研究原型。

每次推送或创建 Pull Request 时，GitHub 会在全新的 Linux / Python 3.12
环境中自动运行第一阶段验收。该流程不读取 DeepSeek Key，也不会产生 API 费用。

## 项目问题

LLM 很容易把循环改写为 `ray.remote`，但生成的代码不一定正确，也不一定
更快。本项目比较三种方法：

- **M0 Serial**：原始串行执行；
- **M1 Naive**：Agent 朴素转换，一条数据一个 Ray Task；
- **M2 Optimized**：根据试运行耗时估计任务粒度；若预测收益不足则回退
  串行，否则批量提交并行任务。

当前版本已经包含统一运行器、八类 Benchmark、正确性验证、CPU/内存采样、
AST 静态分析、Worker/Chunk 搜索、收益 Gate、性能回退，以及受控的
DeepSeek 在线代码生成与代码级修复。

当前版本在 WSL2 单节点 Ray 上完成 3 轮正式复测：8 类任务、M0/M1/M2、
每方法 5 次计时，共 360 次且全部正确。M2 预热宏平均加速为 2.406x，
性能退化率为 0%，相对 M1 的几何平均提升为 1.734x。

## 环境

推荐 Python 3.11 或 3.12。当前项目暂不支持 Python 3.13，主要是为了避免
Ray 兼容性风险。

```powershell
conda create -n parallel-agent python=3.12 -y
conda activate parallel-agent
python -m pip install -e ".[dev]"
```

## 快速验证

验收当前正式 Ray 数据、Agent–Ray 契约和完整测试（不调用 DeepSeek API）：

```powershell
python scripts/verify_research_core.py --run-tests
```

详细验收范围和结果边界见 `docs/reproducibility.md`。

运行第一次导师汇报的离线现场演示：

```powershell
python scripts/run_advisor_demo.py
```

演示顺序和讲解词见 `docs/advisor-demo.md`。

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

本机 Windows 主机名含中文，因此日常快速测试默认使用
`multiprocessing` 后端；正式 Ray 实验已转移到 WSL2 Ubuntu。Linux 或 WSL2
中可直接运行真实 Ray Task：

```bash
parallel-agent benchmark benchmarks/prime_count/workload.py \
  --size 24 --workers 4 --backend ray \
  --modes serial naive optimized \
  --output results/raw/prime_count_ray.json
```

连接已经启动的 Ray 集群时增加 `--ray-address`：

```bash
parallel-agent benchmark benchmarks/prime_count/workload.py \
  --size 24 --workers 8 --backend ray --ray-address auto \
  --modes serial naive optimized \
  --output results/raw/prime_count_cluster.json
```

结果文件包含中位运行时间、加速比、并行效率、CPU 利用率、任务数以及每次
原始测量数据。Ray 结果还记录可用节点、集群资源和任务实际执行节点；只有
至少两个不同节点真正执行过任务时，才标记为多节点执行。

复现当前首轮实验：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_first_experiment.ps1
```

首轮结果及其边界见 `docs/first-results.md`。
冷启动、热运行和自动开销标定结果见 `docs/calibrated-results.md`。
六类任务覆盖和通信代理结果见 `docs/benchmark-suite-smoke.md`。
五次重复的正式本机基线见 `docs/formal-multiprocessing-baseline.md`。
DeepSeek 首次真实闭环见 `docs/deepseek-pilot.md`。
性能反馈 Agent 与首轮消融见 `docs/performance-feedback-agent.md`。
四任务、三模式、三次独立运行的正式结果见
`docs/formal-agent-experiment.md`。
受控 LLM 代码生成、安全门与四任务预检见 `docs/controlled-llm-codegen.md`。
共享分析/计划的模板与 LLM 正式配对实验见
`docs/formal-paired-generation-experiment.md`。
多尺度 Worker/Chunk 搜索与性能回退正式实验见
`docs/formal-configuration-search.md`。
DeepSeek 分析与确定性性能搜索的端到端工具接入见
`docs/agent-performance-tool.md`。
固定配置、小样本直接决策与完整三阶段方法的正式消融见
`docs/formal-configuration-ablation.md`。
通信与复用感知任务融合实验见 `docs/task-fusion-experiment.md`。
FIFO 与通信感知关键路径 DAG 调度模型见
`docs/dag-scheduling-experiment.md`。

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

运行性能反馈组：

```powershell
parallel-agent agent benchmarks/tiny_tasks/workload.py `
  --adapter deepseek --feedback-mode performance `
  --output-dir generated/tiny_performance `
  --size 8 --workers 2 --chunks 2 `
  --performance-repeats 3 --minimum-speedup 1.05
```

让 DeepSeek 生成受控的并行实现：

```powershell
parallel-agent agent benchmarks/prime_count/workload.py `
  --adapter deepseek --generation-mode llm `
  --feedback-mode correctness `
  --output-dir generated/deepseek_llm_codegen_prime `
  --size 8 --workers 4 --chunks 4
```

模型只允许实现任务划分与并行执行两个函数。候选必须先通过 AST 语法、函数签名、
调用允许列表和危险操作检查，随后才能进入独立子进程执行与正确性验证。

当前模型路由为：分析、修复和性能决策使用 `deepseek-v4-pro`，结构化计划
使用关闭思考模式的 `deepseek-v4-flash`。这样把较高成本模型集中在真正影响
正确性与效率的环节。

运行可断点续跑的正式在线实验：

```powershell
parallel-agent agent-experiment configs/agent_experiment_formal.yaml `
  --output-dir results/raw/agent_formal_20260729 `
  --adapter deepseek
```

该实验包含调用数和 Token 双预算保护，并自动生成单次结果、分任务统计和
跨任务总体统计。

运行共享计划的模板/LLM 生成器配对实验：

```powershell
parallel-agent paired-generation-experiment `
  configs/paired_generation_formal.yaml `
  --output-dir results/raw/paired_generation_formal_20260729 `
  --adapter deepseek
```

该实验让两个生成器共享同一份分析和并行计划，并随机交错重复测量，避免把
分析差异或运行顺序误认为代码生成器差异。

运行多尺度配置搜索：

```powershell
parallel-agent configuration-search-experiment `
  configs/configuration_search_formal.yaml `
  --output-dir results/raw/configuration_search_formal_final_v2_20260729
```

该实验先在小样本上搜索 Worker/Chunk，再在完整规模上与固定配置比较，最后使用
独立留出测量报告结果。

让 DeepSeek 分析代码，并调用确定性多尺度性能工具：

```powershell
parallel-agent agent benchmarks/load_imbalance/workload.py `
  --output-dir results/raw/agent_tool_run `
  --size 64 `
  --workers 4 `
  --feedback-mode performance `
  --performance-controller configuration_search `
  --search-tuning-size 16 `
  --search-cache-dir work/configuration-search-cache `
  --adapter deepseek
```

正式实验不使用缓存；日常重复分析同一份代码、输入规模和机器环境时可使用缓存，
避免重复支付完整搜索成本。

运行通信感知任务融合实验：

```powershell
parallel-agent task-fusion-experiment configs/task_fusion_formal.yaml `
  --output-dir results/raw/task_fusion_formal
```

运行 DAG 调度模型实验：

```powershell
parallel-agent dag-scheduling-experiment configs/dag_scheduling_formal.yaml `
  --output-dir results/raw/dag_scheduling_formal
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
- 受控 LLM 代码生成已完成 4 任务、3 次独立生成的共享计划正式配对实验；
- 正式 Ray 结果已在 WSL2 单节点环境完成；真实多节点扩展性仍需要课题组或
  云端提供至少两台互通的 Linux 节点；
- AST 分析器只提供保守提示，不能替代实际正确性验证。
