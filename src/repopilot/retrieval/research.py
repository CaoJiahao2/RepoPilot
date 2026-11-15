"""Research Agent backed by Code RAG evidence retrieval."""

from __future__ import annotations

from typing import Any

from repopilot.core.errors import ToolExecutionError
from repopilot.core.schemas import ResearchResult, TaskRequest
from repopilot.retrieval.retriever import CodeRAGRetriever


class CodeRAGResearchAgent:
    name = "research"
    output_model = ResearchResult

    def __init__(self, retriever: CodeRAGRetriever, *, limit: int = 3) -> None:
        self.retriever = retriever
        self.limit = limit

    def run(self, state: dict[str, Any]) -> ResearchResult:
        task: TaskRequest = state["task"]
        query = f"{task.issue} {task.stack_trace or ''}".strip()
        hits = self.retriever.search(
            query,
            stack_trace=task.stack_trace,
            limit=self.limit,
        )
        evidence = self.retriever.to_evidence(hits)
        if not evidence:
            raise ToolExecutionError(
                "Code RAG found no evidence",
                details={"error_code": "no_evidence"},
            )
        return ResearchResult(evidence=evidence)
