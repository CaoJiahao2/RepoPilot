# RepoPilot 真实 Full Pipeline 实验报告

## 1. 实验目标

验证真实 LLM、Code RAG、Git Worktree、Patch Executor 和 pytest Test Runner 组成的 Full Repair Pipeline 在相同 Mini-Benchmark 任务上的稳定性、成功率、Token、调用次数和延迟。

本报告不是 A-E 因果对比实验，不直接回答 Multi-Agent、Memory、Reflection 或 Adaptive Planning 的增量贡献。

## 2. 实验配置

| 配置项 | 值 |
|---|---|
| 日期 | 2026-11-14 |
| 模型 | `deepseek-v4-1-flash-261017` |
| Prompt 版本 | `schema-evidence-retry-v3` |
| 任务集 | 10 个 Python Mini-Benchmark |
| 每任务重复次数 | 3 |
| 总运行次数 | 30 |
| Research | Code RAG |
| Patch | Unified Diff + `git apply --recount` |
| Test | 真实 pytest |
| 隔离 | 独立 Git Worktree |
| Validation Retry | 结构化输出失败后最多重试 1 次 |
| Budget | 30 LLM Calls / 100,000 Tokens / 100 Tool Calls / 180s |

## 3. 总体结果

| 指标 | 结果 |
|---|---:|
| Resolution Rate | 28 / 30 = **93.33%** |
| Patch Pass Rate | 28 / 30 = **93.33%** |
| Regression Rate | 0 / 30 = **0%** |
| Total LLM Calls | 117 |
| Mean LLM Calls | 3.90 / run |
| Total Input Tokens | 82,825 |
| Total Output Tokens | 76,446 |
| Mean Input Tokens | 2,760.8 |
| Mean Output Tokens | 2,548.2 |
| Mean Latency | 30.672s |
| P50 Latency | 28.806s |
| P95 Latency | 40.094s |

Resolution Rate Bootstrap 95% 区间：

```text
[83.33%, 100.00%]
```

平均延迟 Bootstrap 95% 区间：

```text
[28.053s, 34.582s]
```

Bootstrap 使用 5,000 次重采样，seed=17。

## 4. 任务级结果

| Task | 成功次数 | 成功率 |
|---|---:|---:|
| task-001 | 2 / 3 | 66.67% |
| task-002 | 3 / 3 | 100% |
| task-003 | 2 / 3 | 66.67% |
| task-004 | 3 / 3 | 100% |
| task-005 | 3 / 3 | 100% |
| task-006 | 3 / 3 | 100% |
| task-007 | 3 / 3 | 100% |
| task-008 | 3 / 3 | 100% |
| task-009 | 3 / 3 | 100% |
| task-010 | 3 / 3 | 100% |

8 个任务稳定达到 3/3；`task-001`、`task-003` 各出现一次失败。

## 5. 失败分析

| Task | Run | 失败阶段 | 原因 |
|---|---:|---|---|
| task-001 | 1 | coding | LLM API 请求失败，未进入 Patch/Test |
| task-003 | 1 | apply_patch | `git apply --check --recount` 仍拒绝模型生成的 Patch |

失败阶段分布：

```text
coding: 1
apply_patch: 1
```

解释：

1. `coding` 失败是外部 API 请求失败，不是代码逻辑失败。
2. `apply_patch` 失败说明模型生成的 Unified Diff 仍有上下文不稳定问题。
3. 没有出现 Baseline/Post-patch 真实测试回归。
4. task-001、task-003 比其他任务更依赖 Patch 上下文和模型输出稳定性。

## 6. 迭代优化

本轮实验前完成：

- 将 Pydantic JSON Schema、Evidence ID、源码内容、当前 Diagnosis/Diff/Test 状态加入提示。
- Diagnosis/Review 只允许引用现有 Evidence ID。
- 结构化输出失败后执行最多 1 次校验重试。
- `git apply` 增加 `--recount`。
- 修正跨任务累计 LLM Usage 的成本计算。
- 修正 task-004 的无效 Bug Fixture。

## 7. 结论

1. 当前 Full Pipeline 在 30 次真实运行中达到 93.33% Resolution。
2. 成功补丁均通过真实 pytest；未检测到新增回归。
3. 主要剩余风险是外部 API 稳定性和模型 Unified Diff 上下文一致性。
4. task-001、task-003 是后续稳定性优化重点。
5. 该结果不能替代 A-E 对比，也不能证明 Memory、Reflection 或 Adaptive Planning 的贡献。

## 8. 原始数据

```text
experiment-results-real-full-v2/raw_results.jsonl
experiment-results-real-full-v2/raw_results.csv
experiment-results-real-full-v2/summary.json
experiment-results-real-full-v2/summary.csv
experiment-results-real-full-v2/experiment_report.json
experiment-results-real-full-v2/experiment_table.csv
experiment-results-real-full-v2/failure_analysis.csv
```

图表：

```text
plots-real-full-v2/resolution_rate.svg
plots-real-full-v2/latency_p50.svg
plots-real-full-v2/failure_breakdown.svg
```

## 9. 复现命令

```bash
set -a
source .env
set +a

uv run python -m repopilot.evaluation.cli \
  --dataset benchmarks/tasks \
  --output experiment-results-real-full-v2 \
  --group real_full_pipeline_v2 \
  --repeats 3 \
  --model-id deepseek-v4-1-flash-261017 \
  --prompt-version schema-evidence-retry-v3 \
  --executor real
```

## 10. 限制

- Root Cause Accuracy 尚未由私有评测器自动核验。
- 未配置价格表，因此货币成本为 unknown。
- Docker Sandbox 未启用。
- 尚未运行 A-E 和三组消融。
- 30 次运行样本仍有限，Bootstrap 区间较宽。
