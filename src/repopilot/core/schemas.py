"""Core validated data contracts for RepoPilot."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

FailureType = Literal[
    "patch_error",
    "regression",
    "wrong_root_cause",
    "missing_context",
    "test_env_error",
    "tool_failure",
    "budget_exceeded",
]

Action = Literal[
    "search",
    "inspect",
    "diagnose",
    "patch",
    "test",
    "review",
    "replan",
    "finish",
]

SourceType = Literal[
    "stack_trace",
    "source_code",
    "test",
    "git_history",
    "issue",
    "memory",
]

ReviewNextAction = Literal[
    "finish",
    "re_search",
    "re_diagnose",
    "re_patch",
    "fix_environment",
    "human_review",
]

TraceEventType = Literal[
    "task",
    "agent",
    "tool",
    "test",
    "review",
    "budget",
    "error",
]

TraceStatus = Literal["started", "succeeded", "failed", "skipped"]

ScalarValue = str | int | float | bool | None


class RepoPilotModel(BaseModel):
    """Base model for strict, non-extensible boundary objects."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True,
    )


class TaskRequest(RepoPilotModel):
    task_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    repo_path: str = Field(min_length=1)
    issue: str = Field(min_length=5)
    stack_trace: str | None = Field(default=None, min_length=1)
    test_command: list[str] | None = None
    allowed_paths: list[str] = Field(default_factory=list)
    forbidden_paths: list[str] = Field(default_factory=list)
    max_runtime_seconds: int = Field(default=900, ge=1, le=86_400)
    max_llm_calls: int = Field(default=30, ge=1, le=1_000)
    max_total_tokens: int = Field(default=100_000, ge=1)
    max_patch_retries: int = Field(default=3, ge=0, le=10)
    max_tool_calls: int = Field(default=100, ge=1, le=10_000)
    require_approval: bool = True

    @field_validator("test_command")
    @classmethod
    def validate_test_command(cls, value: list[str] | None) -> list[str] | None:
        if value is not None and (not value or any(not item for item in value)):
            raise ValueError("test_command must contain non-empty argument strings")
        return value

    @field_validator("allowed_paths", "forbidden_paths")
    @classmethod
    def validate_path_lists(cls, value: list[str]) -> list[str]:
        if any(not item for item in value):
            raise ValueError("path lists must not contain empty values")
        if len(value) != len(set(value)):
            raise ValueError("path lists must not contain duplicates")
        return value

    @model_validator(mode="after")
    def validate_path_policy(self) -> "TaskRequest":
        overlap = set(self.allowed_paths) & set(self.forbidden_paths)
        if overlap:
            raise ValueError(f"path cannot be both allowed and forbidden: {sorted(overlap)}")
        return self


class PlannedStep(RepoPilotModel):
    step_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    action: Action
    description: str = Field(min_length=1)
    depends_on: list[str] = Field(default_factory=list)
    expected_output: str = Field(min_length=1)

    @field_validator("depends_on")
    @classmethod
    def validate_depends_on(cls, value: list[str]) -> list[str]:
        if any(not item for item in value):
            raise ValueError("depends_on must not contain empty step IDs")
        if len(value) != len(set(value)):
            raise ValueError("depends_on must not contain duplicates")
        return value


class TaskPlan(RepoPilotModel):
    objective: str = Field(min_length=1)
    steps: list[PlannedStep] = Field(min_length=1, max_length=8)
    next_action: Action
    rationale: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_plan_graph(self) -> "TaskPlan":
        step_ids = [step.step_id for step in self.steps]
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("step_id values must be unique")

        known_ids = set(step_ids)
        for step in self.steps:
            missing = set(step.depends_on) - known_ids
            if missing:
                raise ValueError(
                    f"step {step.step_id!r} depends on unknown steps: {sorted(missing)}"
                )
            if step.step_id in step.depends_on:
                raise ValueError(f"step {step.step_id!r} cannot depend on itself")

        dependencies = {step.step_id: step.depends_on for step in self.steps}
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(step_id: str) -> None:
            if step_id in visiting:
                raise ValueError(f"plan dependencies contain a cycle at {step_id!r}")
            if step_id in visited:
                return
            visiting.add(step_id)
            for dependency in dependencies[step_id]:
                visit(dependency)
            visiting.remove(step_id)
            visited.add(step_id)

        for step_id in step_ids:
            visit(step_id)
        if self.next_action != "finish" and self.next_action not in {
            step.action for step in self.steps
        }:
            raise ValueError("next_action must be finish or match a planned step action")
        return self


