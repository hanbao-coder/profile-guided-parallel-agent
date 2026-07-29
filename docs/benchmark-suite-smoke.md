# 六类 Benchmark 冒烟实验

实验日期：2026-07-29

本实验用于验证基准接口、正确性检查、数据记录和优化决策，不是最终论文
数据。每种方法只正式运行一次，因此不能据此报告稳定均值或显著性。

## 覆盖范围

| Benchmark | 类型 | 主要观察点 |
|---|---|---|
| Prime Count | 独立 CPU Map | 粗粒度计算能否加速 |
| Mandelbrot | 不均匀 Map、较大输出 | 负载不均衡和输出通信 |
| Tiny Tasks | 细粒度 Map | 调度开销 |
| Word Count | Map-Reduce | 文本输入传输和结果归约 |
| Monte Carlo Pi | 随机任务归约 | 低通信 CPU 计算 |
| Pairwise Distance | NumPy 数值计算 | 大数组输入和内部向量化 |

此外保留 Prefix Sum 作为循环依赖反例，不进入并行执行套件。

## Large 规模端到端结果

| Benchmark | M0 Serial | M1 Naive | M2 Optimized | M2 决策 |
|---|---:|---:|---:|---|
| Prime Count | 0.819 s | 0.375 s | 0.387 s | 4 Worker / 4 Task |
| Mandelbrot | 0.249 s | 0.338 s | 0.243 s | 回退串行 |
| Tiny Tasks | 0.204 s | 0.687 s | 0.199 s | 回退串行 |
| Word Count | 0.029 s | 0.175 s | 0.029 s | 回退串行 |
| Monte Carlo Pi | 0.274 s | 0.245 s | 0.246 s | 4 Worker / 4 Task |
| Pairwise Distance | 0.097 s | 0.283 s | 0.101 s | 回退串行 |

## 通信代理数据

M1 的典型序列化数据量：

| Benchmark | 输入 | 输出 |
|---|---:|---:|
| Prime Count | 864 B | 576 B |
| Mandelbrot | 2.0 KB | 166 KB |
| Word Count | 2.75 MB | 5.3 KB |
| Pairwise Distance | 3.48 MB | 104 KB |

观察：

1. Prime Count 和 Monte Carlo 输入输出很小，计算占主导；
2. Word Count 的输入文本达到 MB 级，但串行计算本身只有约 0.03 秒；
3. Pairwise Distance 重复传输中心矩阵，输入达到约 3.48 MB；
4. Mandelbrot 的输出明显大于输入，同时不同图像行的计算量不均匀；
5. M2 对四类端到端无收益任务选择了串行回退。

## 本轮发现并修复的问题

Mandelbrot 初版错误地用当前行号推导图像高度，导致多行映射到相同坐标。
现已将每个任务输入改为 `(row, total_height)`，并重新运行 Small/Large 套件。

## 当前结论边界

- 六类任务的接口和三组执行均已跑通；
- 所有输出通过正确性检查；
- 序列化字节数和代理时间已进入结果文件；
- 目前只有单次冒烟数据，正式实验仍需预热、五次重复和随机执行顺序；
- 当前使用 Windows multiprocessing，不能替代最终 Ray/Linux 结果。

