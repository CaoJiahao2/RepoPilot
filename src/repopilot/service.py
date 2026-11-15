"""Task lifecycle service shared by CLI and FastAPI."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Protocol

from pydantic import Field

from repopilot.core.errors import ApprovalError, CheckpointError
from repopilot.core.schemas import EndToEndReport, RepoPilotModel, TaskRequest, TraceEvent


class TaskExecutor(Protocol):
    def run(self, task: TaskRequest) -> EndToEndReport:
        ...


class TaskRecord(RepoPilotModel):
    task_id: str
    request: TaskRequest
    status: str = Field(pattern="^(queued|running|succeeded|failed|cancelled)$")
    created_at: datetime
    updated_at: datetime
    report: EndToEndReport | None = None
    error_code: str | None = None
    error_message: str | None = None
    approval_status: str = Field(default="pending", pattern="^(pending|approved|rejected)$")
    approval_actor: str | None = None
    approval_reason: str | None = None


class TaskArtifacts(RepoPilotModel):
    task_id: str
    patch_diff: str | None = None
    baseline_test_report: Any = None
    post_patch_test_report: Any = None
    review_result: Any = None
    report: EndToEndReport | None = None


class TaskStore(Protocol):
    def save(self, record: TaskRecord) -> None: ...
    def get(self, task_id: str) -> TaskRecord | None: ...
    def list(self) -> list[TaskRecord]: ...


class InMemoryTaskStore:
    def __init__(self) -> None:
        self._records: dict[str, TaskRecord] = {}

    def save(self, record: TaskRecord) -> None:
        self._records[record.task_id] = record

    def get(self, task_id: str) -> TaskRecord | None:
        return self._records.get(task_id)

    def list(self) -> list[TaskRecord]:
        return list(self._records.values())


class SQLiteTaskStore:
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
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL
                )
                """
            )

    def save(self, record: TaskRecord) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO tasks VALUES (?, ?)
                ON CONFLICT(task_id) DO UPDATE SET payload=excluded.payload
                """,
                (record.task_id, record.model_dump_json()),
            )

    def get(self, task_id: str) -> TaskRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
        return TaskRecord.model_validate_json(row["payload"]) if row else None

    def list(self) -> list[TaskRecord]:
        with self._connect() as connection:
            rows = connection.execute("SELECT payload FROM tasks ORDER BY task_id").fetchall()
        return [TaskRecord.model_validate_json(row["payload"]) for row in rows]


class UnavailableExecutor:
    def run(self, task: TaskRequest) -> EndToEndReport:
        return EndToEndReport(
            task_id=task.task_id,
            status="failed",
            summary="real repair executor is not configured",
            failure_node="environment",
            failure_reason="LLM/API or execution backend is not configured",
            execution_mode="unavailable",
        )


class TaskService:
    def __init__(
        self,
        *,
        executor: TaskExecutor | None = None,
        store: TaskStore | None = None,
        max_workers: int = 2,
    ) -> None:
        self.executor = executor or UnavailableExecutor()
        self.store = store or InMemoryTaskStore()
        self._executor_pool = ThreadPoolExecutor(max_workers=max_workers)
        self._futures: dict[str, Future[None]] = {}
        self._tokens: dict[str, Any] = {}
        self._lock = RLock()

    def submit(self, task: TaskRequest) -> TaskRecord:
        with self._lock:
            if self.store.get(task.task_id) is not None:
                raise CheckpointError(
                    "task_id already exists",
                    details={"task_id": task.task_id},
                )
            now = datetime.now(timezone.utc)
            record = TaskRecord(
                task_id=task.task_id,
                request=task,
                status="queued",
                created_at=now,
                updated_at=now,
            )
            self.store.save(record)
            future = self._executor_pool.submit(self._run, task.task_id)
            self._futures[task.task_id] = future
            return record

    def _run(self, task_id: str) -> None:
        with self._lock:
            record = self.store.get(task_id)
            if record is None or record.status == "cancelled":
                return
            record.status = "running"
            record.updated_at = datetime.now(timezone.utc)
            self.store.save(record)
            task = record.request

        try:
            report = self.executor.run(task)
            with self._lock:
                current = self.store.get(task_id)
                if current is None or current.status == "cancelled":
                    return
                current.report = report
                current.status = "succeeded" if report.status == "succeeded" else "failed"
                current.error_code = report.failure_node
                current.error_message = report.failure_reason
                current.updated_at = datetime.now(timezone.utc)
                self.store.save(current)
        except Exception as exc:
            with self._lock:
                current = self.store.get(task_id)
                if current is None or current.status == "cancelled":
                    return
                current.status = "failed"
                current.error_code = "executor_error"
                current.error_message = f"{type(exc).__name__}: {exc}"
                current.updated_at = datetime.now(timezone.utc)
                self.store.save(current)

    def list(self) -> list[TaskRecord]:
        return self.store.list()

    def get(self, task_id: str) -> TaskRecord:
        record = self.store.get(task_id)
        if record is None:
            raise KeyError(task_id)
        return record

    def wait(self, task_id: str, *, timeout: float = 10.0) -> TaskRecord:
        deadline = time.time() + timeout
        while time.time() < deadline:
            record = self.get(task_id)
            if record.status in {"succeeded", "failed", "cancelled"}:
                return record
            time.sleep(0.01)
        return self.get(task_id)

    def trace(self, task_id: str) -> list[TraceEvent]:
        record = self.get(task_id)
        return list(record.report.execution_trace if record.report else [])

    def artifacts(self, task_id: str) -> TaskArtifacts:
        record = self.get(task_id)
        report = record.report
        return TaskArtifacts(
            task_id=task_id,
            patch_diff=report.unified_diff if report else None,
            baseline_test_report=report.baseline_test_report if report else None,
            post_patch_test_report=report.post_patch_test_report if report else None,
            review_result=report.review_result if report else None,
            report=report,
        )

    def approve(
        self,
        task_id: str,
        *,
        approved: bool,
        actor: str,
        reason: str,
    ) -> TaskRecord:
        record = self.get(task_id)
        record.approval_status = "approved" if approved else "rejected"
        record.approval_actor = actor
        record.approval_reason = reason
        record.updated_at = datetime.now(timezone.utc)
        self.store.save(record)
        return record

    def cancel(self, task_id: str, *, reason: str = "cancelled") -> TaskRecord:
        with self._lock:
            record = self.get(task_id)
            if record.status in {"succeeded", "failed", "cancelled"}:
                return record
            record.status = "cancelled"
            record.error_code = "cancelled"
            record.error_message = reason
            record.updated_at = datetime.now(timezone.utc)
            self.store.save(record)
            return record
