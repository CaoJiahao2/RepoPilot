# RepoPilot：编程 Agent 开发任务说明

> **文档用途**：本文件是 RepoPilot
> 项目的产品需求、技术设计、开发路线和验收规范。请将本文件放在仓库根目录，文件名建议为
> `AGENTS.md` 或 `REPOPILOT_IMPLEMENTATION_SPEC.md`，并要求编程 Agent
> 在开始修改代码前完整阅读。
>
> **项目目标**：在 3 周内交付一个可运行、可评测、可演示的自适应多 Agent
> 软件故障诊断与修复系统。项目同时服务于工程能力展示和 Agent 机制研究。
>
> **核心原则**：先完成端到端闭环，再逐步加入
> Planning、Memory、Reflection；先保证可复现和安全，再追求复杂架构。不要为了体现技术栈而堆叠框架。

------------------------------------------------------------------------

## 0. 给编程 Agent 的执行指令

你是本项目的资深 AI Agent
工程师。你的任务不是只生成代码片段，而是持续检查仓库、拆解任务、实现功能、运行测试、修复问题，并维护项目文档。

### 0.1 开始工作前必须执行

1.  检查当前工作目录、Git 状态、已有文件、Python 版本和依赖管理方式。
2.  如果仓库已有代码，先理解现有架构和编码约定；**不得未经检查就覆盖已有文件或重建项目**。
3.  阅读本文件，整理当前阶段的任务清单。
4.  检查可用模型 API、数据库和 Docker
    环境。不得假定这些服务已经配置完成。
5.  如果存在会影响架构的缺失信息，先提出最少量的澄清问题；否则采用本文的默认方案并继续。
6.  先建立可运行的最小骨架和测试，再扩展功能。

### 0.2 每次开发任务的工作方式

每次只实现一个可验证的垂直切片，按以下顺序执行：

1.  说明本次要实现的目标、涉及文件和验收标准。
2.  检查相关代码及依赖的真实 API，不要臆造第三方库接口。
3.  实现最小必要改动。
4.  添加或更新单元测试、集成测试。
5.  运行相关测试和静态检查。
6.  修复本次改动引入的问题。
7.  更新 README、配置示例或设计文档。
8.  汇报：已完成内容、测试命令及结果、未完成项、已知风险、下一步建议。

不要在没有运行测试的情况下声称功能已通过。测试因 API Key、网络或 Docker
不可用而跳过时，必须明确标记为 `SKIPPED`，不能标记为 `PASSED`。

### 0.3 通用开发约束

-   Python 3.11+，类型标注优先，使用 Pydantic v2 做边界数据校验。
-   使用 `pyproject.toml` 管理依赖；优先沿用仓库已有的 `uv`、Poetry
    或其他工具，不要重复引入包管理器。
-   核心业务逻辑必须可在不调用真实 LLM
    的情况下测试。通过接口、依赖注入和 Fake/Mock 实现测试隔离。
-   LLM 输出必须经过结构化解析和 Schema
    校验；不能把模型输出直接当作可信指令执行。
-   所有模型、数据库、Embedding、Reranker
    和工具执行配置均从环境变量或配置文件读取。
-   不得硬编码 API Key、密码、内部地址或用户数据；`.env` 必须加入
    `.gitignore`。
-   不得伪造 Benchmark 结果、成功率、性能提升或成本数据。
-   不要在日志中记录密钥、完整环境变量、敏感文件内容。
-   不要让 Agent 获得宿主机任意 Shell 权限。
-   默认不允许 Agent 自动向远程仓库 push、创建 PR、合并代码或部署。
-   避免过度抽象。没有第二个真实实现需求时，不要为了"可扩展性"创建复杂插件体系。
-   不要无必要地同时引入 LangChain、CrewAI、AutoGen 等多个 Agent
    框架。本项目以 LangGraph 为主。
-   不要将"多个 Prompt
    串联"描述成算法创新；研究贡献必须由明确机制和实验支撑。

------------------------------------------------------------------------

## 1. 项目概述

### 1.1 项目名称

**RepoPilot --- Adaptive Multi-Agent System for Software Debugging and
Repair**

面向 Python 软件仓库的多 Agent 故障诊断与自动修复系统。用户提交 Bug
描述、异常堆栈和本地仓库路径，系统完成代码检索、根因分析、补丁生成、隔离测试、失败反思和修复报告。

### 1.2 目标用户与使用场景

目标用户是希望通过自然语言处理软件缺陷的软件开发者。

典型输入：

-   Bug 描述：`parse_config 在输入为空字典时抛出 TypeError`
-   异常堆栈：可选
-   仓库路径：本地 Git 仓库
-   测试命令：例如 `pytest tests/test_parser.py -q`
-   可选约束：允许修改的目录、禁止修改的文件、最大执行时间

典型输出：

-   问题理解和执行计划
-   相关代码证据（文件路径、行号、符号）
-   根因假设和证据
-   补丁 Diff
-   修改文件列表
-   测试前后结果
-   Review 结论
-   Agent/Tool 执行轨迹
-   Token、耗时、重试次数和成本统计
-   是否需要人工批准

### 1.3 项目目标

**工程目标**

1.  通过 LangGraph 实现可观察、可恢复的 Agent 工作流。
2.  通过统一 Tool Registry 执行
    Git、代码搜索、文件读取、补丁应用和测试。
