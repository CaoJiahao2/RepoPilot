from typing import TypedDict

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from repopilot.core.errors import CheckpointError
from repopilot.memory.short_term import CheckpointedGraphRunner


class State(TypedDict):
    writes: int
    execution_trace: list[str]


def _graph():
    def prepare(state: State) -> State:
        return {
            "writes": state["writes"],
            "execution_trace": state.get("execution_trace", []) + ["prepare"],
        }

    def persist(state: State) -> State:
        return {
            "writes": state["writes"] + 1,
            "execution_trace": state.get("execution_trace", []) + ["persist"],
        }

    def finish(state: State) -> State:
        return {
            "writes": state["writes"],
            "execution_trace": state.get("execution_trace", []) + ["finish"],
        }

    builder = StateGraph(State)
    builder.add_node("prepare", prepare)
    builder.add_node("persist", persist)
    builder.add_node("finish", finish)
    builder.add_edge(START, "prepare")
    builder.add_edge("prepare", "persist")
    builder.add_edge("persist", "finish")
    builder.add_edge("finish", END)
    return builder.compile(checkpointer=InMemorySaver())


def test_checkpoint_interrupt_resume_and_non_idempotent_node_runs_once() -> None:
    runner = CheckpointedGraphRunner(_graph())

    started = runner.start(
        {"writes": 0, "execution_trace": []},
        thread_id="task-001",
        interrupt_before=["persist"],
    )
    assert started.snapshot.next_nodes == ("persist",)
    assert started.snapshot.values["writes"] == 0
    assert started.snapshot.values["execution_trace"] == ["prepare"]

    resumed = runner.resume("task-001")
    assert resumed.snapshot.next_nodes == ()
    assert resumed.snapshot.values["writes"] == 1
    assert resumed.snapshot.values["execution_trace"] == ["prepare", "persist", "finish"]

    with pytest.raises(CheckpointError, match="already complete"):
        runner.resume("task-001")


def test_checkpoint_threads_are_isolated() -> None:
    runner = CheckpointedGraphRunner(_graph())

    runner.start({"writes": 0, "execution_trace": []}, thread_id="task-a")
    runner.start({"writes": 0, "execution_trace": []}, thread_id="task-b", interrupt_before=["persist"])

    assert runner.snapshot("task-a").values["writes"] == 1
    assert runner.snapshot("task-b").values["writes"] == 0

    runner.resume("task-b")
    assert runner.snapshot("task-b").values["writes"] == 1
    assert runner.snapshot("task-a").values["execution_trace"] == ["prepare", "persist", "finish"]


def test_checkpoint_rejects_duplicate_thread_start() -> None:
    runner = CheckpointedGraphRunner(_graph())
    runner.start({"writes": 0, "execution_trace": []}, thread_id="task-001")

    with pytest.raises(CheckpointError, match="already has checkpointed state"):
        runner.start({"writes": 0, "execution_trace": []}, thread_id="task-001")
