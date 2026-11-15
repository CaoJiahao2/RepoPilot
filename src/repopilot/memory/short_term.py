"""Checkpointed LangGraph execution with explicit thread isolation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from repopilot.core.errors import CheckpointError


@dataclass(frozen=True)
class CheckpointSnapshot:
    thread_id: str
    values: dict[str, Any]
    next_nodes: tuple[str, ...]
    checkpoint_id: str | None
    created_at: str | None
    trace: list[Any]


@dataclass(frozen=True)
class CheckpointRunRecord:
    action: str
    snapshot: CheckpointSnapshot


class CheckpointedGraphRunner:
    def __init__(self, graph: Any) -> None:
        self.graph = graph

    def start(
        self,
        input_state: Mapping[str, Any],
        *,
        thread_id: str,
        interrupt_before: list[str] | None = None,
        interrupt_after: list[str] | None = None,
    ) -> CheckpointRunRecord:
        self._validate_thread_id(thread_id)
        config = self._config(thread_id)
        existing = self.graph.get_state(config)
        if existing and existing.values:
            raise CheckpointError(
                "thread_id already has checkpointed state",
                details={"thread_id": thread_id},
            )
        values = self.graph.invoke(
            dict(input_state),
            config,
            interrupt_before=interrupt_before,
            interrupt_after=interrupt_after,
        )
        return CheckpointRunRecord(action="started", snapshot=self.snapshot(thread_id, values))

    def resume(
        self,
        thread_id: str,
        *,
        state_update: Mapping[str, Any] | None = None,
        as_node: str | None = None,
    ) -> CheckpointRunRecord:
        self._validate_thread_id(thread_id)
        config = self._config(thread_id)
        current = self.graph.get_state(config)
        if not current or not current.values:
            raise CheckpointError("thread_id has no checkpoint", details={"thread_id": thread_id})
        if not current.next:
            raise CheckpointError(
                "thread_id is already complete",
                details={"thread_id": thread_id},
            )
        if state_update:
            self.graph.update_state(config, dict(state_update), as_node=as_node)
        values = self.graph.invoke(None, config)
        return CheckpointRunRecord(action="resumed", snapshot=self.snapshot(thread_id, values))

    def snapshot(self, thread_id: str, values: Mapping[str, Any] | None = None) -> CheckpointSnapshot:
        config = self._config(thread_id)
        state = self.graph.get_state(config)
        resolved = dict(values if values is not None else (state.values or {}))
        checkpoint_config = getattr(state, "config", {}) or {}
        configurable = checkpoint_config.get("configurable", {})
        return CheckpointSnapshot(
            thread_id=thread_id,
            values=resolved,
            next_nodes=tuple(state.next or ()),
            checkpoint_id=configurable.get("checkpoint_id"),
            created_at=getattr(state, "created_at", None),
            trace=list(resolved.get("execution_trace", [])),
        )

    @staticmethod
    def _config(thread_id: str) -> dict[str, Any]:
        return {"configurable": {"thread_id": thread_id}}

    @staticmethod
    def _validate_thread_id(thread_id: str) -> None:
        if not thread_id or not thread_id.strip():
            raise CheckpointError("thread_id must be non-empty")
