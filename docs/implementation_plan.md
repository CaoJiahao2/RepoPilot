# RepoPilot 阶段 0：仓库审查与实施计划

## 1. 范围与约束

本阶段只进行仓库审查、环境检查、需求映射和实施计划设计。只允许创建或调整必要计划文档和安全配置示例，不实现完整 Agent、LangGraph、Tool、Memory、Sandbox 或 Benchmark 业务功能。

项目约束来源：

- `AGENTS.md`：项目级产品需求、架构、安全、测试和验收规范。
- 本轮阶段 Prompt：阶段 0 的仓库审查与实施计划范围。

## 2. 仓库现状分析

### 2.1 当前目录树

排除 `.git`、虚拟环境、缓存、构建产物、依赖目录和大型数据目录后：

```text
agent/RepoPilot/
├── AGENTS.md
├── docs/
│   └── implementation_plan.md
├── src/
│   └── repopilot/
│       └── __init__.py
├── tests/
│   └── test_project_skeleton.py
├── .env.example
├── .gitignore
└── pyproject.toml
```

### 2.2 Git 状态

- 当前项目目录不是 Git 仓库。
- 父目录 `/Users/caojiahao/github/vibe-coding` 也不是 Git 仓库。
- 无法取得 Git 分支、HEAD、远端、提交历史、未提交改动或 Staged 状态。
- 因此不能验证 Git Worktree、Git History 检索、Diff 审计或提交流程。
- 本次未初始化 Git，也未删除、覆盖或重建已有代码。

### 2.3 已有实现

- `AGENTS.md`：完整的项目规范。
- `docs/implementation_plan.md`：Task 0 实施计划。
- `pyproject.toml`：最小 Python 项目元数据和 pytest 配置。
- `src/repopilot/__init__.py`：最小包入口。
- `tests/test_project_skeleton.py`：项目骨架 smoke test。
- `.env.example`：无真实凭证的安全配置示例。
- `.gitignore`：排除 `.env`、虚拟环境、缓存、构建产物和本地数据库。

### 2.4 缺失实现

- `TaskRequest`、`TaskPlan`、`Evidence`、`Diagnosis`、`PatchResult`、`ReviewResult`、`TestReport` 等 Schema。
- LangGraph Runtime、State、条件路由、Checkpointer。
- Planner、Research、Diagnosis、Coding、Review、Reflection 模块。
- Tool Registry、Tool Gateway、统一 ToolResult 和权限模型。
- Patch Executor、Unified Diff 校验、Baseline Test、Post-patch Test。
- Worktree、Docker Sandbox、预算、审计轨迹和成本统计。
- Code RAG、短期 Memory、长期 Experience Memory。
- Benchmark Runner、数据集、指标、对比实验和消融实验。
- CLI、FastAPI、README、架构文档和可复现 Demo。
- 真实模型 API、PostgreSQL/pgvector、Docker Daemon。

## 3. 环境与依赖检查

### 3.1 Python 与依赖管理

| 项目 | 当前状态 | 结论 |
|---|---|---|
| 默认 Python | `/opt/anaconda3/bin/python`，3.12.7 | 满足 Python 3.11+ |
| 系统 Python | `/usr/bin/python3`，3.9.6 | 不满足项目要求，不应使用 |
| uv | 0.11.28 | 已安装，建议作为唯一依赖管理工具 |
| Poetry/PDM | 未安装 | 不引入第二套包管理器 |
| `pyproject.toml` | 已存在 | 当前 `dependencies = []`，仅用于骨架测试 |
| 锁文件 | 不存在 `uv.lock` 或其他锁文件 | M1 前必须锁定第三方依赖版本 |
| pytest | 7.4.4 | 可运行当前 smoke test |
| Pydantic | 当前环境可导入 | 应在锁文件中固定 Pydantic v2 |
| LangGraph | 当前环境缺失 | 阻塞真实 LangGraph 开发，但不阻塞 Schema 和 Fake 接口设计 |
| FastAPI | 当前环境缺失 | 属于后期 API 范围 |
| SQLAlchemy | 当前环境可导入 | 可作为持久化候选，但尚未配置 |
| Lint/Type Check | 未发现 Ruff、mypy 或 pre-commit 配置 | 当前无法运行项目级 Lint/类型检查 |

