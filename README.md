# RepoPilot

## 背景

RepoPilot 面向 Python 软件仓库，接收 Bug 描述、异常堆栈、本地仓库和测试命令，完成代码检索、根因分析、补丁生成、隔离测试、失败反思、人工审批和修复报告。项目同时服务于工程闭环和 Agent 机制研究。

## 架构

```text
CLI / FastAPI
      |
      v
TaskService -> LangGraph Repair Pipeline
      |                 |
      |                 +-- Planner
      |                 +-- Research / Code RAG
      |                 +-- Diagnosis
      |                 +-- Coding
      |                 +-- Review
      |                 +-- Reflection
      v
Tool Gateway -> Worktree / Docker Sandbox -> Test Runner
      |
      +-- SQLite Memory / Checkpointer
      +-- Trace / Logs / Cost / Benchmark
```

详细设计见 [docs/architecture.md](docs/architecture.md)。

## Agent 职责

| 模块 | 责任 | 关键约束 |
|---|---|---|
| Planner | 生成 `TaskPlan` 和有限 Action | DAG 无环、预算受限 |
| Research | 使用 Code RAG 找到可追溯 Evidence | 文件、行号、符号、Commit |
| Diagnosis | 解释根因 | 必须引用 Evidence ID |
| Coding | 生成 Unified Diff | 不直接写宿主机文件 |
| Review | 综合 Diff、Diagnosis、真实测试 | 不接受模型自行声称通过 |
| Reflection | 从真实执行证据选择恢复策略 | Patch/Replan/Tool Retry 独立限额 |
| Tool/Test | 执行文件、Git、Patch、pytest | 参数数组、路径限制、超时 |

## 技术栈

- Python 3.11+
- Pydantic v2
- LangGraph 1.2.x
- FastAPI / Uvicorn
- SQLite
- pathspec
- pytest
- uv
- Docker CLI/Sandbox（真实 Daemon 当前未验证）
- 可选 OpenAI-compatible LLM/Embedding Adapter

## 交付状态

- **已实现并通过测试**：Schema、Config、LangGraph、Code RAG、Tool Gateway、Worktree/Patch/Test、Memory、Planning、Reflection、CLI、API、Benchmark Runner。
- **已实现但未充分验证**：真实 LLM 单任务 E2E、真实 LLM/Embedding 全量评测、Docker Sandbox、持久化 Checkpointer、真实 Benchmark 效果。
- **未实现**：Web UI、MCP、RL Planner、自动 push/merge/deploy。
- **环境限制未验证**：真实模型 API、Docker Daemon、PostgreSQL/pgvector、价格和 Token 成本。

完整验收矩阵见 [docs/final_acceptance.md](docs/final_acceptance.md)。

RepoPilot is an adaptive multi-agent system for Python software debugging and repair. The current repository contains the project foundation for configuration, validated schemas, unified errors, structured logging, and tests. LLM agents, tools, sandboxing, memory, and benchmark execution are intentionally not implemented yet.

## Requirements

- Python 3.11 or newer
- uv 0.11 or newer
- No real LLM, PostgreSQL, or Docker service is required for the foundation tests

## Install

```bash
cd agent/RepoPilot
uv sync --extra dev
```

This creates a local `.venv`, installs the project in editable mode, and locks dependencies in `uv.lock`.

## Configuration

Configuration is resolved in this order:

1. Built-in defaults
2. YAML file selected by `REPOPILOT_CONFIG` or `load_config(config_path=...)`
3. Environment variables

Copy the safe example and provide local-only values:

```bash
cp .env.example .env
```

`.env`, `*.local.yaml`, `configs/local.yaml`, and local settings files are ignored by Git. Never place credentials in `configs/app.yaml` or other tracked files.

`load_config` reads the process environment. If `.env` is used as a local source, load it into the shell before running commands:

```bash
set -a
source .env
set +a
```

Optional capabilities are disabled when unconfigured:

