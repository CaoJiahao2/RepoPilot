# Benchmark 与评测器

## 1. 任务格式

公开 Agent Task：

```text
task_id
repository_fixture
base_commit
issue
stack_trace
test_command
expected_behavior
metadata
```

评测器私有 Task：

```text
gold_patch
verification_command
expected_root_cause
regression_command
```

私有数据位于 `private/evaluation.json` 和 `private/gold_patch.diff`，不会进入 `AgentTask`。

## 2. Fixture

当前 `benchmarks/tasks` 包含 10 个 Python Bug Fixture：

- 空字典返回值。
- 上下界。
- 除零。
- 空字符串规范化。
- 零值奇偶判断。
- 默认值。
- 正数过滤。
- 字符串格式。
- 百分比折扣。
- 重复次数。

每个 Fixture 是独立 Git Repository，记录 Base Commit 和目标 pytest。Benchmark Runner 按 Base Commit 创建干净 Worktree。

## 3. Runner

```bash
uv run python -m repopilot.evaluation.cli \
  --dataset benchmarks/tasks \
  --output benchmark-results \
  --group full
```

实验套件：

```bash
uv run python -m repopilot.evaluation.experiment_cli \
  --dataset benchmarks/tasks \
  --output experiment-results \
  --executor skipped
```

`skipped` 是无真实执行器时的诚实基础设施模式；它不会产生 Agent 成功率。

## 4. 原始输出

每次运行输出：

```text
raw_results.jsonl
raw_results.csv
summary.json
summary.csv
runs/<task>/<group>-<run>/record.json
runs/<task>/<group>-<run>/failure.log
runs/<task>/<group>-<run>/patch.diff
```

实验套件额外输出：

```text
experiment_manifest.json
suite_raw.jsonl
suite_raw.csv
experiment_table.csv
paired_comparisons.json
paired_comparisons.csv
failure_analysis.json
failure_analysis.csv
suite_report.json
```

## 5. 指标

- Resolution Rate
- Patch Pass Rate
- Regression Rate
- Root Cause Accuracy
- Tool Success Rate
- Replanning Rate
- Reflection Recovery Rate
- Memory Retrieval Hit Rate
- P50/P95 Latency
- Input/Output Token
- LLM Calls
- Estimated Cost

无真实执行结果时成功率和延迟为 `unknown/null`，不能写成 0%。

## 6. 配对实验

实验组：

- A Single Agent + Tools
- B Static Multi-Agent
- C Static Multi-Agent + Memory
- D Static Multi-Agent + Reflection
- E Full RepoPilot
- Full vs No Adaptive Planning
- Full vs No Memory
- Full vs No Reflection

相同 `task_id + run_index` 配对比较，使用确定性 Bootstrap 95% 区间。当前基础设施运行没有非 skipped 结果，因此真实效果和统计显著性均未验证。

## 7. 评测限制

- 当前只有 10 个 Mini-Benchmark 任务，目标扩展到 20-30 个。
- 真实模型、Docker 和生产 Agent 评测需要外部环境。
- Gold Patch、Verification Command 和隐藏测试不能泄漏到 Agent。
- 没有真实 Token/价格时成本保持 unknown。