class Evidence(RepoPilotModel):
    evidence_id: str = Field(min_length=1, max_length=128)
    source_type: SourceType
    file_path: str | None = Field(default=None, min_length=1)
    line_start: int | None = Field(default=None, ge=1)
    line_end: int | None = Field(default=None, ge=1)
    symbol: str | None = Field(default=None, min_length=1)
    content: str = Field(min_length=1)
    retrieval_score: float | None = Field(default=None, ge=0, le=1)
    retrieval_sources: list[str] = Field(default_factory=list)
    repository_commit: str | None = None

    @model_validator(mode="after")
    def validate_location(self) -> "Evidence":
        if (self.line_start is None) != (self.line_end is None):
            raise ValueError("line_start and line_end must be provided together")
        if self.line_start is not None and self.line_end is not None:
            if self.line_end < self.line_start:
                raise ValueError("line_end must be greater than or equal to line_start")
            if self.file_path is None:
                raise ValueError("file_path is required when line numbers are provided")
        return self


class Diagnosis(RepoPilotModel):
    root_cause: str = Field(min_length=1)
    affected_files: list[str] = Field(default_factory=list)
    related_symbols: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    alternative_hypotheses: list[str] = Field(default_factory=list)
    suggested_fix: str = Field(min_length=1)
    missing_information: list[str] = Field(default_factory=list)

    @field_validator("evidence_ids", "affected_files", "related_symbols")
    @classmethod
    def validate_unique_non_empty(cls, value: list[str]) -> list[str]:
        if any(not item for item in value):
            raise ValueError("list values must not be empty strings")
        if len(value) != len(set(value)):
            raise ValueError("list values must be unique")
        return value


class PatchResult(RepoPilotModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=False,
        validate_assignment=True,
    )

    unified_diff: str = Field(min_length=1)
    modified_files: list[str] = Field(min_length=1)
    explanation: str = Field(min_length=1)
    risks: list[str] = Field(default_factory=list)

    @field_validator("modified_files")
    @classmethod
    def validate_modified_files(cls, value: list[str]) -> list[str]:
        if any(not item for item in value):
            raise ValueError("modified_files must not contain empty paths")
        if len(value) != len(set(value)):
            raise ValueError("modified_files must be unique")
        return value


class TestReport(RepoPilotModel):
    command: list[str] = Field(min_length=1)
    status: Literal[
        "passed",
        "assertion_failed",
        "collection_error",
        "dependency_error",
        "timeout",
        "execution_error",
        "skipped",
    ]
    return_code: int
    duration_seconds: float = Field(ge=0)
    tests_total: int = Field(default=0, ge=0)
    tests_passed: int = Field(default=0, ge=0)
    tests_failed: int = Field(default=0, ge=0)
    tests_skipped: int = Field(default=0, ge=0)
    tests_errors: int = Field(default=0, ge=0)
    stdout: str = ""
    stderr: str = ""
    failure_type: FailureType | None = None

    @field_validator("command")
    @classmethod
    def validate_command(cls, value: list[str]) -> list[str]:
        if any(not item for item in value):
            raise ValueError("command must contain non-empty arguments")
        return value

    @model_validator(mode="after")
    def validate_counts_and_status(self) -> "TestReport":
        counted = (
            self.tests_passed
            + self.tests_failed
            + self.tests_skipped
            + self.tests_errors
        )
        if counted != self.tests_total:
            raise ValueError("test outcome counts must sum to tests_total")
        if self.status == "passed" and (
            self.return_code != 0 or self.tests_failed or self.tests_errors
        ):
            raise ValueError("passed reports require return_code=0 and no failures/errors")
        if self.return_code == 0 and self.status not in {"passed", "skipped"}:
            raise ValueError("non-passed reports require a non-zero return_code")
        return self


class ReviewResult(RepoPilotModel):
    approved: bool
    failure_type: FailureType | None = None
    evidence: list[str] = Field(default_factory=list)
    feedback: str = Field(min_length=1)
    next_action: ReviewNextAction

    @model_validator(mode="after")
    def validate_review_outcome(self) -> "ReviewResult":
        if self.approved and self.failure_type is not None:
            raise ValueError("approved reviews must not set failure_type")
        if not self.approved and self.failure_type is None:
            raise ValueError("rejected reviews must set failure_type")
        if not self.approved and self.next_action == "finish":
            raise ValueError("rejected reviews cannot use next_action='finish'")
        return self


class ToolResult(RepoPilotModel):
    tool_name: str = Field(min_length=1)
    success: bool
    output: str = ""
    error_code: str | None = Field(default=None, min_length=1)
    error_message: str | None = Field(default=None, min_length=1)
    duration_ms: int = Field(ge=0)
    artifacts: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_tool_outcome(self) -> "ToolResult":
        if self.success and (self.error_code is not None or self.error_message is not None):
            raise ValueError("successful tool results must not include errors")
        if not self.success and (self.error_code is None or self.error_message is None):
            raise ValueError("failed tool results require error_code and error_message")
        return self


