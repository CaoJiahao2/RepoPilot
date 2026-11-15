"""Deterministic task-complexity feature extraction."""

from __future__ import annotations

import re
from typing import Any, Mapping

from repopilot.core.schemas import BudgetState
from repopilot.planning.models import ComplexityFeatures, PlanningInputSummary

_STACK_FILE_LINE = re.compile(r"File [\"'](?P<path>[^\"']+)[\"'], line (?P<line>\d+)")
_STACK_COLON_LINE = re.compile(r"(?P<path>[^\s:]+\.py):(?P<line>\d+)")


def _stack_refs(stack_trace: str | None) -> list[tuple[str, int]]:
    if not stack_trace:
        return []
    refs: list[tuple[str, int]] = []
    for pattern in (_STACK_FILE_LINE, _STACK_COLON_LINE):
        for match in pattern.finditer(stack_trace):
            refs.append((match.group("path"), int(match.group("line"))))
    return refs


def extract_complexity_features(
    state: Mapping[str, Any],
    *,
    invalid_plan_count: int = 0,
) -> ComplexityFeatures:
    task = state["task"]
    evidence = list(state.get("evidence", []))
    memory_hits = list(state.get("memory_hits", []))
    tool_results = list(state.get("tool_results", []))
    refs = _stack_refs(task.stack_trace)
    stack_files = {path for path, _ in refs}
    evidence_files = {item.file_path for item in evidence if item.file_path}
    evidence_symbols = {item.symbol for item in evidence if item.symbol}

    matched_refs = 0
    for path, line_number in refs:
        for item in evidence:
            if not item.file_path or item.line_start is None or item.line_end is None:
                continue
            path_matches = item.file_path == path or item.file_path.endswith(f"/{path}")
            if path_matches and item.line_start <= line_number <= item.line_end:
                matched_refs += 1
                break
    localization_score = matched_refs / len(refs) if refs else (1.0 if evidence else 0.0)
    file_coverage = len(evidence_files & stack_files) / len(stack_files) if stack_files else (1.0 if evidence else 0.0)
    symbol_factor = min(1.0, len(evidence_symbols) / 2)
    completeness = min(1.0, 0.6 * localization_score + 0.25 * file_coverage + 0.15 * symbol_factor)

    budget = state.get("budget") or BudgetState()
    latest_test = state.get("test_report") or state.get("baseline_test_report")
    budget_exhausted = any(
        (
            budget.llm_calls_used >= budget.max_llm_calls,
            budget.total_tokens_used >= budget.max_total_tokens,
            budget.tool_calls_used >= budget.max_tool_calls,
            budget.runtime_seconds_used >= budget.max_runtime_seconds,
        )
    )
    return ComplexityFeatures(
        stack_trace_present=bool(task.stack_trace),
        stack_file_count=len(stack_files),
        stack_line_count=len(refs),
        stack_localization_score=localization_score,
        evidence_count=len(evidence),
        evidence_file_count=len(evidence_files),
        evidence_symbol_count=len(evidence_symbols),
        evidence_completeness=completeness,
        memory_hit_count=len(memory_hits),
        verified_memory_hit_count=sum(1 for hit in memory_hits if getattr(hit, "verified", False)),
        latest_test_status=latest_test.status if latest_test else None,
        tool_success_count=sum(1 for result in tool_results if result.success),
        tool_failure_count=sum(1 for result in tool_results if not result.success),
        invalid_plan_count=invalid_plan_count,
        budget_exhausted=budget_exhausted,
    )


def summarize_input(
    state: Mapping[str, Any],
    complexity: ComplexityFeatures,
) -> PlanningInputSummary:
    task = state["task"]
    evidence = list(state.get("evidence", []))
    memory_hits = list(state.get("memory_hits", []))
    tool_results = list(state.get("tool_results", []))
    budget = state.get("budget") or BudgetState()
    latest_test = state.get("test_report") or state.get("baseline_test_report")
    return PlanningInputSummary(
        task_id=task.task_id,
        issue_chars=len(task.issue),
        stack_trace_chars=len(task.stack_trace or ""),
        evidence_ids=[item.evidence_id for item in evidence],
        memory_ids=[hit.experience_id for hit in memory_hits],
        latest_test_status=latest_test.status if latest_test else None,
        tool_result_count=len(tool_results),
        complexity=complexity,
        budget=budget,
    )
