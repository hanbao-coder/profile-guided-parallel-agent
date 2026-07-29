# 第一阶段复现与验收说明

本页用于让本人、导师或代码审阅者快速确认第一阶段提交是否完整。验收工具只读取
仓库内已经版本化的配置、正式实验数据和汇报文档，不会连接 DeepSeek，也不会产生
API 费用。

## 一条命令完成验收

安装项目依赖后，在仓库根目录运行：

```powershell
python scripts/verify_first_stage.py --run-tests
```

该命令会检查：

1. 第一阶段配置、数据、报告、口头提纲和论文笔记是否齐全；
2. 配置搜索是否确实包含 8 个任务、24 个作业且无失败；
3. 固定配置与完整三阶段方法的宏平均加速和性能退化率；
4. 任务融合的正确性、任务数、传输量及复用反例；
5. 两类 DAG 中关键路径策略是否降低建模 makespan 和 Worker 空闲比例；
6. 导师报告中的核心数字是否仍与正式数据一致；
7. 55 项自动化测试是否通过。

如果只想快速核对数据与文档，不运行测试：

```powershell
python scripts/verify_first_stage.py
```

## GitHub 自动验收

`.github/workflows/first-stage-verification.yml` 会在以下情况自动运行：

- 向 `master` 推送代码；
- 推送版本标签；
- 创建或更新面向 `master` 的 Pull Request；
- 在 GitHub 页面手动触发。

云端环境固定为 Ubuntu 与 Python 3.12，先安装项目，再编译源码，最后执行同一条
第一阶段验收命令。工作流不配置 DeepSeek Key，因此不会产生模型调用费用。

在常规验收之后，工作流还会使用实际 `--backend ray` 运行 Prime Count 的
串行、朴素并行和优化并行小规模冒烟实验，并将原始 JSON 保存为 30 天可下载的
GitHub Actions Artifact。该实验用于验证单节点 Ray 后端可执行和结果正确，不作为
共享 CI 机器上的正式性能结论，也不代表多机集群实验。

首次分支推送和 `v0.14.0-linux-ci` 标签触发的两次云端运行均已成功完成：

- `https://github.com/hanbao-coder/profile-guided-parallel-agent/actions/runs/30461017594`
- `https://github.com/hanbao-coder/profile-guided-parallel-agent/actions/runs/30461020253`

## 结果来源

冻结数据位于：

- `docs/data/configuration_ablation_20260729/`
- `docs/data/task_fusion_20260729/`
- `docs/data/dag_scheduling_20260729/`

每组数据均由对应的正式配置和实验命令产生。`results/raw/` 是本地运行目录，不作为
结论的唯一证据；报告引用的精简数据已经复制到 `docs/data/` 并进入 Git。

## 结果解释边界

- 配置搜索和任务融合是本机 `multiprocessing` 实测结果；
- DAG 调度是确定性同构 Worker 列表调度模型，不是真实 Ray 运行加速；
- 当前 Windows 中文主机名触发 Ray 2.56.1 兼容错误，正式 Ray 复现等待 Linux
  或英文主机名环境；
- 验收脚本证明冻结数据、代码测试和文档声明一致，不代替在新机器上重新执行全部
  长时间实验。

## 导师现场演示建议

现场优先运行不联网的快速验收命令，再展示：

1. Prefix Sum 被依赖安全门拒绝并行；
2. Prime Count 保留有收益的并行配置；
3. Tiny Tasks 因调度开销回退串行；
4. 配置搜索消融图和任务融合反例；
5. DAG 结果旁的“模型实验”边界说明。

这样可以在 5 分钟内说明系统既会并行，也会拒绝不合理并行，并且所有结论都有
可追溯数据。
