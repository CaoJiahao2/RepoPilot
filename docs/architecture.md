# RepoPilot 架构

## 1. 总体架构

```text
CLI / FastAPI
      |
      v
TaskService ---- SQLite Task Records
      |
      v
LangGraph Repair Pipeline
      |
      +-- validate_task
      +-- prepare_workspace
      +-- Planner
      +-- Research / Code RAG
      +-- Diagnosis
      +-- Baseline Test
      +-- Coding
      +-- Diff Validation
      +-- Patch Executor
      +-- Post-patch Test
      +-- Review
      +-- Reflection / Replanning
      +-- Report
      |
      v
Tool Gateway
      +-- File / Search / Git Tools
      +-- Test Runner
      +-- Patch Validator / Executor
      |
      v
Isolated Git Worktree / Docker Sandbox
      |
      +-- SQLite Experience Memory
      +-- LangGraph Checkpointer
      +-- Structured Logs / Traces / Costs
```

## 2. 任务生命周期

`TaskService` 是 CLI 和 API 的共同入口：

1. 将请求校验为 `TaskRequest`。
2. 创建唯一 `task_id` 和 SQLite `TaskRecord`。
3. 将长任务提交到线程池。
4. 执行 Repair Pipeline。
5. 将 `EndToEndReport`、Trace、Diff 和测试报告写入任务记录。
6. 通过 status、trace、artifacts、approve、cancel 暴露生命周期。

## 3. 修复 Graph

逻辑节点：

```text
validate_task
  -> prepare_workspace
  -> planner
  -> research
  -> diagnosis
  -> baseline_test
  -> coding
  -> validate_diff
  -> apply_patch
  -> post_patch_test
  -> review
  -> report
```

节点失败时进入 `report`，记录 `failure_node` 和 `failure_reason`。重试和回退由 Adaptive Planning 与 Reflection 的结构化反馈约束。

## 4. Agent 职责

| Agent | 输入 | 输出 | 执行边界 |
|---|---|---|---|
| Planner | Task、Evidence、Memory、反馈、预算 | `TaskPlan` | 只能选择有限 Action |
| Research | Issue、Stack、Code RAG Hits | `ResearchResult` / Evidence | Evidence 必须来自检索结果 |
| Diagnosis | Evidence、Baseline Test、Issue | `Diagnosis` | 必须引用 Evidence ID |
| Coding | Diagnosis、相关代码、约束 | `PatchResult` | 只能输出 Unified Diff |
| Review | Diff、TestReport、Diagnosis | `ReviewResult` | 不能绕过真实测试结果 |
| Reflection | TestReport、ToolResult、Diff、Trace | `ReflectionResult` | 只输出结构化恢复策略 |

Test Runner、Patch Executor、Git、文件工具是确定性 Tool，不是 LLM Agent。

## 5. State 与 Reducer

`RepoPilotState` 是 LangGraph TypedDict：

- 覆盖更新：`plan`、`diagnosis`、`patch_result`、`test_report`、`review_result`、`retry_counts`、`budget`、`status`、`report`、`reflection_result`。
- 追加更新：`evidence`、`memory_hits`、`execution_trace`、`tool_results`。

这样旧轮次 Patch/Diagnosis 不会污染当前轮，Trace 和工具记录仍可审计。

## 6. Code RAG

Python AST Parser 将 Function、Class、Method 切为带行号的 `CodeChunk`。索引器遵循 `.gitignore`，排除虚拟环境、缓存、构建产物、密钥和二进制文件。检索组合：

1. 文件路径。
2. Function/Class Symbol。
3. Stack Trace 文件和行号。
4. BM25。
5. 可选 Embedding Vector。

结果统一转换为 `Evidence`，保留来源、分数、行号和 Git Commit。没有 Embedding Provider 时 BM25 和精确检索继续工作。

## 7. Memory

短期 Memory 使用 LangGraph Checkpointer 和唯一 `thread_id`，支持中断恢复和快照。长期 Memory 使用 SQLite `ExperienceStore`：

- `verified_success` 必须有目标测试和回归测试通过凭据。
- `failed` 和 `uncertain` 可以保存，但不会被默认当作成功经验。
- Memory Retrieval 记录 Memory ID、分数、任务来源和 Planner 是否采纳。
- Memory Hit 只作为 Planner 提示，不覆盖 Code Evidence。

## 8. Planning 与 Reflection

`AdaptivePlanningPolicy` 根据堆栈定位、Evidence 完整度、Memory、Test/Tool 反馈和预算选择 `search/diagnose/patch/test/review/replan/finish`。`StaticPlanningPolicy` 保留固定顺序作为实验基线。

Reflection 只读取真实执行产物，分类：

```text
patch_error
regression
wrong_root_cause
missing_context
test_env_error
tool_failure
budget_exceeded
```

`ReflectionResult` 转换为 `PlannerFeedback`，包括是否回滚 Patch、是否修改代码和剩余 Patch/Replan/Tool Retry。预算耗尽优先终止。

## 9. Sandbox 与安全

Docker Sandbox 默认：

- `--network none`
- 非 root 用户
- CPU、内存、进程数、超时和输出限制
- 只读容器、tmpfs、capability drop、no-new-privileges
- 只挂载任务 Worktree
- 不挂载 Home、SSH、云凭证或 Docker Socket

Patch 只能在独立 Worktree 中应用。Coding Agent 不直接写文件，任意 Shell、push、merge、部署均不在开放接口中。

## 10. 可观测性

每个 Tool/Agent/Test/Review 节点产生 `TraceEvent`。结构化日志经过敏感字段和秘密值脱敏。报告保存：

- 任务摘要和计划。
- Evidence 和根因。
- Unified Diff。
- Baseline/Post-patch TestReport。
- Review/Reflection。
- Git Diff 前后。
- 失败节点/原因。
- LLM、Token、Tool、Runtime 成本；不可采集时标记 unknown。
