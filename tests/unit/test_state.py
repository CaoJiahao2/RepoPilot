from datetime import datetime, timezone

from langgraph.graph import END, START, StateGraph

from repopilot.core.schemas import (
    Diagnosis,
    PatchResult,
    TaskRequest,
    TraceEvent,
)
from repopilot.core.state import RepoPilotState


def test_overwrite_fields_replace_previous_round_and_trace_reducer_appends() -> None:
    task = TaskRequest(task_id="task-001", repo_path="./repo", issue="valid issue")
    timestamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    first_patch = PatchResult(
        unified_diff="diff --git a/a.py b/a.py\n",
        modified_files=["a.py"],
        explanation="first",
    )
    second_patch = PatchResult(
        unified_diff="diff --git a/a.py b/a.py\n",
        modified_files=["a.py"],
        explanation="second",
    )
    first_diagnosis = Diagnosis(
        root_cause="first cause",
        evidence_ids=["ev-001"],
        confidence=0.4,
        suggested_fix="first fix",
    )
    second_diagnosis = Diagnosis(
        root_cause="second cause",
        evidence_ids=["ev-002"],
        confidence=0.8,
        suggested_fix="second fix",
    )
    first_trace = TraceEvent(
        event_id="evt-001",
        task_id=task.task_id,
        timestamp=timestamp,
        event_type="agent",
        actor="coding",
        action="patch",
        status="succeeded",
    )
    second_trace = TraceEvent(
        event_id="evt-002",
        task_id=task.task_id,
        timestamp=timestamp,
        event_type="agent",
        actor="coding",
        action="patch",
        status="succeeded",
    )

    builder = StateGraph(RepoPilotState)
    builder.add_node(
        "first",
        lambda state: {
            "patch_result": first_patch,
            "diagnosis": first_diagnosis,
            "execution_trace": [first_trace],
        },
    )
    builder.add_node(
        "second",
        lambda state: {
            "patch_result": second_patch,
            "diagnosis": second_diagnosis,
            "execution_trace": [second_trace],
        },
    )
    builder.add_edge(START, "first")
    builder.add_edge("first", "second")
    builder.add_edge("second", END)
    result = builder.compile().invoke({"task": task})

    assert result["patch_result"] == second_patch
    assert result["diagnosis"] == second_diagnosis
    assert result["patch_result"] is not first_patch
    assert result["diagnosis"] is not first_diagnosis
    assert [event.event_id for event in result["execution_trace"]] == ["evt-001", "evt-002"]