3.  通过隔离环境运行不可信代码和测试。
4.  支持任务状态持久化、有限重试、超时和预算控制。
5.  提供 CLI 或 FastAPI 接口，以及可复现的端到端 Demo。

**研究目标**

1.  比较静态工作流与自适应任务规划的效果和成本。
2.  评估跨任务经验记忆对相似 Bug 修复的影响。
3.  评估基于真实执行反馈的 Reflection 对失败恢复的贡献。
4.  在统一数据集、模型和预算下开展对比实验和消融实验。

### 1.4 非目标（3 周内不做）

-   不训练或微调基础大模型。
-   不实现强化学习 Planner。
-   不支持所有编程语言；第一阶段只支持 Python。
-   不追求完全无人监督地修改和提交生产代码。
-   不自动执行任意网络请求、安装任意依赖或访问宿主机敏感目录。
-   不实现复杂的分布式 Agent 集群。
-   不把 MCP 当成系统内部所有模块的通信总线。
-   不以 UI 的复杂程度作为项目完成标准。

------------------------------------------------------------------------

## 2. MVP 范围与优先级

### P0：必须完成

1.  用户提交一个本地 Python Git 仓库和 Bug 描述。
2.  系统能创建独立任务工作区。
3.  LangGraph 能执行至少
    `Planner → Research → Diagnosis → Coding → Test → Review → Report`。
4.  工具统一注册、参数校验、超时、错误处理和执行记录。
5.  Coding Agent 只能输出 Unified Diff；由受控执行器应用补丁。
6.  修改前运行 Baseline Test，修改后运行目标测试和回归测试。
7.  测试失败时可分类并触发有限次 Reflection/Replanning。
8.  支持任务状态持久化或至少可靠的本地任务记录。
9.  有至少 10 个可复现的本地开发任务；最终目标扩展到 20--30 个。
10. 有自动化测试、README、配置示例和端到端运行说明。

### P1：应完成

1.  AST 函数/类级代码切分。
2.  BM25 + 向量检索的 Hybrid Retrieval。
3.  跨任务 Experience Memory。
4.  Adaptive Planning 与预算约束。
5.  Checkpoint 恢复和 Human-in-the-loop 审批。
6.  Benchmark Runner、指标统计和消融实验脚本。
7.  Docker Sandbox。

### P2：时间允许再做

1.  MCP Server/Client Adapter。
2.  SWE-bench Lite 小规模外部验证。
3.  Web 可视化界面。
4.  并行执行无副作用的检索任务。
5.  更复杂的 DAG Scheduler。

**优先级规则**：如果时间不足，优先保证 P0 完整可用；P1 中优先
Memory、Reflection、评测；P2 不得阻塞核心闭环。

------------------------------------------------------------------------

## 3. 系统架构

### 3.1 分层架构

``` text
CLI / FastAPI
     |
     v
Task Service
     |
     v
LangGraph Runtime  <---- Checkpointer
     |
     +---- Planner Agent
     |
     +---- Research Agent <---- Code Index / Retrieval
     |
     +---- Diagnosis Agent
     |
     +---- Coding Agent
     |
     +---- Review Agent
     |
     +---- Reflection / Replanner
     |
     v
Tool Gateway / Tool Registry
     |
     +---- Git Tools
     +---- File/Search Tools
     +---- Patch Executor
     +---- Test Runner
     +---- Static Analysis Tools
     +---- MCP Adapter (optional)
     |
     v
Isolated Worktree / Docker Sandbox
     |
     v
PostgreSQL (+ pgvector optional)
     |
     +---- Task Records
     +---- Experience Memory
     +---- Code Chunks / Embeddings
     +---- Evaluation Records

Observability:
  structured logs / execution traces / token & latency accounting
```

### 3.2 核心架构原则

-   **Agent 决策，Tool 执行，Graph 控制流程，Store 持久化数据。**
-   Agent 之间通过有类型的结构化 State
    交换必要信息，不依赖自由聊天历史。
-   确定性操作（Git、文件读写、pytest、Diff 应用）必须由工具完成，不让
    LLM 模拟执行结果。
-   LLM 负责不确定性较高的理解、假设、规划和代码生成。
-   所有执行动作都必须受任务预算、工具权限和沙箱策略约束。
-   Research 输出证据；Diagnosis 输出可追溯根因假设；Coding
    输出补丁；Test Runner 给出真实测试结果；Review 综合判断。
-   测试通过不等于补丁正确；测试失败也不必然代表补丁错误，需要区分环境失败、原有失败和新增回归。

### 3.3 Agent 职责与输入输出

  ---------------------------------------------------------------------------------------------------------------------
  Agent             输入                                  输出                   约束
  ----------------- ------------------------------------- ---------------------- --------------------------------------
  Planner           Issue、堆栈、仓库元信息、Memory       TaskPlan、NextAction   动作必须属于允许集合
                    Hits、当前执行反馈

  Research          Issue、堆栈、TaskPlan                 Evidence 列表          每条证据尽量有文件、行号、符号和来源

  Diagnosis         Evidence、Baseline Test、Issue        Diagnosis              必须引用 Evidence ID，不得编造代码位置

  Coding            Diagnosis、相关代码、历史经验、约束   Unified Diff           不得直接修改宿主机文件

  Review            Diff、测试报告、诊断和约束            ReviewResult           优先依赖客观测试和 Diff 证据

  Reflection        Failure Report、历史轨迹、预算        ReflectionResult       需要输出失败类型和下一步动作
  ---------------------------------------------------------------------------------------------------------------------

