"""Validated long-term experience memory contracts."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator, model_validator

from repopilot.core.schemas import RepoPilotModel

ExperienceOutcome = Literal["verified_success", "failed", "uncertain"]

_SECRET_PATTERN = re.compile(
    r"(?i)(api[_-]?key|access[_-]?token|refresh[_-]?token|password|secret|bearer\s+\S+|BEGIN [A-Z ]*PRIVATE KEY)"
)
_GOLD_PATTERN = re.compile(r"(?i)(gold[_ -]?patch|hidden[_ -]?test|expected[_ -]?answer)")


class Experience(RepoPilotModel):
    experience_id: str = Field(min_length=1, max_length=128)
    source_task_id: str | None = Field(default=None, min_length=1)
    issue_summary: str = Field(min_length=1)
    error_type: str | None = Field(default=None, min_length=1)
    repository_fingerprint: str | None = Field(default=None, min_length=1)
    affected_symbols: list[str] = Field(default_factory=list)
    root_cause: str = Field(min_length=1)
    solution_summary: str = Field(min_length=1)
    patch_summary: str = Field(min_length=1)
    validation_summary: str = Field(min_length=1)
    outcome: ExperienceOutcome
    target_tests_passed: bool = False
    regression_tests_passed: bool = False
    applicability_conditions: list[str] = Field(default_factory=list)
    embedding_text: str = Field(min_length=1)
    created_at: datetime

    @field_validator(
        "issue_summary",
        "root_cause",
        "solution_summary",
        "patch_summary",
        "validation_summary",
        "embedding_text",
    )
    @classmethod
    def reject_sensitive_or_leaked_content(cls, value: str) -> str:
        if _SECRET_PATTERN.search(value) or _GOLD_PATTERN.search(value):
            raise ValueError("experience content must not contain secrets or hidden evaluation data")
        if "diff --git" in value or value.lstrip().startswith(("--- a/", "+++ b/")):
            raise ValueError("experience must store patch summaries, not patch payloads")
        return value

    @model_validator(mode="after")
    def gate_verified_success(self) -> "Experience":
        if self.outcome == "verified_success" and not (
            self.target_tests_passed and self.regression_tests_passed
        ):
            raise ValueError(
                "verified_success requires target and regression tests to pass"
            )
        return self


class MemoryRetrievalRecord(RepoPilotModel):
    retrieval_id: int | None = None
    memory_id: str = Field(min_length=1)
    source_task_id: str | None = None
    query: str = Field(min_length=1)
    retrieval_score: float = Field(ge=0, le=1)
    planner_adopted: bool = False
    retrieved_at: datetime


class MemorySearchResult(RepoPilotModel):
    memory_id: str
    score: float = Field(ge=0, le=1)
    outcome: ExperienceOutcome
    issue_summary: str
    root_cause: str
    solution_summary: str
    applicability_conditions: list[str] = Field(default_factory=list)
