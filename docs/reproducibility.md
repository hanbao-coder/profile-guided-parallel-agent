# 真实项目实验复现说明

本文把复现分成三层：检查本项目代码、重新准备四个真实项目并验证串行基线、重新调用 DeepSeek 运行 Agent。前两层不消耗模型额度；第三层会消耗较多 Token。

## 1. 检查本项目代码

在仓库根目录运行：

```powershell
.\.venv\python.exe -m pytest -q
```

2026 年 8 月 8 日的完整检查结果为 `130 passed`。

本机 `.venv` 是 Conda 环境，Python 位于 `.venv\python.exe`，不是常见的 `.venv\Scripts\python.exe`。在其他机器上可以直接使用当前 Python 或新建 Python 3.12 环境，不要求路径完全相同。

## 2. 从零准备四个真实项目

项目版本、下载地址、压缩包哈希和依赖清单位于：

- `configs/candidate_bootstrap.yaml`；
- `configs/candidate_requirements/`；
- `configs/research_environment_lock.txt`。

在一个不存在的新目录中运行：

```powershell
.\.venv\python.exe scripts\bootstrap_candidate_projects.py `
  --workspace work\reproduction `
  --input-environment
```

脚本会完成以下工作：

1. 下载固定提交的 Radon、Vulture、Chardet 和 MkDocs；
2. 校验下载压缩包的 SHA-256，防止上游内容变化；
3. 为四个项目分别创建隔离环境并安装依赖；
4. 为 Radon 和 Vulture 创建独立的固定输入环境；
5. 固定 Chardet 测试数据的提交版本；
6. 生成 `bootstrap-evidence.json`。

如果输入环境安装因网络或超时中断，可以续跑：

```powershell
.\.venv\python.exe scripts\bootstrap_candidate_projects.py `
  --workspace work\reproduction `
  --input-environment-only `
  --resume-input-environment
```

脚本默认拒绝覆盖已有项目源码和环境，避免把不同批次混在一起。

## 3. 一条命令验证项目测试和串行基线

准备完成后运行：

```powershell
.\.venv\python.exe scripts\verify_candidate_reproduction.py `
  --workspace work\reproduction `
  --output work\reproduction-audit.json
```

验证器会顺序执行，不让四个项目同时抢占 CPU。每个项目均完成：

1. 运行原项目测试；
2. 预热 1 次并正式运行串行工作负载 3 次；
3. 检查三次输出是否稳定；
4. 比较实际输出哈希与预先登记的期望哈希。

本次干净环境审计结果保存在 `docs/data/candidate-reproduction-audit.json`，总结果为 `all_passed: true`：

| 项目 | 原项目测试 | 工作负载输出条目 | 输出是否稳定 | 哈希是否一致 |
|---|---:|---:|---|---|
| Radon | 399 通过，5 跳过 | 1521 | 是 | 是 |
| Vulture | 297 通过 | 3728 | 是 | 是 |
| Chardet | 9324 通过，21 预期失败，8 排除 | 500 | 是 | 是 |
| MkDocs | 719 通过，1 跳过，5 排除 | 67 | 是 | 是 |

不同机器的运行时间可以变化，因此复现首先检查测试、输出条目和输出哈希，不要求秒数完全相同。

## 4. 输出哈希为什么使用相对路径

早期基线把绝对文件路径放进输出，导致同一批内容换一个目录后哈希不同。现在的输出协议为 `output_schema_version: 2`：Radon、Vulture 和 Chardet 的文件名都先转换为相对于输入根目录的路径，再计算哈希；MkDocs 使用站点内相对路径。

这项修正不改变历史实验中同一目录内“修改前后是否一致”的判断，但使新的哈希可以跨目录比较。版本 1 和版本 2 的哈希不能直接混用。

## 5. Chardet 测试数据为什么单独固定

Chardet 的源码和测试数据来自两个仓库。最初从零审计误用了 8 月 8 日最新测试数据，而源码固定在 8 月 6 日；最新数据刚加入了一批用来暴露检测缺陷的样本，造成 12 项测试失败。

修正后，测试数据固定为源码提交时已经存在的最近版本 `fa16e9f`，原项目测试全部通过。这里说明：只固定主项目源码还不够，外部测试数据也属于实验版本的一部分。

## 6. 重新汇总已有 Agent 实验

不调用模型，只从本机原始记录重建 M6 汇总和中文图表：

```powershell
.\.venv\python.exe scripts\summarize_m6_study.py
```

该命令依赖本机 `results/m5` 和 `results/m6` 原始目录。如果原始目录不存在，只能查看 Git 中已经提交的紧凑结果，不能声称重新执行了 Agent。

核对 27 次正式运行是否都保留提示、回复、日志、补丁和验证证据：

```powershell
.\.venv\python.exe scripts\audit_research_evidence.py
```

生成的 `docs/data/research-evidence-manifest.json` 为每个文件保存 SHA-256，用于从汇总结果追溯
本机原始记录。

## 7. 重新运行 Agent 的边界

Agent 入口帮助：

```powershell
.\.venv\python.exe scripts\run_repository_diagnostic.py --help
```

正式运行必须从固定源码创建独立副本，先跑原测试和串行基线，再让 Agent 修改；修改后重新验证测试、固定输出和端到端性能。每次失败、回退和排除都保留，不能只挑最好的一次。

DeepSeek Key 只保存在本机 `.env`，不得提交到 Git。M7 的替代运行曾因服务余额不足被排除，
但当前不再等待补跑：固定协议已经证明 Radon 人工参考版本没有有效加速，原 M7 性能假设失去
实验前提。该决定和被排除运行分别记录，不能混入主实验统计。

## 8. 本轮复现发现并解决的问题

| 问题 | 原因 | 处理 |
|---|---|---|
| 安装超时后无法继续 | 脚本默认拒绝已有环境 | 增加输入环境续装模式，并保留已有项目证据 |
| Chardet 原测试出现 12 项失败 | 源码与最新测试数据版本不配套 | 固定源码提交时对应的测试数据提交 |
| 换目录后输出哈希变化 | 输出包含本机绝对路径 | 输出协议 v2 改用相对路径 |
| 并行启动测试出现临时目录错误 | 多个测试共享了尚未建立的上级目录 | 正式验证改为顺序运行，并使用项目内独立临时目录 |

这些问题都属于复现流程本身，不能被误记为 Agent 并行化失败。