Test Runner 是确定性 Tool，不单独设计成 LLM Agent。

------------------------------------------------------------------------

## 4. 推荐项目目录

如果仓库尚为空，可采用以下结构；如果已有结构，应在不破坏现有约定的前提下映射模块，不要机械重建。

``` text
RepoPilot/
├── AGENTS.md
├── README.md
├── pyproject.toml
├── .env.example
├── .gitignore
├── docker-compose.yml
├── configs/
│   ├── app.yaml
│   ├── models.yaml
│   ├── agents.yaml
│   └── evaluation.yaml
├── src/repopilot/
│   ├── api/
│   │   ├── main.py
│   │   ├── routes.py
│   │   └── schemas.py
│   ├── cli/
│   │   └── main.py
│   ├── core/
│   │   ├── config.py
│   │   ├── state.py
│   │   ├── schemas.py
│   │   ├── graph.py
│   │   ├── routing.py
│   │   ├── budget.py
│   │   └── errors.py
│   ├── agents/
│   │   ├── base.py
│   │   ├── planner.py
│   │   ├── research.py
│   │   ├── diagnosis.py
│   │   ├── coding.py
│   │   └── review.py
│   ├── planning/
│   │   ├── task_decomposer.py
│   │   ├── policy.py
│   │   └── replanner.py
│   ├── memory/
│   │   ├── short_term.py
│   │   ├── experience_store.py
│   │   └── retriever.py
│   ├── retrieval/
│   │   ├── parser.py
│   │   ├── chunker.py
│   │   ├── sparse.py
│   │   ├── vector.py
│   │   └── fusion.py
│   ├── tools/
│   │   ├── base.py
│   │   ├── registry.py
│   │   ├── executor.py
│   │   ├── git.py
│   │   ├── files.py
│   │   ├── search.py
│   │   ├── patch.py
│   │   └── tests.py
│   ├── sandbox/
│   │   ├── worktree.py
│   │   ├── docker.py
│   │   └── policy.py
│   ├── reflection/
│   │   ├── classifier.py
│   │   ├── reflector.py
│   │   └── retry_policy.py
│   ├── evaluation/
│   │   ├── dataset.py
│   │   ├── runner.py
│   │   ├── metrics.py
│   │   ├── ablation.py
│   │   └── report.py
│   └── observability/
│       ├── tracing.py
│       ├── logging.py
│       └── cost.py
├── benchmarks/
│   ├── tasks/
│   ├── results/
│   └── README.md
├── tests/
│   ├── unit/
│   ├── integration/
│   └── e2e/
├── scripts/
│   ├── index_repo.py
│   ├── run_task.py
│   ├── run_benchmark.py
│   └── run_ablation.py
├── docker/
│   ├── Dockerfile.sandbox
│   └── sandbox-compose.yml
└── docs/
    ├── architecture.md
    ├── benchmark.md
    ├── experiments.md
    └── decisions.md
```

------------------------------------------------------------------------

## 5. 核心数据结构与接口契约

先实现稳定的数据结构，再开发
Agent。字段可以根据实现调整，但必须保持职责清晰并更新文档和测试。

### 5.1 Task 输入

``` python
from pydantic import BaseModel, Field
from typing import Literal


class TaskRequest(BaseModel):
    task_id: str
    repo_path: str
    issue: str = Field(min_length=5)
    stack_trace: str | None = None
    test_command: list[str] | None = None
    allowed_paths: list[str] = []
    forbidden_paths: list[str] = []
    max_runtime_seconds: int = 900
    max_llm_calls: int = 30
    max_total_tokens: int = 100_000
    max_patch_retries: int = 3
    require_approval: bool = True
```

注意：`repo_path`
必须经过路径规范化和允许目录检查。不要仅依赖前端传入路径。

### 5.2 Planner Schema

``` python
from pydantic import BaseModel, Field
from typing import Literal


Action = Literal[
    "search", "inspect", "diagnose", "patch",
    "test", "review", "replan", "finish"
]


class PlannedStep(BaseModel):
    step_id: str
    action: Action
    description: str
    depends_on: list[str] = []
    expected_output: str


class TaskPlan(BaseModel):
    objective: str
    steps: list[PlannedStep] = Field(min_length=1, max_length=8)
    next_action: Action
    rationale: str
```

必须验证：

-   `step_id` 唯一。
-   `depends_on` 引用存在的 step。
-   依赖关系无环。
-   `next_action` 属于允许动作。
-   不允许 Planner 自行创建任意工具名或 Shell 命令。
-   任务完成后不得继续创建新步骤。

### 5.3 Evidence Schema

``` python
class Evidence(BaseModel):
    evidence_id: str
    source_type: Literal[
        "stack_trace", "source_code", "test",
        "git_history", "issue", "memory"
    ]
    file_path: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    symbol: str | None = None
    content: str
    retrieval_score: float | None = None
```

### 5.4 Diagnosis Schema

``` python
class Diagnosis(BaseModel):
    root_cause: str
    affected_files: list[str]
    related_symbols: list[str]
    evidence_ids: list[str]
    confidence: float = Field(ge=0, le=1)
    alternative_hypotheses: list[str] = []
    suggested_fix: str
    missing_information: list[str] = []
```

`confidence`
是模型给出的主观评分，不应被解释为校准后的概率。后续需要用实际数据分析其可信度。

### 5.5 Patch 与 Review Schema

