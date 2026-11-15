# RepoPilot 对比实验与消融实验

> 正式真实重复实验报告见 [experiment_report.md](experiment_report.md)。

## 数据状态

本次运行状态：`not_verified`。

真实 LLM API 已通过鉴权并完成单任务 E2E，但完整实验 Suite 尚未使用真实 Agent Executor，且没有可用 Docker Sandbox。本次 Suite 使用 `SkippedExecutor` 运行了完整的实验配置和任务工作区流程，但所有任务结果均为 `skipped`。因此：

- 不把任何任务标记为 Resolution Success。
- 不报告虚假的成功率、成本、延迟或恢复率。
- Token、成本和真实执行延迟均保持 unknown。
- Bootstrap 区间只对 paired 非 skipped 结果计算；当前无可计算区间。

## 实验组

| 组 | 描述 | Multi-Agent | Memory | Reflection | Adaptive |
|---|---|---:|---:|---:|---:|
| A | Single Agent + Tools | 否 | 否 | 否 | 否 |
| B | Static Multi-Agent | 是 | 否 | 否 | 否 |
| C | Static Multi-Agent + Memory | 是 | 是 | 否 | 否 |
| D | Static Multi-Agent + Reflection | 是 | 否 | 是 | 否 |
| E | Full RepoPilot | 是 | 是 | 是 | 是 |
| ablation | Full vs No Adaptive Planning | 是 | 是 | 是 | 否 |
| ablation | Full vs No Memory | 是 | 否 | 是 | 是 |
| ablation | Full vs No Reflection | 是 | 是 | 否 | 是 |

固定字段：

- model_id: `unspecified`
- prompt_version: `v1`
- tool_set: `['list_files', 'search_code', 'read_file', 'git_status', 'git_diff']`
- budget: `{'max_llm_calls': 30, 'max_total_tokens': 100000, 'max_tool_calls': 100, 'max_runtime_seconds': 900}`

差异字段已在 `experiment_manifest.json` 中显式记录。

## 任务与原始数据

数据集：`benchmarks/tasks`

当前任务数：10 个 Python Bug Fixture，每个任务包含独立 Git Base Commit、公开 `task.json`、私有 Gold Patch 和私有 Verification Command。

原始数据：

- `experiment-results-stage12/suite_raw.jsonl`
- `experiment-results-stage12/suite_raw.csv`
- 每组独立目录：`experiment-results-stage12/<experiment_group>/raw_results.jsonl`
- 每次运行记录：`experiment-results-stage12/<experiment_group>/runs/.../record.json`
- 失败任务日志：`failure.log`
- 失败任务 Diff：`patch.diff`

## 汇总表

| 组 | Resolution Rate | Patch Pass Rate | P50 Latency | LLM Calls |
|---|---:|---:|---:|---:|
| `A_single_agent_tools` | unknown | unknown | unknown | 0 |
| `B_static_multi_agent` | unknown | unknown | unknown | 0 |
| `C_static_memory` | unknown | unknown | unknown | 0 |
| `D_static_reflection` | unknown | unknown | unknown | 0 |
| `E_full` | unknown | unknown | unknown | 0 |
| `abl_no_adaptive` | unknown | unknown | unknown | 0 |
| `abl_no_memory` | unknown | unknown | unknown | 0 |
| `abl_no_reflection` | unknown | unknown | unknown | 0 |

所有 `unknown` 均表示没有真实非 skipped 结果，不是 0%。

## 配对比较

| 比较 | 配对组 | Paired Tasks | Success Difference | Bootstrap 95% | 解释 |
|---|---|---:|---:|---|---|
| Multi-Agent vs Single-Agent | B_static_multi_agent vs A_single_agent_tools | 10 | unknown | [None, None] | unknown: no paired non-skipped results |
| Memory vs Static | C_static_memory vs B_static_multi_agent | 10 | unknown | [None, None] | unknown: no paired non-skipped results |
| Reflection vs Static | D_static_reflection vs B_static_multi_agent | 10 | unknown | [None, None] | unknown: no paired non-skipped results |
| Adaptive Planning ablation | E_full vs abl_no_adaptive | 10 | unknown | [None, None] | unknown: no paired non-skipped results |
| Memory ablation | E_full vs abl_no_memory | 10 | unknown | [None, None] | unknown: no paired non-skipped results |
| Reflection ablation | E_full vs abl_no_reflection | 10 | unknown | [None, None] | unknown: no paired non-skipped results |

由于本次运行没有非 skipped 配对结果，所有成功差异和 Bootstrap 区间均为 unknown。

## 失败分析

`experiment-results-stage12/failure_analysis.json` 当前为空。原因不是没有失败风险，而是所有任务被诚实标记为 skipped，未执行真实 Agent 失败流程。

