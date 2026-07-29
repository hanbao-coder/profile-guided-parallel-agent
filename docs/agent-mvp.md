# Agent 最小闭环说明

完成日期：2026-07-29

## 当前闭环

```text
串行 Python 源文件
        ↓
AST 静态分析
        ↓
analysis.json
        ↓
离线 Agent 生成 parallel_plan.json
        ↓
确定性代码生成器生成 candidate.py
        ↓
分别执行 Serial / Parallel
        ↓
比较规范化输出
        ↓
成功：接受候选
失败：写入 repair_feedback.json
        ↓
调整 Worker / Chunk 并重新生成
```

## 为什么先使用离线 Agent

目前尚未配置 OpenAI API Key。为避免模型接口阻塞工程开发，系统提供
`offline-heuristic-v1`：

- 使用 AST 与函数契约判断是否可并行；
- 输出与未来在线模型完全相同的 JSON 结构；
- 使用同一套生成、执行、验证和修复工具；
- 测试结果确定、可重复、不产生 API 成本。

未来在线模型只替换分析、规划和修复适配器，执行器与评价系统保持不变。

## 结构化产物

### analysis.json

记录：

- 源文件和函数；
- 循环数量与依赖风险；
- 是否满足当前支持的函数契约；
- 是否建议并行；
- 判断理由。

### parallel_plan.json

记录：

- 是否并行；
- 后端和并行模式；
- Worker 与 Chunk；
- 正确性门控；
- 串行回退策略；
- 规划理由。

两类文件分别受 `schemas/analysis.schema.json` 和
`schemas/parallel_plan.schema.json` 约束。

## 当前支持范围

输入程序需提供：

- `make_input(size, seed)`；
- `unit(item)`；
- `combine(values)`；
- `equivalent(left, right)`。

这是 P0 Agent 的明确研究边界，不代表最终系统只能处理这种形式。它让我们
先验证闭环、评价指标和失败恢复，再逐步放宽输入限制。

## 已验证案例

### Prime Count

- 成功生成候选代码；
- 串行结果：3491；
- 并行结果：3491；
- 正确性门控通过；
- 最终状态：accepted。

### Prefix Sum

- 未满足支持契约；
- 同时存在跨循环迭代依赖；
- 系统拒绝生成并行候选；
- 最终状态：rejected。

### Child Failure

测试夹具故意让子进程抛出异常：

- 系统捕获运行错误和 stderr；
- 写入结构化修复反馈；
- 降低 Worker / Chunk；
- 重新生成并执行；
- 多轮失败后保留完整日志并标记 failed。

## 下一步

1. 配置一个真实大模型 API；
2. 实现在线 JSON 结构化输出适配器；
3. 让模型根据 AST、报错和性能数据生成/修改计划；
4. 比较离线规则、单次 LLM 与反馈 Agent。