``` python
class PatchResult(BaseModel):
    unified_diff: str
    modified_files: list[str]
    explanation: str
    risks: list[str] = []


class ReviewResult(BaseModel):
    approved: bool
    failure_type: str | None = None
    evidence: list[str] = []
    feedback: str
    next_action: Literal[
        "finish", "re_search", "re_diagnose",
        "re_patch", "fix_environment", "human_review"
    ]
```

### 5.6 统一 State

建议使用 TypedDict 或项目中已经采用的 LangGraph State
类型。不要把所有对象都变成无约束的 `dict[str, Any]`。

State 至少包含：

``` text
task: TaskRequest
plan: TaskPlan | None
current_action: Action
evidence: list[Evidence]
memory_hits: list[Experience]
diagnosis: Diagnosis | None
baseline_test_report: TestReport | None
patch_result: PatchResult | None
test_report: TestReport | None
review_result: ReviewResult | None
reflection_result: ReflectionResult | None
retry_counts: RetryCounters
budget: BudgetState
status: TaskStatus
execution_trace: list[TraceEvent]
```

状态更新必须避免 Reducer 误用：只有真正需要累加的列表字段使用追加
Reducer；Plan、Diagnosis、Review 等字段应由新结果覆盖。不要把旧轮次的
Patch 和 Test Report 混入当前轮结果。

------------------------------------------------------------------------

## 6. 工作流与状态机

### 6.1 主工作流

``` text
START
  |
  v
validate_task
  |
  v
prepare_workspace
  |
  v
load_memory
  |
  v
planner
  |
  +---- search / inspect ---> research
  |                              |
  |                              v
  +-------------------------- diagnosis
                                 |
                                 v
                           baseline_tests
                                 |
                                 v
                              coding
                                 |
                                 v
                            validate_diff
                                 |
                                 v
                            apply_patch
                                 |
                                 v
                            run_tests
                                 |
                                 v
                              review
                                 |
                   +-------------+-------------+
                   |             |             |
                approved        retry         failed
                   |             |             |
                   v             v             v
              human_approval  reflection     report
                   |             |
                   v             v
                report <----- planner
                   |
                   v
                  END
```

这是逻辑流程示意，不要求所有节点都严格线性连接。根据任务状态可以跳过不必要节点，但跳过条件必须显式记录。

### 6.2 失败分类

至少实现以下类型：

  -----------------------------------------------------------------------------------
  Failure Type            证据                             推荐动作
  ----------------------- -------------------------------- --------------------------
  `patch_error`           Patch 无法应用或语法错误         重新生成 Patch

  `regression`            新增测试失败                     回滚当前 Patch，重新诊断

  `wrong_root_cause`      目标测试仍失败且原假设被证伪     回到 Research/Diagnosis

  `missing_context`       证据不足或关键依赖未检索         补充检索

  `test_env_error`        测试环境、依赖或权限错误         修复环境，不盲目修改代码

  `tool_failure`          工具超时、进程异常或工具不可用   根据幂等性有限重试

  `budget_exceeded`       预算耗尽                         终止或请求人工介入
  -----------------------------------------------------------------------------------

### 6.3 重试预算

分别维护，不要用一个 Retry Counter 代替全部预算：

``` yaml
limits:
  max_patch_retries: 3
  max_replans: 2
  max_tool_retries: 2
  max_llm_calls: 30
  max_total_tokens: 100000
  max_runtime_seconds: 900
```

每次调用 LLM 或工具之前检查预算。超预算时返回明确的 `budget_exceeded`
状态，不得无限循环。

### 6.4 Human-in-the-loop

默认策略：

-   可以自动读取仓库和运行受控测试。
-   可以在隔离工作区生成和应用补丁。
-   最终补丁导出到用户指定位置前需要人工确认。
-   远程 push、PR、merge、部署等动作不在 MVP 范围内。
-   通过 LangGraph interrupt/resume 或等价机制实现审批；如果 3
    周内无法稳定实现，先提供 CLI 人工确认，不要伪造审批能力。

------------------------------------------------------------------------

## 7. Memory 设计

### 7.1 短期记忆

短期记忆是单次任务状态：

-   当前 Plan 和步骤状态。
-   当前轮 Evidence、Diagnosis、Patch。
-   工具调用结果。
-   失败分类和重试计数。
-   Token/时间预算。
-   执行轨迹。

优先使用 LangGraph Checkpointer 持久化。开发阶段可使用
SQLite；需要多任务服务时使用 PostgreSQL Checkpointer。实际依赖与 API
版本必须先检查并锁定。

### 7.2 长期经验记忆

长期记忆保存跨任务可复用的经验，而不是无差别保存所有对话。

建议结构：

``` python
class Experience(BaseModel):
    experience_id: str
    issue_summary: str
    error_type: str | None = None
    repository_fingerprint: str | None = None
    affected_symbols: list[str] = []
    root_cause: str
    solution_summary: str
    patch_summary: str
    validation_summary: str
    outcome: Literal["verified_success", "failed", "uncertain"]
    applicability_conditions: list[str] = []
    embedding_text: str
    created_at: str
```

写入规则：

1.  只有补丁通过目标测试和必要回归测试后，才可标记为
    `verified_success`。
2.  失败案例可以保存，但必须标记为 `failed`，不能和成功经验混淆。
3.  保存仓库指纹、依赖版本或相关上下文，减少错误迁移。
4.  不保存密钥、环境变量、用户敏感数据或不必要的完整源码。
5.  记忆检索结果只是参考证据，不能直接覆盖当前代码事实。

