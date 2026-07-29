# 相关工作核验笔记

最后核验：2026-07-29

这里只保留与当前项目设计直接相关的原始论文或官方论文页面。

## 1. ParEval

Daniel Nichols et al. “Can Large Language Models Write Parallel Code?”
HPDC 2024.

- 论文：https://arxiv.org/abs/2401.12554
- HPDC PDF：https://pssg.cs.umd.edu/assets/papers/2024-06-pareval-hpdc.pdf

核心信息：

- 提出包含 420 个任务的并行代码生成 Benchmark；
- 覆盖多类科学计算问题和多种并行编程模型；
- 并行代码生成能力明显弱于串行代码生成；
- 评价不应只看代码是否生成，还要看正确性和并行性能。

对本项目的影响：

- 同时记录可运行率、正确率、运行时间和加速比；
- 使用真实执行结果评价，不让 LLM 自己给代码打分；
- 保留不适合并行的反例。

## 2. PerfCodeGen

Yun Peng et al. “PerfCodeGen: Improving Performance of LLM Generated Code
with Execution Feedback.” 2024.

- 论文：https://arxiv.org/abs/2412.03578

核心信息：

- 将测试运行时间反馈给模型；
- 通过训练外、迭代式自我改进提高生成代码的运行效率；
- 正确代码不等于高效代码。

对本项目的影响：

- Agent 反馈不仅包含报错和正确性，还包含性能数据；
- 保留不同迭代的代码、运行时间和优化决策；
- 性能下降时自动回退。

## 3. OpenCodeInterpreter

Tianyu Zheng et al. “OpenCodeInterpreter: Integrating Code Generation with
Execution and Refinement.” Findings of ACL 2024.

- 论文：https://arxiv.org/abs/2402.14658
- 正式论文：https://aclanthology.org/2024.findings-acl.762/

核心信息：

- 将代码生成、执行和迭代修复结合；
- 使用执行反馈支持多轮代码改进。

对本项目的影响：

- 把分析、计划、代码生成、执行与修复拆成明确阶段；
- 保存结构化错误反馈；
- 限制修复轮数，避免无限循环。

## 4. Ray

Philipp Moritz et al. “Ray: A Distributed Framework for Emerging AI
Applications.” OSDI 2018.

- USENIX 页面：https://www.usenix.org/conference/osdi18/presentation/moritz
- PDF：https://www.usenix.org/system/files/osdi18-moritz.pdf

核心信息：

- 统一支持 Task 与 Actor；
- 使用动态执行引擎和分布式调度；
- 适合从单机任务并行扩展到集群。

对本项目的影响：

- 最终执行后端选择 Ray；
- Agent 负责判断任务是否提交、任务粒度和 Worker 数；
- 底层资源调度仍由 Ray 完成。

## 5. ParEval-Repo

Joshua H. Davis et al. “ParEval-Repo: A Benchmark Suite for Evaluating LLMs
with Repository-level HPC Translation Tasks.” ICPP 2025.

- 论文：https://arxiv.org/abs/2506.20938
- 正式 PDF：https://www.cs.umd.edu/~bhatele/pubs/pdf/2025/icpp2025.pdf

核心信息：

- 研究仓库级 HPC 代码翻译；
- 小程序翻译可行，但构建系统、跨文件依赖使仓库级任务明显变难；
- 评价包含可编译性、正确性、错误类型和推理 Token。

对本项目的影响：

- 20 天版本限定为单文件和小型函数契约；
- 记录 Agent 调用次数和成本；
- 仓库级转换作为未来工作，不作为当前承诺。

## 6. ParaCoder

Xiaowen Huang et al. “ParaCoder: Parallel Code Generation with Large Language
Model.” FCPC 2025.

- ACM 页面：https://doi.org/10.1145/3711708.3723442

核心信息：

- 将 Memory、Planning、Tools 和 Action 组织成并行代码生成 Agent；
- 强调并行代码生成中的规划和工具使用。

对本项目的影响：

- 使用结构化中间计划，而不是一次性直接生成代码；
- 当前版本将模型决策与确定性代码渲染器分开，便于验证与消融。

## 当前项目与相关工作的差异

当前项目不试图训练新模型，也不声称解决任意代码并行化。重点是：

> 在本科生可实现范围内，构建一个依赖感知、性能剖析驱动、能够拒绝有害
> 并行并保存完整执行证据的 Python 自动并行化 Agent。

拟验证的核心问题：

1. 执行反馈是否提高最终正确率？
2. 实测启动、调度和序列化成本能否降低性能退化率？
3. Worker/Chunk 自适应是否优于固定配置？
4. 哪类程序适合并行，哪类程序应该拒绝或回退？

