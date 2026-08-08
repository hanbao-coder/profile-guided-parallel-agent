# 相关工作：Agent 驱动的项目级自动并行化

## 1. 调研目的

本文档不把论文按标题简单罗列，而是比较已有研究分别解决了什么，以及项目级自动
并行化还缺少哪些证据。M6 诊断后，研究问题已经收敛为：通用代码 Agent 在真实
多文件项目中为什么容易生成“有并行语法但不可交付”的修改，以及怎样用项目测试、
固定输出、配对性能反馈和安全回退降低错误交付。后续 M7 曾计划检验 Worker 边界证据能否
提高正确候选的生成概率，但其 Radon 人工性能参考未能在固定协议下复现，因此该实验按前提
失效终止。

## 2. 核心工作对照

| 工作 | 研究对象 | 主要方法与指标 | 与本项目的关系 | 尚未覆盖 |
|---|---|---|---|---|
| ParEval（HPDC 2024） | 420个独立并行编程任务 | 比较正确率、加速比和并行效率 | 证明并行代码必须真实运行和测性能 | 不研究多文件项目的修改和集成 |
| ParEval-Repo（2025） | 仓库级HPC/GPGPU代码迁移 | 构建、正确性、错误类型和Token | 说明仓库扩大后构建和跨文件依赖变难 | 重点是执行模型翻译，不是从串行项目发现并行机会 |
| CodeAgent（ACL 2024） | 真实仓库代码生成 | 检索、实现、测试工具组成Agent | 说明仓库任务需要主动找文件并执行验证 | 不专门研究并行正确性和性能 |
| RepoExec（NAACL 2025） | 仓库级代码生成上下文 | 可执行性、功能正确性、依赖利用 | 说明不完整上下文会误导代码生成 | 不回答并行修改需要哪些运行证据 |
| PerfCodeGen（2024） | 通用Python代码性能优化 | 正确性门控后反馈真实运行时间 | 支持“运行后再优化”的闭环 | 不处理项目级并行区域选择和跨文件集成 |
| SWE-Perf（2025） | 140个真实仓库性能优化任务 | 专家补丁、性能测试和可执行环境 | 证明仓库级性能优化明显难于普通修复 | 任务不要求使用并行化，也不分析串行到并行的失败 |
| SWE-efficiency（ICML 2026） | 9个大型Python仓库中的498个任务 | 真实工作负载、守护测试、专家加速比 | 提供端到端性能和专家上界的严格评价方法 | 优化手段开放，不专门研究并行语义和并行开销 |
| FormulaCode（2026） | 70个科学Python仓库中的957个瓶颈 | 多工作负载、专家补丁、多目标指标 | 说明真实仓库需要细粒度、连续性能评价 | 关注一般性能优化，不限定串行到并行转换 |
| PEACE（2025） | 47个Python项目中的146个优化任务 | 依赖感知的多函数混合编辑 | 与跨函数项目优化直接相关 | 目标是一般代码编辑，不研究任务拆分、共享状态和并行执行 |
| PerfAgent（2026） | GSO和SWE-efficiency-Lite仓库优化任务 | 剖析摘要、选择性测试、最多5轮再优化 | 已经验证“热点剖析+验证闭环”能够改善仓库优化 | 不专门解决串行项目并行化的安全边界和并行收益 |
| Profile-driven auto-parallelization（PLDI 2009） | 传统编译器自动并行化 | 静态分析结合性能剖析 | 说明静态安全与实际收益需要同时考虑 | 不使用LLM，也不处理Agent修改过程 |
| AutoTornado（2022） | Java循环自动并行化 | 依赖与纯函数分析 | 提供保守安全判断思路 | 主要是循环级，不是仓库级 |
| Ray（OSDI 2018） | 分布式任务与Actor执行 | 动态任务图、调度和对象存储 | 可作为生成代码的执行后端 | 不负责判断项目哪里应该并行 |

## 3. 已有工作能够支持的事实

### 3.1 并行代码评价不能只看能否生成