### 7.3 检索策略

第一版可按以下顺序实现：

1.  精确符号/文件路径检索。
2.  BM25 关键词检索。
3.  向量语义检索（可选）。
4.  RRF 或加权融合。
5.  可选 Reranker。

如果没有 Embedding API 或数据库环境，先实现 BM25 + SQLite/PostgreSQL
文本存储接口，确保主流程可用；向量检索必须可配置关闭。

初始融合公式：

``` text
score(d) =
  alpha * normalized_bm25(d)
  + beta * normalized_vector(d)
  + gamma * symbol_match(d)
```

权重是实验参数，不得在没有实验时宣称最优。

### 7.4 Memory 实验隔离

Benchmark 必须防止数据泄漏：

-   测试任务的 Gold Patch 和隐藏测试不能写入 Memory。
-   同一任务的未来答案不能被当前任务检索到。
-   若研究跨任务经验复用，明确区分训练/经验构建集和评测集。
-   记录每次检索的 Memory ID、分数和最终是否被 Planner 使用。

------------------------------------------------------------------------

## 8. Code RAG 设计

### 8.1 索引流程

``` text
Repository
  |
  v
File Scanner
  |
  v
Ignore Rules (.gitignore + configured exclusions)
  |
  v
Python AST Parser
  |
  v
Function/Class Chunker
  |
  +---- Symbol Index
  +---- BM25 Index
  +---- Vector Index (optional)
  |
  v
Hybrid Retrieval
  |
  v
Evidence with path/line/symbol
```

### 8.2 索引规则

-   默认只索引 `.py` 文件和必要项目文档。
-   遵循 `.gitignore`。
-   排除 `.git`、虚拟环境、构建目录、缓存、二进制文件和密钥文件。
-   限制单文件大小和总索引规模。
-   AST 解析失败时允许退化为文本分块，并记录错误。
-   每个 Chunk 保留文件路径、起止行号、符号名、符号类型和内容。
-   索引需要绑定 Git Commit Hash，避免代码变更后使用过期索引。

### 8.3 检索优先级

1.  异常堆栈明确给出的文件/行号。
2.  堆栈函数及其调用关系。
3.  相关测试文件。
4.  关键词和 BM25。
5.  向量语义检索。
6.  Reranker。

不要让向量检索取代异常堆栈的精确定位。

------------------------------------------------------------------------

## 9. Tool Registry 与 Sandbox

### 9.1 统一工具接口

每个工具应提供：

-   名称和描述。
-   Pydantic 输入 Schema。
-   风险等级。
-   超时时间。
-   是否幂等。
-   是否需要审批。
-   执行函数。
-   结构化结果。

统一结果示例：

``` python
class ToolResult(BaseModel):
    tool_name: str
    success: bool
    output: str = ""
    error_code: str | None = None
    error_message: str | None = None
    duration_ms: int
    artifacts: list[str] = []
```

### 9.2 第一批工具

  Tool                   能力                    权限
  ---------------------- ----------------------- ---------
  `list_files`           列出允许范围内的文件    Read
  `search_code`          搜索文本/符号           Read
  `read_file`            读取允许范围内的文件    Read
  `git_status`           查看工作区状态          Read
  `git_diff`             查看 Diff               Read
  `run_baseline_tests`   修改前运行测试          Execute
  `apply_patch`          在隔离工作区应用 Diff   Write
  `run_tests`            运行测试                Execute
  `run_lint`             执行静态检查            Execute

### 9.3 安全要求

-   通过 `Path.resolve()` 校验真实路径，阻止 `../` 和符号链接逃逸。
-   命令使用参数数组执行，不使用 `shell=True` 拼接不可信字符串。
-   命令必须有
    allowlist；测试命令来自受控配置，不直接接受任意模型生成命令。
-   限制执行时间、输出大小、CPU、内存和进程数。
-   Docker 容器使用非 root 用户，默认禁用网络，限制挂载目录。
-   不挂载宿主机 Home、SSH、云凭证或 Docker Socket。
-   对补丁文件路径进行 allowlist 校验。
-   对超大 Diff、二进制文件和敏感文件修改直接拒绝。
-   每个任务使用独立临时目录或 Git Worktree。
-   任务结束后清理临时容器和临时文件；保留用户明确要求保留的产物。
-   所有工具操作记录审计日志，但不记录秘密信息。

**重要**：Docker
是隔离层之一，不是自动安全保证。不要把不可信代码容器与宿主机敏感资源连接起来。

### 9.4 MCP

MCP 是可选的工具接入适配层：

``` text
Agent -> Tool Gateway -> Native Tool
                       -> MCP Client -> MCP Server
```

先完成原生 Tool Registry。只有在核心流程稳定后，才增加一个最小 MCP
Server（例如只读仓库搜索工具）和 Client Adapter。MCP
不应成为内部业务状态流转的必要依赖。

------------------------------------------------------------------------

## 10. Benchmark 与实验设计

### 10.1 数据集

最终目标 20--30 个任务，先以 5 个任务开发，再扩充。

每个任务必须包含：

``` text
task_id
repository_url_or_local_fixture
base_commit
issue
stack_trace (optional)
test_command
expected_behavior
gold_patch (evaluation only)
verification_command
metadata
```

建议两类任务：

