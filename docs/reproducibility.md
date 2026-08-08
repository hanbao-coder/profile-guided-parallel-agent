# 真实项目实验复现说明

本文区分三种复现层级：检查当前代码、从已有原始记录重建结果、重新调用 DeepSeek 完成全部
实验。三者耗时和 API 成本差别很大，不能混在一起。

## 1. 环境确认

在仓库根目录 `D:\hustagent` 运行：

```powershell
.\.venv\python.exe --version
.\.venv\python.exe -m pytest -q
```

本机环境的 Python 直接位于 `.venv\python.exe`，不是常见的
`.venv\Scripts\python.exe`，因此不需要先运行 `Activate.ps1`。

`.env` 中的 `DEEPSEEK_API_KEY` 只在重新运行 Agent 时读取，不应提交到 Git。

## 2. 从原始记录重建紧凑结果和中文图

这一步不调用 DeepSeek，通常只需几秒：

```powershell
.\.venv\python.exe scripts\summarize_repository_diagnostics.py `
  --results-root results\m6\ablation-contract-only `
  --output-csv results\m6\ablation-contract-only-summary.csv `
  --output-json results\m6\ablation-contract-only-summary.json

.\.venv\python.exe scripts\summarize_m6_study.py
```

第二条命令同时读取：

- `results/m5/corrected-b0-summary.json`；
- `results/m5/corrected-final-summary.json`；
- `results/m6/ablation-contract-only-summary.json`；
- `results/m5/corrected-final/*/*/outcome.json` 中的逐轮反馈。

输出为：

- `docs/data/m6-study-summary.json`；
- `docs/data/m6-study-summary.csv`；
- `docs/figures/m6-overall-outcomes.png`；
- `docs/figures/m6-mkdocs-ablation.png`；
- `docs/figures/m6-feedback-findings.png`。

若本机没有 `results/m5` 和 `results/m6` 原始目录，只能查看 Git 中已经提交的紧凑结果，不能
声称重新执行了 Agent 实验。

## 3. 检查四个候选项目环境

源码固定副本位于 `work/candidate-sources/`，隔离环境位于 `work/candidate-envs/`。运行：

```powershell
.\.venv\python.exe scripts\verify_diagnostic_setup.py
```

该步骤检查源码路径、固定版本、测试命令、工作负载命令和串行基线信息，不调用模型。

## 4. 单独复现一个串行工作负载

以下示例复现 MkDocs 官方完整文档站点构建：

```powershell
work\candidate-envs\mkdocs\Scripts\python.exe scripts\run_candidate_baseline.py `
  --project mkdocs `
  --input-root work\candidate-sources\mkdocs-1.6.1 `
  --output work\mkdocs-baseline.json `
  --warmups 1 --repeats 5
```

命令必须从仓库根目录启动。输出应包含 67 个站点文件和稳定输出哈希。不同机器上的时间可以
变化，重点先检查输出是否稳定。

## 5. 重新运行一次 Agent 诊断

完整参数较多，先查看入口帮助：

```powershell
.\.venv\python.exe scripts\run_repository_diagnostic.py --help
```

每次运行都应满足：

1. 从固定源码建立独立试验副本；
2. 先运行原项目测试和串行工作负载；
3. 检查实际导入模块来自试验副本；
4. 保存模型每轮读取、修改和 Token；
5. 修改后重新运行项目测试和固定输出；
6. 使用现场串行基线做配对性能判断；
7. 不覆盖已有运行目录。

由于一次真实项目运行可能调用模型十余次并运行数百或数千项测试，重新执行前应先确认运行
目录、项目和组别，避免误把调试运行混入正式数据。

## 6. 实验固定规则

- 普通 Agent 和完整方法使用相同的模型与最大轮数；
- 每个项目、每种方法独立运行 3 次；
- 最终计时预热 1 次、正式运行 5 次，报告中位数；
- 有效并行要求测试通过、输出一致、存在并行结构、加速至少 1.05 倍；
- 失败和回退全部保留，不只挑最好的一次；
- 排除数据必须写 `exclusion.json` 并说明原因，然后重新运行替代试验。

## 7. 已知的两个复现陷阱

### Chardet 的 `src` 目录

必须确认 `chardet.__file__` 指向当前试验副本。否则 Python 可能导入隔离环境中已安装的原版，
造成“修改没有生效但测试看似通过”。旧的受影响运行已经排除。

### MkDocs 的当前工作目录

MkDocs 官方文档中的 API 页面会解析项目源码。基线必须从项目规定的根目录启动；从其他目录
运行会生成不同内容。首次错误基线已排除并保留说明。

## 8. 结果解释边界

- 主实验是 Windows 单机 CPU 进程/线程，不是 Ray 多节点实验；
- 历史目录中的单文件 Ray、配置搜索、任务融合和 DAG 调度不是当前主结论；
- 安全回退只表示没有保留已知不合格修改，不表示实现了并行加速；
- 紧凑汇总可以审计数字，但完整模型回答和测试日志只保存在本机原始结果中。
