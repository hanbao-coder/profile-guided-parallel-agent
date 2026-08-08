# Project-Level Parallelization Agent

本项目研究一个具体问题：通用代码 Agent 直接把真实的多文件 Python 项目并行化时，为什么
经常得到“有并行语法，但项目不能用或整体没有变快”的结果？

当前观点是：项目级自动并行化不应只做一次代码生成，而应成为一个**允许拒绝候选的决策过程**。
Agent 需要检查源码位置、共享状态和输出语义，并用原项目测试、固定输出及配对性能测量决定
是否保留修改；证据不合格时恢复串行版本。

当前代码版本：`v0.23.2-repository-study`。

## 当前实验结论

主实验覆盖 Radon、Vulture、Chardet 和 MkDocs 四个真实开源项目，每种方法独立运行 12 次：

| 方法 | 有效并行 | 安全回退 | 错误修改 | 未形成方案 |
|---|---:|---:|---:|---:|
| 普通 Agent | 0 | 0 | 6 | 6 |
| 完整方法 | 1 | 10 | 0 | 1 |

完整方法在 Chardet 上有 1 次得到 3.251 倍端到端加速。其余大部分运行选择回退，说明当前
方法主要改善的是交付安全性，还不能稳定完成自动加速。详细结果见
[M6 真实项目实验发现](docs/m6-findings.md)。

后续 Radon 实验尝试加入 Worker 边界检查：它在 2 次运行中发现 3 个复杂状态跨进程风险，
但 3/3 最终仍回退，没有提高正确候选率或有效并行率。这个负结果见
[M7 Worker 边界实验](docs/m7-worker-boundary-design.md)。

![主实验结果](docs/figures/m6-overall-outcomes.png)

## 方法流程

```text
固定串行项目
  → 运行原测试、固定工作负载和串行计时
  → Agent 阅读入口、调用关系和状态
  → 生成任务边界与语义约束
  → 生成候选并行修改
  → 项目测试、固定输出和端到端性能检查
  → 合格则保留；不合格则修复，仍失败就恢复串行代码
```

有效并行化必须同时满足：原项目测试通过、固定输出一致、存在实际并行结构、端到端中位加速
至少 1.05 倍。只让某个内部函数变快不算成功。

## 从哪里开始阅读

- [方法说明](docs/method.md)：系统为什么这样设计；
- [实验设计与结果](docs/experiments.md)：项目、对照组、指标和真实数字；
- [相关工作](docs/related-work-project-level-parallelization.md)：论文与本项目的区别；
- [当前局限](docs/limitations.md)：哪些结论现在还不能说；
- [Worker 边界负结果](docs/m7-worker-boundary-design.md)：一个被真实实验否定的后续假设；
- [复现说明](docs/reproducibility.md)：环境与运行入口；
- [研究日志](docs/research-log.md)：问题发现、协议修正和方向变化。

## 环境

项目使用 Python 3.10～3.12。当前本机已经配置仓库专用环境，Python 位于
`.venv/python.exe`。在新的 Windows 环境中可使用 Conda：

```powershell
conda create -n parallel-agent python=3.12 -y
conda activate parallel-agent
python -m pip install -e ".[dev]"
```

DeepSeek Key 只保存在本机 `.env`，不进入 Git。

## 快速检查

不调用 DeepSeek，只检查项目代码：

```powershell
.\.venv\python.exe -m pytest -q
```

从本机原始实验重新生成紧凑结果和中文图表：

```powershell
.\.venv\python.exe scripts\summarize_m6_study.py
```

原始实验体积较大，默认只保存在本机 `results/`。Git 仓库保存汇总脚本、紧凑 JSON/CSV、
中文图表和研究文档。

## 主要目录

```text
configs/             四个真实项目的固定命令和上下文
src/parallel_agent/  仓库 Agent、验证与性能反馈实现
scripts/             实验、汇总和验收入口
tests/               本项目自动测试
docs/                方法、实验、相关工作、局限和研究日志
docs/data/           可提交的紧凑实验结果
docs/figures/        由紧凑结果生成的中文图表
results/             本机原始实验记录
work/                固定源码副本和隔离环境
```

## 研究边界

- 当前研究单机 CPU 并行，不声称完成真实多节点扩展；
- 主实验只有 4 个项目，每种方法 12 次运行；
- 安全回退不等于并行化成功；
- 现有测试和固定输出不能证明全部输入上的语义完全一致；
- 旧的单文件 Ray、任务融合和 DAG 调度代码只作为历史实验工具，不作为当前研究贡献。