1.  **自建 Mini-Benchmark**：20--30 个可复现 Python
    Bug，适合调试和消融。
2.  **外部验证**：时间允许时选取 5--10 个 SWE-bench Lite
    任务，使用其官方评测流程。不要在 3 周计划中承诺完整 SWE-bench 成绩。

Benchmark 运行时，Agent 只能看到 Issue、必要堆栈和仓库；Gold
Patch、隐藏验证信息不得暴露。

### 10.2 对比实验

至少实现：

  实验组   配置
  -------- -----------------------------------------------------------
  A        Single Agent + Tools
  B        Static Multi-Agent
  C        Static Multi-Agent + Memory
  D        Static Multi-Agent + Reflection
  E        Full RepoPilot（Adaptive Planning + Memory + Reflection）

所有组应尽量使用相同：

-   基础模型及版本。
-   Prompt 基线。
-   工具集合。
-   测试任务。
-   最大 Token/LLM 调用/时间预算。
-   温度及其他生成参数。

如果无法严格一致，必须在报告中披露差异。

### 10.3 指标

**任务效果**

-   Resolution Rate：通过目标验证测试的任务比例。
-   Patch Pass Rate：通过验证测试的有效补丁比例。
-   Regression Rate：引入新增回归的比例。
-   Root Cause Accuracy：经人工或预先定义证据标准核验的根因正确率。

**Agent 行为**

-   Tool Success Rate。
-   Replanning Rate。
-   Reflection Recovery Rate。
-   Memory Retrieval Hit Rate。
-   Memory Useful Rate（检索经验实际帮助解决问题的比例）。

**成本和性能**

-   平均/中位/P95 延迟。
-   平均输入和输出 Token。
-   LLM 调用次数。
-   工具调用次数。
-   单任务成本（有可核验价格时计算）。

**可靠性**

-   Checkpoint Resume Success Rate。
-   Sandbox Execution Success Rate。
-   Patch Apply Failure Rate。
-   Task Timeout Rate。

### 10.4 消融实验

至少做三组：

1.  Full vs. No Adaptive Planning。
2.  Full vs. No Memory。
3.  Full vs. No Reflection。

报告每组成功率、成本、延迟和任务级结果。小样本应报告置信区间或 Bootstrap
区间，避免过度声称统计显著。

### 10.5 实验记录格式

每次任务至少保存：

``` json
{
  "task_id": "example-001",
  "experiment_group": "full",
  "model": "configured-model-id",
  "prompt_version": "v1",
  "success": false,
  "failure_type": "wrong_root_cause",
  "llm_calls": 8,
  "input_tokens": 12000,
  "output_tokens": 2400,
  "tool_calls": 11,
  "duration_seconds": 132.5,
  "patch_applied": true,
  "target_tests_passed": false,
  "regression_detected": false
}
```

这是格式示例，不是实验结果。实际值必须由运行系统采集。

------------------------------------------------------------------------

## 11. API 与运行方式

至少提供 CLI；FastAPI 可以在 CLI 和核心流程稳定后实现。

### 11.1 CLI 示例

``` bash
# 查看帮助
repopilot --help

# 运行一个任务
repopilot run \
  --repo ./sample-project \
  --issue "Fix TypeError in parse_config" \
  --test-command "pytest tests/test_parser.py -q"

# 查看任务状态
repopilot status --task-id <task-id>

# 查看执行轨迹
repopilot trace --task-id <task-id>

# 运行 Benchmark
repopilot benchmark run --dataset benchmarks/tasks --group full
```

CLI 参数必须解析为 `TaskRequest`，不允许绕过校验。

### 11.2 FastAPI（P1）

建议接口：

``` text
POST /api/v1/tasks
GET  /api/v1/tasks/{task_id}
GET  /api/v1/tasks/{task_id}/trace
GET  /api/v1/tasks/{task_id}/artifacts
POST /api/v1/tasks/{task_id}/approve
POST /api/v1/tasks/{task_id}/cancel
```

API 返回任务 ID 和状态。长任务不要阻塞 HTTP 请求直到所有 Agent
执行完成；使用后台任务或任务执行器，并提供状态查询。

------------------------------------------------------------------------

## 12. 配置规范

提供 `.env.example`，至少包括：

``` dotenv
REPOPILOT_ENV=development

LLM_PROVIDER=
LLM_MODEL=
LLM_API_KEY=
LLM_BASE_URL=

DATABASE_URL=sqlite:///./repopilot.db
# 启用 pgvector 时再使用 PostgreSQL DSN

EMBEDDING_PROVIDER=
EMBEDDING_MODEL=
RERANKER_PROVIDER=

CHECKPOINTER_BACKEND=sqlite

SANDBOX_BACKEND=docker
SANDBOX_NETWORK_DISABLED=true
SANDBOX_TIMEOUT_SECONDS=300

MAX_LLM_CALLS=30
MAX_TOTAL_TOKENS=100000
MAX_RUNTIME_SECONDS=900
MAX_PATCH_RETRIES=3

LOG_LEVEL=INFO
```

配置加载时应校验必需字段。没有配置 Embedding
时，系统应能关闭向量检索并继续运行基础流程。

模型供应商应通过统一接口适配，不要将业务代码绑定到单一供应商的私有 API。

------------------------------------------------------------------------

## 13. 测试策略与验收标准

### 13.1 单元测试

至少覆盖：