- `LLM_ENABLED=false`
- `EMBEDDING_ENABLED=false`
- `RERANKER_ENABLED=false`

SQLite is the default local database and checkpointer backend. Docker is not required while `SANDBOX_BACKEND=local_worktree`.

## Tests

Run tests from the RepoPilot directory:

```bash
uv run --extra dev pytest -v
```

The current tests cover schema validity and boundaries, configuration precedence, optional-service behavior, and secret redaction in structured logs. They do not call a real model API, database server, or Docker daemon.

## Current Scope

Implemented:

- Unified YAML and environment configuration loading
- LangGraph 1.x runtime with explicit state channels and bounded routing
- Fake LLM and Fake Agent support for API-key-free graph tests
- Tool Registry and Tool Gateway with validated ToolSpec/ToolInput contracts
- Read-only `list_files`, `search_code`, `read_file`, `git_status`, and `git_diff` tools
- Isolated Git Worktree lifecycle, Unified Diff validation/application, and controlled Test Runner
- End-to-end repair pipeline with Fake LLM and optional OpenAI-compatible real LLM adapter
- Python AST Code RAG with BM25, optional embeddings, RRF/weighted fusion, and stale-index detection
- Short-term LangGraph Checkpointer recovery and SQLite long-term Experience Memory
- Adaptive Planning with complexity features, bounded action routing, and Static Workflow baseline
- Execution-aware Reflection with bounded recovery strategies and Recovery Rate metrics
- Docker-first sandboxing, bounded reliability controls, and CLI-only patch approval
- Benchmark Runner with 10 Python Bug fixtures, private evaluator data, raw JSON/CSV records, and metrics
- Experiment suite for A-E groups, ablations, paired comparisons, Bootstrap intervals, failure analysis, and SVG plots
- CLI, asynchronous FastAPI task API, and honest Fake-LLM Demo with real patch/test execution
- Pydantic v2 core schemas
- Unified error types
- JSON/text structured logging with secret redaction
- Pytest test structure and installable package metadata

Not implemented:

- Real LLM agents or model calls
- Patch Executor and real Test Runner
- Docker sandbox
- Memory and benchmark logic

External services that cannot be verified must be reported as `SKIPPED` or `NOT VERIFIED`; test results must never be fabricated.

## Runtime Scope

The current runtime graph is:

```text
initialize
  -> planner
  -> research
  -> diagnosis
  -> coding
  -> test
  -> review
  -> report
  -> END
```

Review failures route to `coding` for bounded patch retries or `planner` for bounded replanning. Terminal failures and exhausted budgets route to `report`, so the graph cannot loop indefinitely. Every node records structured `TraceEvent` entries in `execution_trace`.

`RepoPilotState` uses append reducers only for `evidence`, `memory_hits`, and `execution_trace`. `plan`, `diagnosis`, `patch_result`, `test_report`, `review_result`, `retry_counts`, `budget`, `status`, and `report` are overwrite fields so stale round results cannot accumulate.

All Fake LLM outputs are parsed through Pydantic contracts before reaching downstream nodes. Invalid structured output marks the run failed and routes to the report node.

## Tool Gateway

Agents must call tools through `ToolGateway`; handlers are not a command execution surface. The current built-in registry is read-only and includes:

```text
list_files
search_code
read_file
git_status
git_diff
```

Each `ToolSpec` declares its validated input model, risk level, timeout, idempotence, approval requirement, and output limit. `ToolResult` always reports success, structured error information, duration, and artifacts.

File tools normalize relative paths and reject absolute paths, `..` traversal, symbolic links, and paths resolving outside the allowed repository root. Git tools execute argument arrays with `shell=False`. No write tool or arbitrary Shell tool is registered.

Tool calls can be wrapped with `execute_tool_with_trace()` so `ToolResult` and `TraceEvent` records are appended to LangGraph state. Tool failures remain structured and traceable instead of becoming uncontrolled exceptions.

## Worktree, Patch, and Test Runner

