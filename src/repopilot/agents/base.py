"""Agent contract and a deterministic fake agent implementation."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Generic, Protocol, TypeVar

from pydantic import BaseModel

from repopilot.core.state import RepoPilotState
from repopilot.llm import LLMClient, parse_structured_output
from repopilot.core.errors import SchemaValidationError

OutputT = TypeVar("OutputT", bound=BaseModel)


class Agent(Protocol):
    name: str
    output_model: type[BaseModel]

    def run(self, state: RepoPilotState) -> BaseModel:
        """Produce one validated output from the current graph state."""


class BaseAgent(Generic[OutputT], ABC):
    def __init__(
        self,
        *,
        name: str,
        output_model: type[OutputT],
        llm: LLMClient,
        max_validation_retries: int = 1,
    ) -> None:
        if max_validation_retries < 0:
            raise ValueError("max_validation_retries must be non-negative")
        self.name = name
        self.output_model = output_model
        self.llm = llm
        self.max_validation_retries = max_validation_retries

    @abstractmethod
    def build_prompt(self, state: RepoPilotState) -> str:
        """Build a deterministic prompt from validated state."""

    def run(self, state: RepoPilotState) -> OutputT:
        last_error: SchemaValidationError | None = None
        for attempt in range(self.max_validation_retries + 1):
            prompt = self.build_prompt(state)
            if last_error is not None:
                messages = [
                    item.get("message", "")
                    for item in last_error.details.get("errors", [])
                    if isinstance(item, dict) and item.get("message")
                ]
                prompt += (
                    "\nPrevious output failed schema validation"
                    + (f": {'; '.join(messages)}" if messages else "")
                    + ". Return a corrected JSON object only."
                )
            raw_output = self.llm.complete(
                prompt=prompt,
                output_name=self.output_model.__name__,
            )
            try:
                return parse_structured_output(raw_output, self.output_model)
            except SchemaValidationError as exc:
                last_error = exc
        assert last_error is not None
        raise last_error


class FakeAgent(BaseAgent[OutputT]):
    """Small deterministic agent used to exercise the runtime without API keys."""

    def build_prompt(self, state: RepoPilotState) -> str:
        task = state.get("task")
        task_id = getattr(task, "task_id", "unknown-task")
        issue = getattr(task, "issue", "")
        stack_trace = getattr(task, "stack_trace", None)
        evidence = list(state.get("evidence", []))
        evidence_ids = [getattr(item, "evidence_id", None) for item in evidence]
        evidence_refs = [
            {
                "evidence_id": getattr(item, "evidence_id", None),
                "file_path": getattr(item, "file_path", None),
                "line_start": getattr(item, "line_start", None),
                "line_end": getattr(item, "line_end", None),
                "symbol": getattr(item, "symbol", None),
                "content": getattr(item, "content", None),
            }
            for item in evidence
        ]
        return json.dumps(
            {
                "task_id": task_id,
                "issue": issue,
                "stack_trace": stack_trace,
                "available_evidence_ids": evidence_ids,
                "available_evidence": evidence_refs,
                "current_diagnosis": getattr(state.get("diagnosis"), "root_cause", None),
                "current_patch": getattr(state.get("patch_result"), "unified_diff", None),
                "baseline_test_status": getattr(state.get("baseline_test_report"), "status", None),
                "post_patch_test_status": getattr(state.get("test_report"), "status", None),
                "output_contract": self.output_model.__name__,
                "output_schema": self.output_model.model_json_schema(),
                "instruction": "Return only valid JSON matching output_schema. Do not include markdown fences. Diagnosis and Review must cite only available_evidence_ids exactly. Review must consider current_diagnosis, current_patch, baseline_test_status, and post_patch_test_status before approving. PatchResult.unified_diff must be a directly applicable unified diff with --- a/path, +++ b/path, and @@ hunk headers; use the available evidence content as source context and do not invent unrelated lines.",
            },
            ensure_ascii=False,
            sort_keys=True,
        )