ParEval 同时评价正确性和性能，说明“生成了并行语法”并不等于“得到了有效并行
程序”。本项目因此把有效并行化定义为：项目可运行、输出正确、端到端性能至少提高
预设阈值。

### 3.2 仓库级修改比独立函数更依赖上下文

ParEval-Repo、CodeAgent 和 RepoExec 从不同角度说明，仓库级任务需要处理构建、
入口、检索和跨文件依赖。只向模型提供孤立函数可能漏掉调用方和状态；把整个仓库
不加选择地放进上下文，也不代表模型一定能找到真正相关内容。

### 3.3 代码性能需要用真实执行反馈判断

PerfCodeGen 先通过正确性检查，再把实际运行时间用于后续修改。传统
profile-guided auto-parallelization 也表明，静态依赖安全与运行收益是两个不同
问题。一个区域可以安全并行，不代表它值得并行。

### 3.4 执行框架不是研究问题本身

Ray 提供并行任务执行能力，但它不会替 Agent 判断修改哪个模块、如何保持原项目
语义，以及修改是否改善端到端时间。本项目使用 Ray 作为候选后端，不把修改 Ray
调度器作为目标。

### 3.5 “给 Agent 热点信息”已经不能单独作为创新

2026年7月发布的 PerfAgent 已经系统实现了仓库级性能剖析引导：它向普通代码
Agent提供经过整理的热点、调用上下文和运行占比，在每轮修改后重新构建、验证和
剖析，并保留最快的正确补丁。论文报告其专家水平补丁比例在 GSO 上从 19.6%
提高到39.2%，在 SWE-efficiency-Lite 上从26%提高到74%。

因此，本项目不能仅仅把“运行 cProfile 后把热点发给模型”写成研究贡献。性能
剖析可以作为诊断工具或方法中的一部分，但最终问题必须体现串行到并行转换特有的
困难。

### 3.6 真实仓库性能基准为实验设计提供了更高标准

SWE-efficiency 的公开说明显示，其498个任务来自 NumPy、Pandas、SciPy、
Scikit-learn、Matplotlib、Xarray、SymPy、Dask和Astropy，并为每个任务提供完整
代码库、性能工作负载和需要保持通过的仓库测试。它还区分专家加速和模型加速，
明确统计错误补丁、正确但无加速补丁和达到专家水平的补丁。

FormulaCode、SWE-Perf和PEACE也都使用真实仓库、专家修改或可执行环境。这说明
本项目如果只使用自己编写的单文件算法，将无法充分支持“项目级”结论。因此主实验
最终使用四个固定版本的真实开源项目，并保留原项目测试和完整工作负载。

## 4. 诊断后仍缺少的研究证据

现有工作已经研究了一般仓库性能优化、热点剖析反馈和依赖感知编辑。M6 进一步观察到：
普通 Agent 的 12 次项目级并行化中有 6 次留下错误修改，另 6 次没有形成可用方案；错误并不
只来自某一种语法或调度策略，而是分布在项目测试、最终输出、真实并行结构和端到端收益多个
阶段。

因此当前空白不再表述为“尚不知道会不会失败”，而是：

> 面向串行项目到并行项目的结构性修改，仍缺少一种把候选生成和证据门控明确分开的 Agent
> 流程：候选只有同时满足项目测试、固定输出、真实并行和端到端收益时才交付，否则允许拒绝
> 修改并保留串行版本。

这一问题与一般性能优化不同。并行补丁可能退出码正常、耗时很短，却通过错误聚合或吞掉子进程
异常得到错误输出；也可能局部变快但整体变慢。因此模型自评或单项测试不足以支持交付决定。

## 5. 当前研究问题、假设和观点

### 研究问题

在固定模型、项目、工具和运行次数的条件下，加入项目语义约束、真实执行反馈和安全回退，能否
降低普通 Agent 自动并行化真实项目时的错误交付率，同时保留能够通过端到端验证的有效候选？

### 可否定假设

如果证据门控和回退确实有作用，那么 B2 的错误交付率应低于 B1；若 B2 仍频繁保留测试失败、
输出错误或性能退化的补丁，假设被否定。有效并行成功率单独统计，不能把回退算作成功。

