"""CLI-only patch approval with auditable decisions."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Protocol

from pydantic import Field

from repopilot.core.errors import ApprovalError
from repopilot.core.schemas import RepoPilotModel


class ApprovalRequest(RepoPilotModel):
    request_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    patch_summary: str = Field(min_length=1)
    unified_diff: str = Field(min_length=1)
    risk_level: str = Field(default="write", pattern="^(read|execute|write|admin)$")
    created_at: datetime


class ApprovalDecision(RepoPilotModel):
    request_id: str = Field(min_length=1)
    approved: bool
    actor: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    decided_at: datetime


class PatchExport(RepoPilotModel):
    request_id: str
    approved_by: str
    unified_diff: str


class ApprovalStore(Protocol):
    def record_request(self, request: ApprovalRequest) -> None: ...
    def record_decision(self, decision: ApprovalDecision) -> None: ...
    def get_request(self, request_id: str) -> ApprovalRequest | None: ...
    def get_decision(self, request_id: str) -> ApprovalDecision | None: ...


class SQLiteApprovalStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS approval_requests (
                    request_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS approval_decisions (
                    request_id TEXT PRIMARY KEY,
                    approved INTEGER NOT NULL,
                    actor TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    decided_at TEXT NOT NULL
                )
                """
            )

    def record_request(self, request: ApprovalRequest) -> None:
        try:
            with self._connect() as connection:
                connection.execute(
                    "INSERT INTO approval_requests VALUES (?, ?, ?)",
                    (
                        request.request_id,
                        request.task_id,
                        request.model_dump_json(),
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise ApprovalError(
                "approval request already exists",
                details={"request_id": request.request_id},
            ) from exc

    def record_decision(self, decision: ApprovalDecision) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO approval_decisions VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(request_id) DO UPDATE SET
                    approved=excluded.approved,
                    actor=excluded.actor,
                    reason=excluded.reason,
                    decided_at=excluded.decided_at
                """,
                (
                    decision.request_id,
                    int(decision.approved),
                    decision.actor,
                    decision.reason,
                    decision.decided_at.isoformat(),
                ),
            )

    def get_request(self, request_id: str) -> ApprovalRequest | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM approval_requests WHERE request_id = ?",
                (request_id,),
            ).fetchone()
        return ApprovalRequest.model_validate_json(row["payload"]) if row else None

    def get_decision(self, request_id: str) -> ApprovalDecision | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM approval_decisions WHERE request_id = ?",
                (request_id,),
            ).fetchone()
        if row is None:
            return None
        return ApprovalDecision(
            request_id=row["request_id"],
            approved=bool(row["approved"]),
            actor=row["actor"],
            reason=row["reason"],
            decided_at=datetime.fromisoformat(row["decided_at"]),
        )


class CLIApprovalGate:
    def __init__(
        self,
        store: ApprovalStore,
        *,
        input_fn: Callable[[str], str] = input,
    ) -> None:
        self.store = store
        self.input_fn = input_fn

    def request(
        self,
        request: ApprovalRequest,
        *,
        actor: str = "operator",
    ) -> ApprovalDecision:
        self.store.record_request(request)
        answer = self.input_fn(
            f"Approve patch {request.request_id} for {request.task_id}? [approve/reject]: "
        )
        approved = answer.strip().lower() in {"approve", "approved", "y", "yes"}
        reason = "approved by CLI operator" if approved else "rejected by CLI operator"
        decision = ApprovalDecision(
            request_id=request.request_id,
            approved=approved,
            actor=actor,
            reason=reason,
            decided_at=datetime.now(timezone.utc),
        )
        self.store.record_decision(decision)
        return decision


class PatchExporter:
    def __init__(self, store: ApprovalStore) -> None:
        self.store = store

    def export(self, request_id: str) -> PatchExport:
        request = self.store.get_request(request_id)
        decision = self.store.get_decision(request_id)
        if request is None or decision is None:
            raise ApprovalError(
                "patch export requires an approval request and decision",
                details={"request_id": request_id},
            )
        if not decision.approved:
            raise ApprovalError(
                "patch export was rejected by the human approver",
                details={"request_id": request_id, "actor": decision.actor},
            )
        return PatchExport(
            request_id=request_id,
            approved_by=decision.actor,
            unified_diff=request.unified_diff,
        )
