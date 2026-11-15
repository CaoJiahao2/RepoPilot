# RepoPilot 3-5 分钟 Demo 脚本

## 0. 开场（20 秒）

说明：RepoPilot 将 Bug、代码证据、结构化计划、补丁、测试、反思和审批放到同一条可追踪链路中。今天演示使用 `task-001` 和显式 Fake LLM；真实测试、Worktree、Patch 和 pytest 都是实际执行。

## 1. 输入 Bug（30 秒）

```bash
cat benchmarks/tasks/task-001/task.json
```

展示：

- Bug：`parse_config({})` 返回 `None`，预期 `{}`。
- Base Commit。
- 目标测试。
- Agent 可见输入不包含 Gold Patch 或 Verification Command。

## 2. 启动 Demo（60 秒）

```bash
uv run repopilot demo
```

依次展示：

- `validate_task`
- `prepare_workspace`
- Planner 的结构化 `TaskPlan`
- Research 的 Code RAG Evidence
- Diagnosis 的 Evidence ID 和根因
- `baseline_test` 的 pytest 结果

## 3. 补丁和真实测试（60 秒）

展示最终报告中的：

- `unified_diff`
- `modified_files`
- `git_diff_before`
- `git_diff_after`
- `baseline_test_report.status == assertion_failed`
- `post_patch_test_report.status == passed`

强调 Diff 只在独立 Worktree 中应用，原始 Fixture 仓库不改变。

## 4. Review、Trace 和 provenance（40 秒）

展示：

- `review_result`
- `execution_trace`
- `execution_mode == fake_llm`
- `cost` 中 Fake LLM 的调用数和 unknown Token/Cost

说明 Fake LLM 负责决策输出，但补丁和测试结果来自真实工具执行，因此不是静态 UI 假数据。

## 5. API/CLI 收尾（30 秒）

```bash
uv run repopilot --help
uv run repopilot benchmark run --dataset benchmarks/tasks --output benchmark-results --executor skipped
```

说明 API 只提供任务生命周期、Trace、Artifacts、审批和取消，不提供任意 Shell 接口。

## 6. 结束（20 秒）

总结：

- 可解释结构化状态。
- 真实测试约束模型声明。
- 独立 Worktree 和审批边界。
- 真实 LLM、Docker 和性能数据需要外部环境验证。