### 核心观点

> 项目级自动并行化不是一次性生成并行语法，而是带拒绝选项的决策过程。项目测试、固定输出
> 和配对端到端性能共同决定候选是否值得交付；证据不合格时保留串行版本更可靠。

## 6. 当前事实与尚未验证部分

### 已验证事实

- B1 普通 Agent：12 次中 6 次错误交付，6 次未形成方案，0 次有效并行；
- B2 完整方法：1 次有效并行、10 次安全回退、1 次未形成方案，0 次已知错误交付；
- B2 共检查 30 个候选，其中 17 个测试失败、4 个输出或集成失败、3 个没有实际并行、
  3 个收益不足 5%、2 个整体变慢、1 个被接受；
- MkDocs 的 A1 小规模消融中，单独增加语义约束没有消除错误修改；加入执行反馈和回退后，
  3 个不合格候选均未被交付；
- 这些事实支持“执行证据和拒绝选项降低了当前样本中的错误交付”，不支持“已经能稳定自动加速”。

### 尚未验证或证据不足

- 主实验只有四个项目，不能估计所有 Python 项目的平均成功率；
- 完整方法同时改变多个环节，MkDocs 每组只有 3 次，不能精确分离每个组件的因果贡献；
- Radon 的 Worker 边界检查只完成 2 次有效探索运行；随后人工性能参考被固定协议否定，故该
  支线终止，不能判断它是否能提高有效加速成功率；
- 现阶段只验证 Windows 单机 CPU 进程/线程，不外推到多节点网络和 GPU。

## 7. 核心参考文献

1. Nichols et al. *Can Large Language Models Write Parallel Code?*
   HPDC 2024. https://doi.org/10.1145/3625549.3658689
2. Davis et al. *ParEval-Repo: A Benchmark Suite for Evaluating LLMs
   with Repository-level HPC Translation Tasks.* 2025.
   https://arxiv.org/abs/2506.20938
3. Peng et al. *PerfCodeGen: Improving Performance of LLM Generated
   Code with Execution Feedback.* 2024.
   https://arxiv.org/abs/2412.03578
4. Zhang et al. *CodeAgent: Enhancing Code Generation with
   Tool-Integrated Agent Systems for Real-World Repo-level Coding
   Challenges.* ACL 2024.
   https://aclanthology.org/2024.acl-long.737/
5. Hai et al. *On the Impacts of Contexts on Repository-Level Code
   Generation.* Findings of NAACL 2025.
   https://aclanthology.org/2025.findings-naacl.82/
6. Tournavitis et al. *Towards a Holistic Approach to
   Auto-Parallelization: Integrating Profile-Driven Parallelism
   Detection and Machine-Learning Based Mapping.* PLDI 2009.
   https://doi.org/10.1145/1543135.1542496
7. Sharma et al. *Can We Run in Parallel? Automating Loop
   Parallelization for TornadoVM.* 2022.
   https://arxiv.org/abs/2205.03590
8. Moritz et al. *Ray: A Distributed Framework for Emerging AI
   Applications.* OSDI 2018.
   https://www.usenix.org/conference/osdi18/presentation/moritz
9. He et al. *SWE-Perf: Can Language Models Optimize Code Performance
   on Real-World Repositories?* 2025.
   https://arxiv.org/abs/2507.12415
10. Ma et al. *SWE-efficiency: Can Language Models Optimize Real-World
    Repositories on Real Workloads?* ICML 2026.
    https://arxiv.org/abs/2511.06090
11. Sehgal et al. *FormulaCode: Evaluating Agentic Optimization on
    Large Codebases.* 2026.
    https://arxiv.org/abs/2603.16011
12. Ren et al. *PEACE: Towards Efficient Project-Level Efficiency
    Optimization via Hybrid Code Editing.* 2025.
    https://arxiv.org/abs/2510.17142
13. Deng et al. *PerfAgent: Profiler-Guided Iterative Refinement for
    Repository-Level Code Optimization.* 2026.
    https://arxiv.org/abs/2607.19653
