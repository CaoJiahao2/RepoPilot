# 简历项目描述草稿

## 项目名称

RepoPilot：面向 Python 仓库的自适应多 Agent 故障诊断与自动修复系统

## 项目描述

设计并实现一个基于 LangGraph 的有状态软件修复流水线，串联 Planner、Code Research、Diagnosis、Coding、Review 和 Reflection。系统通过统一 Tool Gateway 执行只读检索、Git 查询、补丁应用和真实 pytest 测试，在独立 Git Worktree 中生成 Unified Diff，并通过 Baseline/Post-patch Test 区分原失败和新增回归。

补充实现了 AST/BM25/可选 Embedding Code RAG、SQLite Experience Memory、Checkpoint 恢复、执行感知 Reflection、Docker Sandbox 命令边界、CLI 审批、FastAPI 异步任务 API、Benchmark Runner、实验配对比较和 Bootstrap 指标框架。

## 工程亮点

- 用 Pydantic Schema 约束 LLM 输出、TaskPlan DAG 和 Tool Input。
- 用 `shell=False` 参数数组和路径规范化阻止 Shell 注入、路径穿越和符号链接逃逸。
- 用 Worktree + Patch Executor 保证 Coding Agent 不直接修改原始仓库。
- 用真实 TestReport 约束 Review 和 Reflection，不允许模型自行声明成功。
- 用 `verified_success` 门控 Experience Memory，避免污染跨任务经验。
- 用 Fake LLM 保证无 API Key 时仍可测试完整业务逻辑，并显式标注 `fake_llm` provenance。

## 可引用的工程事实

- Python 3.11+、Pydantic v2、LangGraph、FastAPI、SQLite、pathspec。
- 10 个可复现 Python Bug Fixture。
- 129 个通过测试，1 个真实 LLM 测试因环境未配置跳过。
- Benchmark 原始 JSONL/CSV、实验组、消融、Bootstrap 和失败分析框架已实现。

## 实际验证数据

在 10 个本地 Mini-Benchmark Bug 上完成 30 次 Full Pipeline 真实验证：

- 28/30 运行成功，Resolution Rate 93.33%。
- Bootstrap 95% CI：83.33% - 100.00%。
- 117 次 LLM 调用。
- 82,825 Input Tokens、76,446 Output Tokens。
- P50 延迟 28.806 秒，P95 延迟 40.094 秒。

该数据来自单次 Full Pipeline 多任务验证，不是 A-E 对比实验，不能外推为总体泛化能力或统计显著性。