Patch execution is limited to an isolated Git Worktree. The worktree manager records the source repository, base commit, and initial Git status, and supports cleanup without modifying the source checkout.

The Patch Validator rejects malformed Unified Diffs, absolute paths, `..` traversal, forbidden files, binary patches, oversized diffs, and excessive modified-file or hunk counts. The Patch Executor runs `git apply --check` before applying a patch and restores the worktree on failure. The source repository is never the write target.

Tests run only from a controlled command allowlist with argument arrays and `shell=False`. The runner records exit code, stdout, stderr, duration, and a classified status:

```text
passed
assertion_failed
collection_error
dependency_error
timeout
execution_error
skipped
```

Test execution has timeout and output-size limits, and sets `PYTHONDONTWRITEBYTECODE=1` so test runs do not pollute Git diffs. Baseline and post-patch reports are separate records.

## End-to-End Repair Pipeline

The first reproducible fixture is `benchmarks/tasks/task-001`, a Git repository containing a `parse_config` empty-mapping bug and its target pytest. The repair sequence is:

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

The Fake LLM path is fully runnable without API keys. The optional real path uses an OpenAI-compatible Chat Completions adapter only when `LLM_ENABLED=true`, `LLM_PROVIDER=openai-compatible`, and `LLM_BASE_URL`, `LLM_API_KEY`, and `LLM_MODEL` are configured. The real model path is not considered verified without an actual successful run.

The final report includes the task summary, plan, root cause, path/line evidence, Unified Diff, modified files, baseline and post-patch TestReport values, review result, Git diffs, failure node/reason, execution trace, and cost usage when the LLM client exposes it.

## Code RAG

`retrieval` indexes Python repositories into structured chunks for functions, classes, and methods. Each chunk records file path, line range, symbol, parent symbol, source text, and repository commit.

Indexing:

- follows `.gitignore` using `pathspec`
- excludes virtual environments, caches, build output, secrets, and binary files
- falls back to a text chunk when Python AST parsing fails
- records parser/indexing errors
- detects stale indexes by comparing the repository Git commit

Retrieval combines:

1. exact file path matches
2. exact function/class symbol matches
3. stack-trace file/line matches
4. BM25 lexical search
5. optional embedding cosine search

Fusion supports configurable weighted scoring and RRF. If no Embedding Provider is configured, vector retrieval is disabled and BM25 plus exact retrieval continue normally. Retrieved chunks are converted to `Evidence` with retrieval source and repository commit preserved.

## Memory

Short-term memory uses LangGraph Checkpointer state snapshots. `CheckpointedGraphRunner` assigns one `thread_id` per task, supports `interrupt_before` and resume via `invoke(None, config)`, rejects duplicate thread starts, and exposes node `next` state plus execution traces. A resumed run continues from the checkpoint instead of repeating completed non-idempotent nodes.

Long-term memory uses a SQLite `ExperienceStore`. Each `Experience` records issue summary, error type, repository fingerprint, affected symbols, root cause, solution summary, patch summary, validation summary, applicability conditions, embedding text, source task, and outcome:

```text
verified_success
failed
uncertain
```

Only experiences with both target and regression tests marked passed may be saved as `verified_success`. Failed experiences can be stored and inspected explicitly, but are not returned as successful planning examples by default. Memory retrieval records memory ID, query, score, source task, timestamp, and whether Planner adopted the hit.

Retrieval currently uses deterministic keyword ranking. Semantic/vector retrieval remains optional and must not block the core flow. Memory hits are planning hints only; they never replace current source-code Evidence.

## Adaptive Planning

Planner outputs structured `TaskPlan` objects over the bounded action space:

```text
search, inspect, diagnose, patch, test, review, replan, finish
```

Plans are validated for unique `step_id` values, valid dependencies, acyclic DAGs, legal actions, and a valid `next_action`. The adaptive policy then applies deterministic rules over complexity features:

