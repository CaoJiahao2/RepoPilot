# RepoPilot 面试追问与回答要点

1. **为什么不直接让 LLM 修改文件？**
   - `PatchResult` 只包含 Unified Diff；`PatchValidator` 和 `PatchExecutor` 负责在 Worktree 中应用，便于审计、回滚和权限控制。

2. **如何避免路径穿越和符号链接逃逸？**
   - `ToolContext.resolve_path` 拒绝绝对路径和 `..`，逐段检查符号链接，并确认 `resolve()` 结果仍在允许根目录内。

3. **如何证明测试真的通过？**
   - `CommandTestRunner` 使用 allowlist argv 和 `shell=False`，保存退出码、stdout、stderr、耗时；Review 不能绕过 `TestReport.status == passed`。

4. **State 中为什么区分覆盖和 Reducer？**
   - Plan/Diagnosis/Patch 是当前轮结果，覆盖旧值；Evidence、Memory、Trace、ToolResult 是审计和检索记录，使用追加。

5. **Fake LLM 为什么可信？**
   - 它只模拟结构化决策输出，真实 Worktree、Patch、pytest 和 Trace 仍执行；报告标 `execution_mode="fake_llm"`，不冒充真实模型。

6. **Memory 如何避免错误经验污染？**
   - `verified_success` 要求目标和回归测试都通过；失败/不确定经验分开保存；默认检索不把它们当成功经验。

7. **Adaptive Planning 如何受限？**
   - Action 是有限 Literal；TaskPlan 校验 step_id、依赖和 DAG 无环；预算、失败反馈和 invalid plan 次数优先于模型建议。

8. **Reflection 与普通重试有什么不同？**
   - Classifier 根据真实 TestReport、ToolResult、Diff、Trace 分类失败，输出结构化 `RecoveryStrategy` 和剩余预算，不只生成自然语言解释。

9. **Benchmark 如何避免 Gold Patch 泄漏？**
   - `AgentTask` 只读 `task.json`；Gold Patch、Verification Command、预期根因在 `private/evaluation.json`，Runner 不把它们传给执行器。

10. **当前项目最大的未验证风险是什么？**
    - 真实 LLM、Docker Daemon、真实 Benchmark 和成本尚未验证；`docs/experiments.md` 明确标记 `not_verified`，不使用 mock 结果宣称性能。
