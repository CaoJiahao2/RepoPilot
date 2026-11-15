# 架构决策记录

## ADR-001：LangGraph 是主编排层

使用显式 State、条件边和 Checkpointer，避免把多个 Prompt 串联伪装成 Agent 系统。当前锁定 `langgraph 1.2.20`。

## ADR-002：五个专业 Agent，不继续扩张角色

Planner、Research、Diagnosis、Coding、Review 各自有明确输入输出。测试、Git、文件、Patch 是确定性 Tool。

## ADR-003：Coding Agent 只输出 Unified Diff

模型不直接写宿主机文件。Patch Validator 和 Patch Executor 在独立 Worktree 中应用 Diff。

## ADR-004：Baseline Test 是修复流程的一部分

Baseline 与 Post-patch Test 分开保存，用于区分原失败、新增回归和目标问题是否解决。

## ADR-005：Memory 只将验证结果作为高质量成功经验

`verified_success` 需要目标测试和回归测试都通过。失败经验可保存但不默认展示为成功。

## ADR-006：先实现原生 Tool Registry，再接 MCP

Tool Gateway 是内部安全边界。MCP、Web UI 和复杂协议不阻塞核心闭环。

## ADR-007：核心流程必须支持 Fake LLM

没有 API Key 时可以测试 Schema、Graph、Tool、Patch、Test 和 Reflection。Fake LLM 结果必须标记 `fake_llm`，不能作为真实模型能力。

## ADR-008：以实验验证机制贡献

Planning、Memory、Reflection 的价值通过 A-E 和消融实验评估。当前实验数据为 `not_verified`，没有性能宣称。

## ADR-009：路径和命令必须受控

Tool Input 使用 Pydantic，路径经过规范化、符号链接和 `..` 检查。命令使用参数数组和 `shell=False`。

## ADR-010：Docker 是隔离层，不是安全保证

容器默认禁网、非 root、只挂载 Worktree。Docker 不可用时不伪造容器结果。

## ADR-011：审批只开放 CLI

最终 Patch 导出需要人工 approve。没有 Web 审批、push、merge、部署接口。

## ADR-012：所有成本数据允许 unknown

Token、价格、真实延迟和模型能力不能由 mock 或基础设施运行推断。

## ADR-013：Benchmark 私有数据与 Agent 输入分离

`AgentTask` 不包含 Gold Patch、Verification Command、预期根因和隐藏测试。

## ADR-014：代码版本和实验配置必须随结果保存

每条 BenchmarkRecord 保存 model、prompt、budget、tool set、code version、Base Commit 和配置差异。