class BudgetState(RepoPilotModel):
    max_llm_calls: int = Field(default=30, ge=1)
    max_total_tokens: int = Field(default=100_000, ge=1)
    max_runtime_seconds: int = Field(default=900, ge=1)
    max_patch_retries: int = Field(default=3, ge=0)
    max_replans: int = Field(default=2, ge=0)
    max_tool_retries: int = Field(default=2, ge=0)
    max_tool_calls: int = Field(default=100, ge=1)
    llm_calls_used: int = Field(default=0, ge=0)
    total_tokens_used: int = Field(default=0, ge=0)
    tool_calls_used: int = Field(default=0, ge=0)
    runtime_seconds_used: float = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_budget_usage(self) -> "BudgetState":
        limits = (
            ("llm_calls_used", "max_llm_calls"),
            ("total_tokens_used", "max_total_tokens"),
            ("tool_calls_used", "max_tool_calls"),
            ("runtime_seconds_used", "max_runtime_seconds"),
        )
        for used_name, max_name in limits:
            if getattr(self, used_name) > getattr(self, max_name):
                raise ValueError(f"{used_name} cannot exceed {max_name}")
        return self


class RetryCounters(RepoPilotModel):
    patch_retries: int = Field(default=0, ge=0)
    replans: int = Field(default=0, ge=0)
    tool_retries: int = Field(default=0, ge=0)


class TraceEvent(RepoPilotModel):
    event_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    timestamp: datetime
    event_type: TraceEventType
    actor: str = Field(min_length=1)
    action: str = Field(min_length=1)
    status: TraceStatus
    duration_ms: int | None = Field(default=None, ge=0)
    message: str = ""
    details: dict[str, ScalarValue] = Field(default_factory=dict)

    @field_validator("timestamp")
    @classmethod
    def validate_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must include a timezone")
        return value


TaskStatus = Literal[
    "created",
    "running",
    "waiting_approval",
    "succeeded",
    "failed",
    "cancelled",
    "budget_exceeded",
]


class MemoryHit(RepoPilotModel):
    experience_id: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    source: str = Field(default="experience_memory", min_length=1)
    retrieval_score: float = Field(ge=0, le=1)
    verified: bool = False


class ResearchResult(RepoPilotModel):
    evidence: list[Evidence] = Field(min_length=1)

    @field_validator("evidence")
    @classmethod
    def validate_unique_evidence(cls, value: list[Evidence]) -> list[Evidence]:
        ids = [item.evidence_id for item in value]
        if len(ids) != len(set(ids)):
            raise ValueError("evidence_id values must be unique")
        return value


class FinalReport(RepoPilotModel):
    task_id: str = Field(min_length=1)
    status: TaskStatus
    summary: str = Field(min_length=1)
    review_approved: bool
    test_status: Literal[
        "passed",
        "assertion_failed",
        "collection_error",
        "dependency_error",
        "timeout",
        "execution_error",
        "skipped",
    ] | None = None
    modified_files: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    failure_type: FailureType | None = None
    trace_count: int = Field(ge=0)


class TaskValidationResult(RepoPilotModel):
    task_id: str = Field(min_length=1)
    valid: bool
    errors: list[str] = Field(default_factory=list)


class WorkspaceRecord(RepoPilotModel):
    source_repo: str = Field(min_length=1)
    worktree_path: str = Field(min_length=1)
    base_commit: str = Field(min_length=1)
    initial_status: str = ""


class RunCost(RepoPilotModel):
    llm_calls: int = Field(default=0, ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    estimated_cost_usd: float | None = Field(default=None, ge=0)
    cost_status: Literal["actual", "fake", "unavailable"] = "unavailable"


class EndToEndReport(RepoPilotModel):
    task_id: str = Field(min_length=1)
    status: TaskStatus
    summary: str = Field(min_length=1)
    plan: TaskPlan | None = None
    root_cause: str | None = None
    evidence: list[Evidence] = Field(default_factory=list)
    modified_files: list[str] = Field(default_factory=list)
    unified_diff: str | None = None
    baseline_test_report: TestReport | None = None
    post_patch_test_report: TestReport | None = None
    review_result: ReviewResult | None = None
    reflection_result: Any | None = None
    failure_node: str | None = None
    failure_reason: str | None = None
    base_commit: str | None = None
    initial_git_status: str = ""
    git_diff_before: str = ""
    git_diff_after: str = ""
    cost: RunCost | None = None
    execution_mode: Literal["real", "fake_llm", "unavailable", "mock"] = "real"
    execution_trace: list[TraceEvent] = Field(default_factory=list)
