# DeepSeek Agent 与确定性性能工具接入

## 目标

这一版本把“模型理解代码”和“性能参数决策”分开：

1. DeepSeek V4 Pro 分析代码、依赖和可并行性；
2. V4 Flash 把分析结果整理成结构化并行计划；
3. 确定性工具实测 Worker/Chunk 组合；
4. 完整规模确认小样本结论；
5. 独立留出运行验证正确性和速度；
6. 最终生成并执行被选中的计划，收益不足则回退串行。

模型不直接根据文字描述猜 Worker 和 Chunk。它负责语义理解，性能控制器负责
可复现的测量与决策。

## 科研控制

- 只有 `feedback_mode=performance` 才能使用配置搜索控制器；
- 当前只允许确定性模板生成，保证被搜索的代码和最终部署代码完全相同；
- 搜索、完整规模确认和留出评测使用分开的运行记录；
- 正式实验关闭缓存；
- 日常重复运行可按源码、规模、阈值、Python 和机器环境指纹复用缓存；
- 缓存命中仍保留明确标记，不能伪装成新的独立实验。

## 真实 DeepSeek 冒烟测试

任务：`load_imbalance`，完整规模 64，小样本规模 16。

| 项目 | 结果 |
|---|---:|
| DeepSeek 调用 | 2 次 |
| Token | 2,115 |
| 搜索选择 | 4 Worker / 8 Chunk |
| 固定 4/4 留出加速 | 0.861x |
| 自适应留出加速 | 1.108x |
| 自适应相对固定配置 | 1.286x |
| 最终独立验证加速 | 1.117x |
| 正确性 | 通过 |

该结果说明端到端控制流已经成立，但单次冒烟不能代替正式消融。下一步需要比较：

- 固定 4 Worker / 4 Chunk；
- 小样本选择但不做完整规模确认；
- 完整三阶段方法。

## 运行方式

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

主要产物：

- `analysis.json`：DeepSeek 的代码分析；
- `parallel_plan.json`：工具选择后的最终计划；
- `configuration_search/configuration_search_report.json`：完整搜索证据；
- `candidate.py`：最终执行代码；
- `run_report.json`：端到端决策、正确性和性能结果。