### 3.2 Docker

- Docker CLI：29.6.1 已安装。
- Docker Compose/Buildx 插件可见。
- Docker Daemon 无法连接，Docker Socket 路径不存在。
- 结论：`NOT VERIFIED`。镜像构建、容器运行、网络禁用和资源限制均不能验证。

### 3.3 数据库

- SQLite CLI：3.54.0 已安装，可作为开发阶段本地持久化后备。
- PostgreSQL 客户端 `psql`：未安装。
- 当前没有 `DATABASE_URL` 或数据库服务配置。
- 结论：SQLite 可用；PostgreSQL/pgvector 为 `NOT VERIFIED`。

### 3.4 模型 API 与外部服务

- 未发现 LLM、OpenAI、Anthropic、Embedding、Reranker、数据库或 Sandbox 相关环境变量名。
- 未发现真实 `.env`、模型 YAML 或服务配置文件。
- 未读取、打印或提交任何密钥。
- 结论：模型 API、Embedding、Reranker 均为 `NOT CONFIGURED / NOT VERIFIED`。

### 3.5 当前可执行验证

```bash
cd agent/RepoPilot
python -m pytest -q
```

该命令仅验证 Python 版本、项目元数据和包入口，不代表 Agent、模型、数据库或 Sandbox 已实现。

## 4. AGENTS.md 要求映射

| AGENTS.md 要求 | 已有 | 缺失 | 需要调整 | 风险 |
|---|---|---|---|---|
| Python 3.11+、Pydantic v2 | Python 3.12.7；Pydantic 可导入 | 版本锁定、Pydantic v2 约束 | 固定使用 3.11+ 的 uv 环境 | 系统 Python 3.9.6 可能被误用 |
| LangGraph 主编排 | 无 | Graph、State、路由、Checkpoint | 先验证真实 LangGraph API 再锁定版本 | 依赖版本/API 未验证 |
| 五个专业 Agent | 无 | Planner/Research/Diagnosis/Coding/Review | 保持角色边界，不扩展角色 | 过早增加 Agent 会扩大成本 |
| 确定性 Tool | 无 | Tool Registry、Tool Gateway、ToolResult | 所有工具统一走 Gateway | Agent 可能绕过工具执行 |
| Coding 只输出 Diff | 无 | Unified Diff Schema、Patch Executor | 严格禁止模型直接写宿主机文件 | 路径逃逸和危险 Diff |
| Baseline/Post-patch Test | 无 | Test Runner、失败分类 | 区分原失败、目标失败和回归 | 测试通过不代表补丁正确 |
| Memory | 无 | Short-term、Experience Store、Retriever | 成功经验必须验证后写入 | 数据泄漏、错误经验污染 |
| Reflection | 无 | Failure Classifier、Reflection、Replan | 只能基于真实执行结果 | 虚构反馈会造成错误重试 |
| Code RAG | 无 | AST、BM25、Hybrid Retrieval | 向量检索可配置关闭 | 索引过期、证据不可追溯 |
| Sandbox | 无 | Worktree、Docker、资源和路径策略 | Docker 不可用时使用本地隔离后备 | Docker Daemon 当前阻塞 |
| Benchmark | 无 | Task Format、Runner、Metrics、Ablation | 指标必须由真实运行采集 | 虚构结果会破坏研究可信度 |
| API/CLI | 无 | CLI；FastAPI 为 P1/P2 | 先 CLI 后 API | API 引入过早增加复杂度 |
| 安全和审计 | `.env.example`、`.gitignore` | 权限、超时、脱敏、审计日志 | 所有命令参数化、路径 allowlist | 密钥泄露、宿主机任意执行 |
| Fake LLM 测试 | smoke test | Fake LLM、Mock Tool、集成测试 | M1 必须不调用真实模型 | 真实 API 不可用时无法验收 |
| 文档与复现 | Task 0 计划 | README、架构、实验报告 | 每个阶段同步文档 | 文档与实现不一致 |