- stack-trace localization coverage
- affected files and symbols
- Evidence completeness
- Memory hits
- latest test status
- tool success/failure feedback
- invalid planning attempts
- LLM, token, tool-call, and runtime budgets

The policy can route to `search`, `diagnose`, `patch`, `test`, `replan`, `review`, or `finish`. Budget exhaustion and terminal `finish` are hard stops. Invalid planning attempts are bounded. `StaticPlanningPolicy` preserves the fixed workflow as an experimental baseline.

`PlanningRecord` stores sanitized planning input summaries, requested/effective actions, rationale, execution result, and cost. No RL policy is used.

## Reflection

Reflection classifies failures from real execution artifacts rather than model claims:

```text
patch_error
regression
wrong_root_cause
missing_context
test_env_error
tool_failure
budget_exceeded
```

`ReflectionResult` records structured evidence, root-cause hypothesis, recommended action, confidence, remaining retry budgets, and a recovery strategy. It is converted to `PlannerFeedback`, so the Planner receives typed action constraints rather than natural-language notes.

Strategies include patch regeneration, patch rollback plus re-diagnosis, additional search, environment handling without code changes, bounded idempotent tool retry, and budget termination/human review. Invalid Reflection JSON safely degrades to a terminal recovery result.

`ReflectionRecord` stores state before/after, evidence, Planner feedback, cost, and recovery outcome. `calculate_recovery_rate()` reports recovered/actionable counts and Recovery Rate.

## Sandbox, Reliability, and Approval

Docker Sandbox builds a container command with:

- `--network none`
- non-root `--user`
- CPU, memory, process, and timeout limits
- `--read-only`
- dropped capabilities and `no-new-privileges`
- one task Worktree bind mount at `/workspace`
- `/tmp` as a restricted tmpfs
- no Home, SSH, cloud credential, or Docker Socket mounts

When the Docker daemon is unavailable, sandbox execution is reported as `sandbox_unavailable`; no container result is fabricated.

`ExecutionLedger` deduplicates successful non-idempotent operations. `ReliabilityController` distinguishes retryable, terminal, and human-required errors and enforces timeout, cancellation, and budget limits. Checkpoint recovery continues from the saved node instead of replaying completed work.

Final patch export requires a recorded CLI approval decision. Rejected or missing approvals block export. Approval requests and decisions are persisted in SQLite. No Web approval, automatic push, merge, or deployment is implemented.

## Benchmark

`benchmarks/tasks` contains 10 reproducible Python Bug fixtures. Each task has:

- a clean Git repository fixture and Base Commit
- public `task.json` for Agent input
- private `private/evaluation.json`
- private `private/gold_patch.diff`

The Agent receives only `AgentTask`. Gold Patch, verification command, expected root cause, and regression command remain evaluator-private.

One command can run the benchmark infrastructure:

```bash
uv run python -m repopilot.evaluation.cli \
  --dataset benchmarks/tasks \
  --output benchmark-results \
  --group full
```

The CLI has `skipped` and `mock` infrastructure modes. With no real agent executor configured it records skipped/unknown results instead of fabricating agent success. The runner writes:

```text
raw_results.jsonl
raw_results.csv
summary.json
summary.csv
runs/<task>/<group>-<run>/record.json
runs/<task>/<group>-<run>/failure.log
runs/<task>/<group>-<run>/patch.diff
```

Metrics include Resolution Rate, Patch Pass Rate, Regression Rate, Root Cause Accuracy, Tool Success Rate, Replanning Rate, Reflection Recovery Rate, Memory Retrieval Hit Rate, P50/P95 latency, Token totals, LLM calls, and estimated cost when available. Missing token or price data remains `unknown`/`null`.

## Experiments

Experiment groups are defined in `src/repopilot/evaluation/experiments.py`:

- A: Single Agent + Tools
- B: Static Multi-Agent
- C: Static Multi-Agent + Memory
- D: Static Multi-Agent + Reflection
- E: Full RepoPilot
- Full vs No Adaptive Planning
- Full vs No Memory
- Full vs No Reflection