-   Pydantic Schema 校验。
-   Planner 输出合法性和 DAG 环检测。
-   路径安全检查。
-   Tool Registry 注册、参数校验和超时。
-   Diff 路径校验和 Patch 应用。
-   Failure Classifier。
-   Retry/Budget Policy。
-   Memory 写入过滤和检索排序。
-   指标计算。

### 13.2 集成测试

至少覆盖：

1.  Fake LLM 下完整 Graph 执行。
2.  Tool 执行失败后的状态更新。
3.  测试失败后 Reflection 和 Replanning。
4.  Checkpoint 保存和恢复。
5.  Memory 写入与跨任务检索。
6.  Sandbox 执行测试命令。
7.  补丁应用后 Git Diff 符合预期。

### 13.3 端到端验收

至少有一个可复现 Demo：

``` text
输入 Bug
  -> 解析仓库
  -> 检索代码
  -> 分析根因
  -> 生成 Diff
  -> 应用到隔离工作区
  -> 运行测试
  -> Review
  -> 输出报告
```

### 13.4 项目最终验收清单

-   [ ] 一条命令能够启动 CLI。
-   [ ] 能提交本地 Python 仓库和 Bug 描述。
-   [ ] 至少五个 Agent/模块按职责协作。
-   [ ] Planner 输出结构化计划并通过合法性校验。
-   [ ] Research 输出可追溯 Evidence。
-   [ ] Coding 输出 Unified Diff。
-   [ ] Patch Executor 校验并应用补丁。
-   [ ] Baseline Test 和 Post-patch Test 均有记录。
-   [ ] Reflection 能识别至少四类失败。
-   [ ] Retry、Token、LLM Call 和 Runtime 预算生效。
-   [ ] Memory 可以跨任务检索经验。
-   [ ] 有至少 20 个可复现任务，或清楚说明实际任务数和限制。
-   [ ] 有 Single Agent / Static Multi-Agent / Full System 对比。
-   [ ] 有 Planning、Memory、Reflection 消融结果。
-   [ ] 有执行轨迹和成本记录。
-   [ ] 有 README、架构文档、实验报告和配置示例。
-   [ ] 没有虚构的测试结果或实验指标。
-   [ ] 不会在宿主机上执行 Agent 生成的任意命令。

------------------------------------------------------------------------

## 14. 三周开发排期与每阶段交付物

### Week 1：端到端闭环

**Day 1 --- 项目检查和骨架**

-   检查仓库、环境和依赖。
-   初始化配置、日志、Schema、测试框架。
-   定义 TaskRequest、State、Agent I/O Schema。
-   准备 5 个本地可复现 Bug Fixture。

交付：项目骨架、架构说明、数据结构测试。

**Day 2 --- LangGraph Runtime**

-   实现 Graph 和最小节点。
-   实现 Planner、Research、Diagnosis。
-   实现条件路由。
-   使用 Fake LLM 跑通 Graph。

交付：可测试的 Agent Graph。

**Day 3 --- Tool Registry**

-   实现工具基类、注册表和统一执行器。
-   实现文件、搜索、Git 只读工具。
-   加入超时、异常和执行日志。

交付：可测试的 Tool Gateway。

**Day 4 --- Coding 和测试执行**

-   实现 Diff Schema。
-   实现 Diff 校验和应用。
-   实现独立 Worktree。
-   实现 Baseline Test 和 Post-patch Test。

交付：隔离工作区内的补丁应用和测试执行。

**Day 5 --- 端到端联调**

-   接入 Review。
-   接通完整流程。
-   保存执行轨迹。
-   修复最主要的联调问题。

交付：至少一个端到端 Bug 修复 Demo。

### Week 2：研究机制

**Day 6--7 --- Code RAG**

-   AST 解析和函数/类切分。
-   BM25 检索。
-   Embedding 和向量检索（环境允许时）。
-   融合排序和证据来源管理。

交付：代码检索模块及检索测试。

**Day 8 --- Memory**

-   Checkpointer。
-   Experience Schema 和 Store。
-   成功/失败经验分流。
-   跨任务检索。

交付：短期状态和长期经验记忆。

**Day 9 --- Adaptive Planning**

-   任务复杂度特征。
-   结构化 TaskPlan。
-   DAG 合法性校验。
-   动态路由和预算检查。

交付：自适应规划模块。

**Day 10 --- Reflection**

-   Failure Classifier。
-   Reflection Schema。
-   失败反馈到 Planner。
-   分别限制 Patch Retry、Replan 和 Tool Retry。

交付：失败恢复闭环。

### Week 3：可靠性、评测和展示

**Day 11 --- 可靠性和人工审批**

-   Checkpoint 恢复。
-   人工确认。
-   任务取消和超时。
-   日志脱敏和预算保护。

交付：可恢复、可控的执行流程。

**Day 12 --- Benchmark Runner**

-   任务数据格式。
-   运行器和结果持久化。
-   指标计算。
-   先完成 10--15 个任务，再尽量扩展到 20--30 个。

交付：可重复运行的 Benchmark。

**Day 13 --- 对比和消融实验**

-   Single Agent。
-   Static Multi-Agent。
-   Memory Ablation。
-   Reflection Ablation。
-   Planning Ablation。

交付：实验原始数据和分析结果。

**Day 14 --- API/Demo 和优化**

-   CLI 完善。
-   FastAPI（如果核心功能已稳定）。
-   执行轨迹、Diff、测试结果展示。
-   处理最主要的性能和稳定性问题。

交付：可展示 Demo。

