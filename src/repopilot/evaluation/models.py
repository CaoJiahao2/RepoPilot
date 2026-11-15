"""Benchmark raw records, execution contracts, and summary models."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from repopilot.core.schemas import RepoPilotModel

ExecutionMode = Literal["real", "mock", "infrastructure", "skipped"]


class BenchmarkExecutionResult(RepoPilotModel):
    status: Literal["succeeded", "failed", "skipped"] = "failed"
    success: bool = False
    patch_passed: bool = False
    regression_detected: bool = False
    root_cause_correct: bool | None = None
    root_cause: str | None = None
    patch_diff: str = ""
    logs: str = ""
    failure_stage: str | None = None
    failure_type: str | None = None
    tool_calls: int = Field(default=0, ge=0)
    tool_successes: int = Field(default=0, ge=0)
    replans: int = Field(default=0, ge=0)
    reflection_attempts: int = Field(default=0, ge=0)
    reflection_recoveries: int = Field(default=0, ge=0)
    memory_retrievals: int = Field(default=0, ge=0)
    memory_hits: int = Field(default=0, ge=0)
    duration_seconds: float = Field(default=0, ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    llm_calls: int = Field(default=0, ge=0)
    estimated_cost_usd: float | None = Field(default=None, ge=0)
    execution_mode: ExecutionMode = "real"


class BenchmarkRecord(RepoPilotModel):
    task_id: str
    dataset: str
    experiment_group: str
    run_index: int = Field(ge=0)
    model_id: str
    prompt_version: str
    code_version: str
    config: dict[str, Any]
    budget: dict[str, int | float]
    started_at: datetime
    finished_at: datetime
    base_commit: str
    workspace_path: str
    result: BenchmarkExecutionResult
    agent_input_task_id: str
    gold_patch_available_to_agent: bool = False
    verification_command_available_to_agent: bool = False


class MetricSummary(RepoPilotModel):
    resolution_rate: float | None = Field(default=None, ge=0, le=1)
    patch_pass_rate: float | None = Field(default=None, ge=0, le=1)
    regression_rate: float | None = Field(default=None, ge=0, le=1)
    root_cause_accuracy: float | None = Field(default=None, ge=0, le=1)
    tool_success_rate: float | None = Field(default=None, ge=0, le=1)
    replanning_rate: float | None = Field(default=None, ge=0, le=1)
    reflection_recovery_rate: float | None = Field(default=None, ge=0, le=1)
    memory_retrieval_hit_rate: float | None = Field(default=None, ge=0, le=1)
    latency_p50_seconds: float | None = Field(default=None, ge=0)
    latency_p95_seconds: float | None = Field(default=None, ge=0)
    total_input_tokens: int | None = None
    total_output_tokens: int | None = None
    total_llm_calls: int = Field(default=0, ge=0)
    total_estimated_cost_usd: float | None = Field(default=None, ge=0)
    unknown_token_or_cost_tasks: int = Field(default=0, ge=0)


class BenchmarkSummary(RepoPilotModel):
    dataset: str
    experiment_group: str
    task_count: int = Field(ge=0)
    run_count: int = Field(ge=0)
    success_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
    skipped_count: int = Field(ge=0)
    metrics: MetricSummary