失败阶段和失败类型需要真实 Executor、真实 Test Runner 和真实模型运行后才能产生。

## 研究问题

### Multi-Agent 相比 Single Agent 是否提升成功率，代价是什么？

**当前结论：未验证。**

本次 A/B 组均为 skipped，没有真实成功率、Token、LLM Call、Tool Call 或延迟数据。不能据此判断 Multi-Agent 提升或代价。

### Memory 是否改善相似 Bug 的解决效果？

**当前结论：未验证。**

C 组和 B 组没有真实结果，也没有相似任务的真实配对数据。Memory Retrieval Hit Rate 为 unknown，不能声称改善。

### Reflection 是否提高失败恢复率，额外成本是多少？

**当前结论：未验证。**

D 组、E 组和 `abl_no_reflection` 没有真实失败恢复结果。Reflection Recovery Rate、额外 Token、LLM Call 和延迟均未采集。

### Adaptive Planning 是否减少无效步骤？

**当前结论：未验证。**

需要真实 PlanningRecord、Tool Call、Replan 次数和无效步骤标注。当前实验结果没有执行步骤数据。

### 哪些任务类型容易失败？

**当前结论：未验证。**

当前 10 个 Fixture 覆盖空值、边界、除零、字符串格式、过滤、百分比和计数等类型，但没有真实任务失败分布，不能给出容易失败的任务类型结论。

## 图表

绘图脚本：

```bash
python scripts/plot_experiments.py experiment-results-stage12 plots-stage12
```

当前生成：

- `plots-stage12/resolution_rate.svg`
- `plots-stage12/latency_p50.svg`
- `plots-stage12/failure_breakdown.svg`

图表中的灰色 `unknown` 是真实数据状态，不是实验结果。

## 复现命令

```bash
uv run --extra dev python -m repopilot.evaluation.experiment_cli \
  --dataset benchmarks/tasks \
  --output experiment-results-stage12 \
  --repeats 1 \
  --model-id unspecified \
  --prompt-version v1 \
  --executor skipped

python scripts/plot_experiments.py experiment-results-stage12 plots-stage12
```

## 限制

1. 没有真实 Agent Executor，不能回答效果问题。
2. 真实 LLM 单任务调用已采集 Token Usage，但完整实验 Token、成本和效果数字仍未运行。
3. 没有 Docker Sandbox，真实隔离执行未验证。
4. 小样本 Bootstrap 只有在真实 paired 结果存在后才有统计意义。
5. 本报告不宣称任何统计显著性或性能提升。


## 补充：2026-11-13 真实多任务修复验证

这不是 A-E 对比实验，而是 Full Repair Pipeline 的真实多任务验证。模型为 `deepseek-v4-1-flash-261017`，Research 使用 Code RAG，Coding/Review 使用真实 LLM，Patch 和 pytest 在独立 Git Worktree 中执行。

| 指标 | 实际结果 |
|---|---:|
| 任务数 | 10 |
| Resolution | 10 / 10 |
| Baseline 复现失败 | 10 / 10 |
| Post-patch Test 通过 | 10 / 10 |
| LLM Calls | 40 |
| Input Tokens | 28,319 |
| Output Tokens | 27,888 |
| Mean Input Tokens | 2,831.9 |
| Mean Output Tokens | 2,788.8 |
| P50 Latency | 28.752 s |
| P95 Latency | 41.242 s |

原始汇总：`validation-results/real-task-summary.json`。

迭代中发现并修复：

1. 跨任务复用 LLM Client 时成本被累计，已改为单次运行 Usage 差值。
2. 首次运行 Token Usage 从 `None` 开始时未按 0 起算，已修复。
3. `task-004` Fixture 的旧实现本身不构成 Bug，已修复 Fixture、Gold Patch 和 Base Commit。
4. 模型生成的 Hunk 行号偶发不准确，Patch Executor 增加 `git apply --recount`。

上述 10/10 只代表当前 10 个 Mini-Benchmark 的单次 Full Pipeline 验证，不代表 A-E 实验比较、总体泛化能力或统计显著性。


## 正式真实重复实验（2026-11-14）

30 次真实 Full Pipeline 运行：

- Resolution：28/30，93.33%。
- Bootstrap 95% CI：83.33% - 100.00%。
- P50：28.806s。
- P95：40.094s。
- 117 LLM Calls。
- 82,825 Input Tokens、76,446 Output Tokens。
- 失败：1 次 coding API failure，1 次 apply_patch failure。

详细任务级结果、失败分析和图表见 [experiment_report.md](experiment_report.md)。该实验仍是 Full Pipeline 稳定性验证，不替代 A-E 对比。