## 5. 风险清单

### R1：项目不是 Git 仓库

- **影响**：无法执行分支/状态/提交、Git Worktree、Git History 检索和 Diff 复核。
- **优先级**：阻塞 P0 后半段和 M3。
- **处理**：由用户决定是否初始化 Git；Agent 不应自行初始化或提交。

### R2：Docker Daemon 不可用

- **影响**：无法验证镜像、容器隔离、网络禁用、资源限制和 Sandbox。
- **优先级**：阻塞 M3/M9 Docker 部分。
- **处理**：先实现可测试的本地 Worktree 隔离；Docker 测试明确标记 `SKIPPED / NOT VERIFIED`。

### R3：LLM API 未配置

- **影响**：无法验证真实模型调用、Token、成本和生成质量。
- **优先级**：不阻塞 M1 Fake LLM，阻塞真实端到端验证。
- **处理**：M1-M4 使用 Fake LLM；真实结果出现前不得声称模型能力。

### R4：PostgreSQL/pgvector 未配置

- **影响**：无法验证长期 Memory、向量检索和多任务持久化。
- **优先级**：不阻塞 P0，阻塞部分 P1 性能验证。
- **处理**：开发阶段使用 SQLite；向量检索可关闭。

### R5：依赖未锁定

- **影响**：LangGraph、Checkpoint 和第三方 API 可能随版本变化。
- **优先级**：阻塞 M1 的稳定开发。
- **处理**：使用 uv 创建 3.11+ 环境，核对真实 API，生成 `uv.lock`。

### R6：Python 版本混杂

- **影响**：系统 Python 3.9.6 不满足要求。
- **处理**：测试和开发命令固定使用 Python 3.11+。

### R7：工作区包含其他项目

- **影响**：从父目录运行 pytest 会收集无关项目测试。
- **处理**：所有 RepoPilot 命令在 `agent/RepoPilot` 内执行，避免根目录全局测试。

### R8：Benchmark 数据缺失

- **影响**：无法验证成功率、回归率、Memory/Reflection 贡献。
- **处理**：先建立 5 个最小 Fixture，再扩展 10-30 个任务；禁止提前报告指标。

## 6. 15 个工作日实施计划

