# 第一次导师汇报现场演示

为了避免现场受网络、DeepSeek 服务或长时间实验影响，演示采用“实时依赖分析 +
冻结正式性能数据”的方式。脚本不会调用 DeepSeek，不产生 API 费用。

## 演示前

在仓库根目录运行一次：

```powershell
python scripts/verify_first_stage.py --run-tests
```

看到 `第一阶段科研交付包验收完成` 和全部测试通过后，再进行现场演示。

## 现场只运行一条命令

```powershell
python scripts/run_advisor_demo.py
```

脚本依次展示：

1. **Prefix Sum**：实时 AST 分析检测跨迭代依赖，拒绝朴素并行；
2. **Load Imbalance**：正式留出数据中选择 4 Worker / 16 Chunk，固定 4/4
   只有 0.781x，自适应达到 1.278x，且输出指纹一致；
3. **Tiny Tasks**：固定并行只有约 0.962x，完整方法三次都选择串行；
4. **实验边界**：性能数字来自冻结的 multiprocessing 正式实验，DAG 是调度
   模型结果，不冒充真实 Ray 加速。

## 讲解词

> 第一个例子说明系统不是看到循环就并行，而是先检查依赖。第二个例子说明固定
> Worker 和 Chunk 可能变慢，完整方法通过小样本搜索、完整规模确认和独立留出
> 评测选择更合理的粒度。第三个例子说明任务太小时系统会回退串行。项目当前的
> 核心贡献不是生成并行语法，而是降低盲目并行带来的性能退化。

演示输出会保存在 `work/advisor-demo-时间戳/advisor_demo_summary.json`，方便
汇报后追溯。