The suite records fixed model/prompt/tool/budget fields, disclosed differences, paired task results, Bootstrap intervals, failure stages/types, raw JSONL/CSV data, and separate group directories. The current run is intentionally `not_verified` because the full experiment suite has not been executed with the real Agent Executor and Docker Sandbox, even though real LLM connectivity and one repair E2E have been verified. See [docs/experiments.md](/Users/caojiahao/github/vibe-coding/agent/RepoPilot/docs/experiments.md).

Reproduce the infrastructure run and SVG plots:

```bash
uv run --extra dev python -m repopilot.evaluation.experiment_cli \
  --dataset benchmarks/tasks \
  --output experiment-results-stage12 \
  --executor skipped

python scripts/plot_experiments.py experiment-results-stage12 plots-stage12
```

## Frontend

A dependency-light frontend is available in `frontend/` and is served by FastAPI:

```bash
uv run uvicorn repopilot.api:create_app --factory --host 127.0.0.1 --port 8765
```

Open `http://127.0.0.1:8765/`. The UI provides a live task queue, structured task submission, status polling, trace and Diff inspection, test reports, approval/cancel actions, and saved real experiment charts. It uses live `/api/v1/tasks` endpoints and does not expose arbitrary command execution.

## CLI and API

Install the `repopilot` command with `uv sync --extra dev`.

CLI commands:

```bash
repopilot run --repo ./repo --issue "Bug description" --test-command "python -m pytest -q"
repopilot status <task-id>
repopilot trace <task-id>
repopilot artifacts <task-id>
repopilot benchmark run --dataset benchmarks/tasks --output benchmark-results
repopilot demo
```

`run` validates all parameters into `TaskRequest`, submits a long task asynchronously, and returns `task_id`. `--test-command` is parsed into an argument vector using JSON or shell-like tokenization, never executed through a shell. The default executor reports `unavailable` when no real repair backend is configured.

FastAPI endpoints:

```text
POST /api/v1/tasks
GET  /api/v1/tasks/{task_id}
GET  /api/v1/tasks/{task_id}/trace
GET  /api/v1/tasks/{task_id}/artifacts
POST /api/v1/tasks/{task_id}/approve
POST /api/v1/tasks/{task_id}/cancel
```

API requests and responses are Pydantic models with unified JSON errors. Long tasks execute in a thread pool and return immediately. There is no arbitrary command execution endpoint.

## Demo

`repopilot demo` runs `task-001` using explicit `FakeLLM` decisions plus real Code RAG, Git Worktree, Patch Validator, Patch Executor, and pytest Test Runner. The resulting `EndToEndReport` includes `execution_mode="fake_llm"` so the UI/CLI cannot present it as real-model evidence.

## 文档

- [架构](docs/architecture.md)
- [Benchmark 与评测器](docs/benchmark.md)
- [实验报告](docs/experiments.md)
- [真实 Full Pipeline 重复实验报告](docs/experiment_report.md)
- [架构决策](docs/decisions.md)
- [最终验收](docs/final_acceptance.md)
- [Demo 脚本](docs/demo_script.md)
- [简历项目描述草稿](docs/resume_project.md)
- [面试追问](docs/interview_questions.md)

## 已知问题和安全限制

1. 真实 LLM API 和单任务真实 E2E 已验证；完整 Benchmark 和总体性能仍需独立实验。
2. Docker Daemon 不可用，容器网络隔离和资源限制尚未真实验证。
3. 当前 Mini-Benchmark 只有 10 个任务，尚未达到 20-30 个目标。
4. 实验效果、成本和统计显著性没有真实数据支撑，`docs/experiments.md` 不作性能宣称。
5. 生产代码不提供任意 Shell、push、merge 或部署接口。
6. Patch 只在独立 Worktree 中写入；原始仓库不变的结论已在测试范围验证。
7. 日志、Memory 和审批记录不保存 API Key、Token、密码、Gold Patch 或隐藏测试答案。