| 工作日 | 里程碑与交付 | 优先级 | 依赖 | 验收重点 | 阻塞风险 |
|---|---|---|---|---|---|
| Day 1 | 项目基线：Python 3.11+ uv 环境、依赖核对、`uv.lock`、测试/Lint 基线 | P0 | 阶段 0 确认 | `uv run pytest` 可复现；第三方 API 已核对 | Git 未初始化；Python 混杂 |
| Day 2 | 核心 Schema：TaskRequest、State、TaskPlan、Evidence、Diagnosis、Patch/Test/Review | P0 | Day 1 | Pydantic v2 校验、非法计划和 DAG 环测试通过 | Schema 过度抽象 |
| Day 3 | LangGraph Runtime：最小节点、条件路由、Fake LLM、结构化输出解析 | P0 | Day 2 | 不调用真实 LLM 跑通 Graph；错误输出被拒绝 | LangGraph API/版本未验证 |
| Day 4 | Tool Registry/Gateway：注册、Schema、权限、超时、ToolResult、只读工具 | P0 | Day 2 | `list_files/search_code/read_file/git_*` 全部受控 | 路径逃逸；绕过 Gateway |
| Day 5 | 隔离与补丁：Worktree、Unified Diff 校验、Patch Executor、Baseline/Post-patch Test | P0 | Day 4 | 补丁只在隔离区应用；测试结果真实记录 | 无 Git 仓库；Docker 不可用 |
| Day 6 | P0 端到端闭环：Planner 到 Report，一个 Bug Demo，执行轨迹和预算 | P0 | Day 3-5 | Fake LLM 下完整流程可重复；失败可分类 | 端到端联调范围膨胀 |
| Day 7 | Code RAG：文件扫描、AST 切分、Symbol Index、BM25、Evidence | P1 | Day 4 | 证据包含路径、行号、符号；索引绑定 Commit | 无 Git 导致 Commit 绑定受限 |
| Day 8 | Memory：SQLite Checkpointer、Experience Schema、成功/失败分流、跨任务检索 | P1 | Day 3, Day 7 | Gold Patch 不泄漏；只有验证成功可标 `verified_success` | 数据泄漏；经验污染 |
| Day 9 | Adaptive Planning：复杂度特征、DAG 校验、动态路由、预算控制 | P1 | Day 3, Day 4 | Plan 变更可追踪；预算超限能终止 | 重试循环；过度规划 |
| Day 10 | Reflection：失败分类、Reflection Schema、Replanning、独立重试预算 | P1 | Day 6 | 至少四类失败；反馈来自真实测试/工具结果 | 虚构反馈；Patch 无限重试 |
| Day 11 | 可靠性：Checkpoint Resume、审批、取消、超时、日志脱敏、Docker 策略 | P1 | Day 5, Day 8 | 可恢复/可取消；敏感信息不落日志 | Docker 阻塞；审批能力不可伪造 |
| Day 12 | Benchmark 基础：任务格式、5 个 Fixture、Runner、结果持久化、基础指标 | P1 | Day 6 | 每个结果来自真实运行；Gold Patch 隔离 | 样本少；结果不可复现 |
| Day 13 | 对比与消融：Single Agent、Static Multi-Agent、Memory/Planning/Reflection Ablation | P1 | Day 8-12 | 同模型/预算/任务；报告原始任务结果 | 配置不一致；过度统计声称 |
| Day 14 | CLI/Demo/可观测性：Trace、Diff、测试报告、成本；FastAPI 仅在稳定后进行 | P0/P2 | Day 6, Day 12 | CLI 一条命令演示；FastAPI 为可选 P2 | API 抢占核心稳定性 |
| Day 15 | 文档、复现、最终验收：README、架构、实验报告、已知限制、完整测试 | P0/P2 | Day 1-14 | P0 清单完成；未验证项明确标记；P2 不阻塞交付 | 文档虚构结果；P2 范围失控 |

### P0、P1、P2 边界

- **P0**：Day 1-6 的端到端闭环，以及 Day 14 的 CLI/演示和 Day 15 的文档验收。
- **P1**：Day 7-13 的 RAG、Memory、Planning、Reflection、可靠性和 Benchmark。
- **P2**：FastAPI、MCP、Web UI、外部 SWE-bench Lite、复杂并行/DAG 调度。只有 P0/P1 稳定后才进行。

## 7. 下一阶段建议

下一阶段应执行 **M1：Fake LLM 下的 LangGraph 流程**，对应 Day 1-3 的核心部分。

建议范围：

1. 使用 uv 创建 Python 3.11+ 环境。
2. 核对并锁定 Pydantic v2、LangGraph 和 pytest 的真实版本/API。
3. 定义核心 State 和 Agent 输入输出 Schema。
4. 实现最小 Planner、Research、Diagnosis 节点和条件路由。
5. 使用 Fake LLM 和 Mock Tool 跑通结构化流程。
6. 添加 Schema、路由、无效输出和预算检查测试。
7. 更新 README/架构文档中的 M1 状态。

M1 开始前需要确认：

- 是否允许初始化 Git 仓库；Agent 不会自行执行。
- 是否使用当前 Python 3.12.7，还是通过 uv 固定 Python 3.11/3.12。
- Docker Daemon 和 LLM API 是否会在 M3/M4 前恢复；若不会，继续采用明确的 `SKIPPED / NOT VERIFIED` 策略。

## 8. 阶段 0 结论

当前仓库处于可继续开发的最小骨架状态，但尚未具备完整 Agent 系统。P0 端到端闭环可以在没有真实 LLM、PostgreSQL 和 Docker 的情况下使用 Fake LLM、SQLite 后备和可测试隔离接口推进；真实模型、数据库、Docker 和 Benchmark 指标必须等待环境可用后验证，当前不得填写任何虚构结果。
