# 共享计划的模板/LLM 生成器正式配对实验

日期：2026-07-29

## 1. 研究问题

受控 LLM 代码生成已经能够输出正确候选，但此前模板组与 LLM 组分别调用模型
进行分析和规划，因此性能差异可能来自不同的并行计划，而不是代码生成器本身。

本实验回答：

> 在共享完全相同的代码分析和并行计划时，让 LLM 自由实现任务划分与并行执行，
> 是否比确定性模板更正确、更快，代价是多少？

## 2. 控制变量

每一对候选共享：

- 同一份 `analysis.json`；
- 同一份 `parallel_plan.json`；
- 相同 Worker 和 Chunk 数量；
- 相同输入规模、随机种子和超时；
- 相同可信执行脚手架；
- 相同结果与任务数语义检查。

唯一变化是：

- Template：使用确定性规范实现；
- Controlled LLM：DeepSeek V4 Pro 生成两个受控函数，错误时最多修复两轮。

正式实验覆盖 Prime Count、Tiny Tasks、Word Count 和 Pairwise Distance。每个任务
独立生成 3 次，共 12 对；每对预热 1 次，并把 Serial、Template Parallel 和
LLM Parallel 各重复 3 次，按固定种子随机化执行顺序。

## 3. 新增的任务数语义门

真实预检中，Tiny Tasks 的模型代码虽然输出数值正确，却把 `task_count` 返回为
数据项数量 200，而实际只提交约 4 个进程任务。如果不检查该字段，后续任务粒度、
调度开销和通信分析都会被污染。

系统现在同时要求：

1. 串行与并行最终结果一致；
2. `task_count` 必须是整数；
3. `1 <= task_count <= configured_chunks`。

该错误被自动反馈给 DeepSeek，修复后的候选通过验证。这说明科研代码不能只检查
最终数值，还必须检查用于量化分析的元数据语义。

## 4. 正式结果

| Workload | Template 正确率 | LLM 正确率 | LLM/Template 运行比 | LLM 胜率 |
|---|---:|---:|---:|---:|
| Pairwise Distance | 100% | 66.7% | 1.027x | 2/2 已测样本 |
| Prime Count | 100% | 100% | 1.016x | 3/3 |
| Tiny Tasks | 100% | 100% | 0.998x | 1/3 |
| Word Count | 100% | 100% | 1.042x | 3/3 |
| **总体** | **100%** | **91.7%** | **宏平均 1.021x** | **9/11** |

其中 `LLM/Template 运行比 = Template 并行耗时 / LLM 并行耗时`，大于 1 表示
LLM 候选更快。Pairwise Distance 只有两个候选进入计时，失败样本仍计入正确率
分母。

表面上 LLM 在 9/11 个成功样本中更快，但差异很小。使用更保守的
`Template Q1 / LLM Q3 > 1` 判断时，只有 3/11 个样本仍占优。因此当前证据
不能证明 LLM 代码生成带来稳定性能提升。

![共享计划生成器对比](assets/paired_generation_formal_20260729/paired_generator_comparison.png)

## 5. 生成可靠性与成本

- 共享分析和规划：24 次调用；
- LLM 代码生成与修复：20 次调用；
- LLM 代码生成与修复 Token：16,978；
- LLM 代码生成增量费用上界：约 0.00949 美元；
- 全实验 Token：40,573；
- 全实验费用上界：约 0.02325 美元；
- 代码修复：8 次；
- AST 安全拒绝：0 次；
- 最终无法修复：1/12。

失败样本为 Pairwise Distance 第 3 次生成。模型连续两轮修复后仍错误展开
NumPy 数组，最终在 `np.concatenate` 处触发
`zero-dimensional arrays cannot be concatenated`。该失败的完整代码、错误反馈
和模型轨迹均已保留。

## 6. 结论

1. 受控 LLM 确实能够生成不同形式的并行实现，并在多数样本中通过验证；
2. 在明确、规则化的 Map-Reduce 契约下，确定性模板达到 100% 正确率，LLM
   没有表现出可靠的性能优势；
3. 自由代码生成增加了 Token、修复和失败成本；
4. LLM 的价值不应被表述为“生成代码一定比模板快”；
5. 项目的主要研究贡献应继续放在 LLM/Agent 更适合的决策层：
   依赖理解、是否值得并行、Worker/Chunk 选择、性能反馈和自动回退。

这是一个有价值的负结果：它明确区分了“适合确定性规则的代码骨架”和“需要
Agent 推理的性能决策”，避免为了使用 LLM 而把所有模块都交给 LLM。

## 7. 复现命令

```powershell
parallel-agent paired-generation-experiment `
  configs/paired_generation_formal.yaml `
  --output-dir results/raw/paired_generation_formal_20260729 `
  --adapter deepseek
```

生成汇报图：

```powershell
parallel-agent plot-paired-generation `
  results/raw/paired_generation_formal_20260729/paired_generation_summary.csv `
  results/raw/paired_generation_formal_20260729/paired_generation_aggregate.csv `
  --output-dir docs/assets/paired_generation_formal_20260729
```

实验器支持调用次数和 Token 双预算保护、失败轨迹保留与成功作业断点续跑。
正式汇总表和精简失败证据同时版本化保存在
`docs/data/paired_generation_20260729/`，原始全量运行记录保存在
`results/raw/paired_generation_formal_20260729/`。
