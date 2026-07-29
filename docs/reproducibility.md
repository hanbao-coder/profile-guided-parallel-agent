# 当前研究核心复现与验收说明

本页用于让本人、导师或代码审阅者快速确认当前研究核心是否完整。验收工具只读取
仓库内已经版本化的配置、正式实验数据和代码契约，不会连接 DeepSeek，也不会产生
API 费用。

## 一条命令完成验收

安装项目依赖后，在仓库根目录运行：

```powershell
python scripts/verify_research_core.py --run-tests
```

该命令会检查：

1. 三组正式 Ray 数据是否包含约定的 3×8×3 方法矩阵；
2. 当前正式数据是否包含 360 次计时且全部正确；
3. 方差感知优化是否改善负载不均衡案例并降低性能退化率；
4. 并行开销、Agent–Ray 后端契约和结构化计划是否完整；
5. 当前数据的集群节点、任务执行节点及计数不变量是否可审计；
6. 69 项自动化测试是否通过。

如果只想快速核对数据与文档，不运行测试：

```powershell
python scripts/verify_research_core.py
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
共享 CI 机器上的正式性能结论，也不代表多机集群实验。工作流还会验证报告中的
存活节点、任务实际执行节点和节点任务计数可以相互还原。

首次 Ray Gate 暴露了一个跨平台问题：GitHub 的 checkout 路径较长，原先再将
Ray 临时目录放在仓库 `work/ray/` 下，会使 Linux `AF_UNIX` Socket 路径超过
107 字节。当前实现改用系统短临时目录 `/tmp/pa_ray`，并加入路径
长度回归测试。

首次分支推送和 `v0.14.0-linux-ci` 标签触发的两次云端运行均已成功完成：

- `https://github.com/hanbao-coder/profile-guided-parallel-agent/actions/runs/30461017594`
- `https://github.com/hanbao-coder/profile-guided-parallel-agent/actions/runs/30461020253`

## 结果来源

冻结数据位于：

- `docs/data/wsl_ray_cluster_ready_20260730/`
- `docs/data/wsl_ray_variance_20260730/`
- `docs/data/wsl_ray_formal_20260729/`
- `docs/data/configuration_ablation_20260729/`
- `docs/data/task_fusion_20260729/`
- `docs/data/dag_scheduling_20260729/`

每组数据均由对应的正式配置和实验命令产生。`results/raw/` 是本地运行目录，不作为
结论的唯一证据；报告引用的精简数据已经复制到 `docs/data/` 并进入 Git。

## 结果解释边界

- 配置搜索和任务融合是本机 `multiprocessing` 实测结果；
- DAG 调度是确定性同构 Worker 列表调度模型，不是真实 Ray 运行加速；
- 当前正式 Ray 性能结果来自 WSL2 Ubuntu 单节点，不代表真实多节点扩展性；
- `--ray-address` 已可连接外部集群，但多节点结论必须同时满足至少两个物理节点
  和至少两个实际任务执行节点；
- 验收脚本证明冻结数据、代码测试和文档声明一致，不代替在新机器上重新执行全部
  长时间实验。

## 重新运行当前正式 Ray 协议

在 WSL2 或 Linux 中激活包含项目依赖的环境，然后运行：

```bash
bash scripts/run_wsl_ray_formal.sh results/raw/wsl_ray_current
```

脚本拒绝覆盖已有目录，依次启动三轮独立 Ray 运行，最后自动生成聚合 CSV 和
总体 JSON。正式协议固定为 8 类任务、M0/M1/M2、每方法 1 次预热和 5 次计时。

## 导师现场演示建议

现场优先运行不联网的快速验收命令，再展示：

1. Prefix Sum 被依赖安全门拒绝并行；
2. Prime Count 保留有收益的并行配置；
3. Tiny Tasks 因调度开销回退串行；
4. 配置搜索消融图和任务融合反例；
5. DAG 结果旁的“模型实验”边界说明。

这样可以在 5 分钟内说明系统既会并行，也会拒绝不合理并行，并且所有结论都有
可追溯数据。
