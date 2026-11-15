"""Reflection recovery metrics."""

from __future__ import annotations

from collections.abc import Iterable

from pydantic import Field

from repopilot.core.schemas import RepoPilotModel
from repopilot.reflection.models import ReflectionRecord


class ReflectionMetrics(RepoPilotModel):
    total_records: int = Field(ge=0)
    actionable_records: int = Field(ge=0)
    recovered_records: int = Field(ge=0)
    recovery_rate: float = Field(ge=0, le=1)


def calculate_recovery_rate(records: Iterable[ReflectionRecord]) -> ReflectionMetrics:
    records = list(records)
    actionable = [
        record
        for record in records
        if record.recovery_outcome in {"recovered", "failed"}
    ]
    recovered = [record for record in actionable if record.recovery_outcome == "recovered"]
    rate = len(recovered) / len(actionable) if actionable else 0.0
    return ReflectionMetrics(
        total_records=len(records),
        actionable_records=len(actionable),
        recovered_records=len(recovered),
        recovery_rate=rate,
    )