**Day 15 --- 文档和验收**

-   README。
-   架构设计。
-   实验报告。
-   已知限制。
-   项目演示脚本。
-   完整测试。

交付：可供他人复现的 Git 仓库。

------------------------------------------------------------------------

## 15. 推荐开发顺序：不要一次性生成整个项目

编程 Agent 应严格按以下里程碑执行，不要一次生成所有模块后再尝试运行。

  里程碑   完成定义                             优先级
  -------- ------------------------------------ --------
  M0       项目检查、配置、Schema、测试框架     P0
  M1       Fake LLM 下 LangGraph 流程通过测试   P0
  M2       Tool Registry 和只读工具             P0
  M3       Worktree、Patch、Test Runner         P0
  M4       端到端修复一个 Bug                   P0
  M5       Code RAG                             P1
  M6       Memory                               P1
  M7       Adaptive Planning                    P1
  M8       Reflection                           P1
  M9       Sandbox、恢复和预算                  P1
  M10      Benchmark 和消融实验                 P1
  M11      MCP、Web UI、外部 Benchmark          P2

每个里程碑必须满足：

-   代码已提交或改动范围清晰。
-   测试可运行。
-   文档同步更新。
-   配置不依赖本机私有信息。
-   不破坏已有里程碑。

------------------------------------------------------------------------

## 16. 关键设计决策（ADR）

编程 Agent 不应随意改变以下设计；如确有必要，先说明原因并更新
`docs/decisions.md`。

### ADR-001：LangGraph 作为主编排框架

理由：显式状态、条件边、Checkpoint 和中断恢复适合有状态的 Agent 工作流。

### ADR-002：五个专业 Agent，不继续增加角色

理由：控制协作成本和调试复杂度。测试、Git、文件等确定性操作使用
Tool，而非 LLM Agent。

### ADR-003：Coding Agent 只输出 Diff

理由：将模型生成和实际文件写入隔离，便于审计、验证、回滚和人工审批。

### ADR-004：Baseline Test 是修复流程的一部分

理由：区分仓库原有失败、新增回归和目标问题是否被解决。

### ADR-005：Memory 只将验证结果作为高质量成功经验

理由：避免错误修复经验污染长期记忆。

### ADR-006：先实现原生 Tool Registry，再接 MCP

理由：降低协议开发对核心系统的阻塞。

### ADR-007：核心流程支持 Fake LLM

理由：降低测试成本，保证业务逻辑可复现。

### ADR-008：不以复杂度代替研究贡献

理由：只有通过对比实验和消融实验验证的机制，才能作为项目研究结论。

------------------------------------------------------------------------

## 17. README 和最终展示要求

README 至少包含：

1.  项目简介和目标问题。
2.  系统架构图。
3.  核心 Agent 职责。
4.  Planning、Memory、Reflection 的设计。
5.  技术栈和环境要求。
6.  安装和配置方式。
7.  最小运行示例。
8.  Benchmark 数据格式和运行命令。
9.  对比实验与消融实验结果。
10. 安全设计和已知限制。
11. 项目演示截图或录屏。

演示时至少展示一个完整任务：

-   输入 Bug 和仓库。
-   Planner 生成计划。
-   Research 找到代码证据。
-   Diagnosis 输出根因假设。
-   Coding 生成 Diff。
-   Sandbox 运行测试。
-   测试失败时触发 Reflection。
-   最终输出修复报告和测试结果。

实验结果必须来自实际运行，并注明模型、数据集版本、预算和运行配置。

------------------------------------------------------------------------

## 18. 给编程 Agent 的第一条任务

阅读完本文后，**不要立即实现所有模块**。请先完成以下任务：

### Task 0：仓库审查与实施计划

1.  输出当前仓库目录树（排除 `.git`、虚拟环境、缓存和大型数据目录）。
2.  检查 Python 版本、依赖管理方式和现有依赖。
3.  检查是否存在已有 Agent、API、数据库、测试和 Docker 实现。
4.  检查当前环境是否能访问配置的 LLM、数据库和
    Docker；不得输出任何密钥。
5.  对照本文给出"已有 / 缺失 / 需要调整"的模块清单。
6.  给出适配当前仓库的最小实施计划，标记依赖关系和风险。
7.  只创建或调整必要的项目骨架、配置示例和基础测试；不要在本任务中实现完整
    Agent 系统。

### Task 0 验收标准

-   没有覆盖或删除用户已有代码。
-   有一份 `docs/implementation_plan.md`。
-   有一份 `.env.example`，不含真实凭证。
-   有最小可运行的测试命令。
-   明确记录当前环境无法验证的部分。
-   向用户汇报后再进入 M1。

**完成 Task 0 后暂停，等待用户确认实施计划。**

------------------------------------------------------------------------

## 19. 最终交付原则

RepoPilot 的完成标准不是"代码文件很多"，而是：

1.  能稳定完成至少一个真实 Bug 的端到端诊断和修复验证。
2.  Agent 决策和工具执行边界清晰。
3.  失败后能够根据真实执行证据进行有限恢复。
4.  Memory 能跨任务复用经过验证的经验。
5.  Benchmark 能重复运行并产出真实指标。
6.  系统具备必要的安全边界、日志和成本控制。
7.  其他开发者能够根据 README 复现。

**最终目标：交付一个可运行、可解释、可评测、可复现的 Agent
系统，而不是一个仅能展示对话效果的 Demo。**
