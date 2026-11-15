"""SQLite-backed experience store with keyword retrieval and audit records."""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Protocol

from repopilot.core.errors import MemoryWriteError
from repopilot.memory.schemas import (
    Experience,
    MemoryRetrievalRecord,
    MemorySearchResult,
)
from repopilot.core.schemas import MemoryHit

_TOKEN_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class ExperienceStore(Protocol):
    def save(self, experience: Experience) -> None: ...
    def get(self, memory_id: str) -> Experience | None: ...
    def search(
        self,
        query: str,
        *,
        limit: int = 5,
        include_failed: bool = False,
    ) -> list[MemorySearchResult]: ...
    def record_retrieval(self, record: MemoryRetrievalRecord) -> int: ...
    def set_planner_adoption(self, retrieval_id: int, adopted: bool) -> None: ...
    def list_retrievals(self, *, memory_id: str | None = None) -> list[MemoryRetrievalRecord]: ...


class SQLiteExperienceStore:
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
                CREATE TABLE IF NOT EXISTS experiences (
                    experience_id TEXT PRIMARY KEY,
                    source_task_id TEXT,
                    outcome TEXT NOT NULL,
                    issue_summary TEXT NOT NULL,
                    root_cause TEXT NOT NULL,
                    solution_summary TEXT NOT NULL,
                    embedding_text TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_retrievals (
                    retrieval_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    memory_id TEXT NOT NULL,
                    source_task_id TEXT,
                    query TEXT NOT NULL,
                    retrieval_score REAL NOT NULL,
                    planner_adopted INTEGER NOT NULL DEFAULT 0,
                    retrieved_at TEXT NOT NULL
                )
                """
            )

    def save(self, experience: Experience) -> None:
        if experience.outcome == "verified_success" and not (
            experience.target_tests_passed and experience.regression_tests_passed
        ):
            raise MemoryWriteError(
                "verified_success experience requires passing target and regression tests",
                details={"memory_id": experience.experience_id},
            )
        payload = experience.model_dump(mode="json")
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO experiences (
                        experience_id, source_task_id, outcome, issue_summary,
                        root_cause, solution_summary, embedding_text, created_at, payload
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        experience.experience_id,
                        experience.source_task_id,
                        experience.outcome,
                        experience.issue_summary,
                        experience.root_cause,
                        experience.solution_summary,
                        experience.embedding_text,
                        experience.created_at.isoformat(),
                        json.dumps(payload, sort_keys=True),
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise MemoryWriteError(
                "experience_id already exists",
                details={"memory_id": experience.experience_id},
            ) from exc

    def get(self, memory_id: str) -> Experience | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM experiences WHERE experience_id = ?",
                (memory_id,),
            ).fetchone()
        return Experience.model_validate_json(row["payload"]) if row else None

    def search(
        self,
        query: str,
        *,
        limit: int = 5,
        include_failed: bool = False,
    ) -> list[MemorySearchResult]:
        tokens = set(_TOKEN_PATTERN.findall(query.lower()))
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload, outcome FROM experiences"
            ).fetchall()
        results: list[tuple[float, str, Experience]] = []
        query_lower = query.lower()
        for row in rows:
            experience = Experience.model_validate_json(row["payload"])
            if not include_failed and experience.outcome != "verified_success":
                continue
            searchable = " ".join(
                [
                    experience.issue_summary,
                    experience.root_cause,
                    experience.solution_summary,
                    experience.embedding_text,
                    " ".join(experience.affected_symbols),
                ]
            ).lower()
            overlap = sum(1 for token in tokens if token in searchable)
            phrase_bonus = 2.0 if query_lower in searchable else 0.0
            score = min(1.0, (overlap + phrase_bonus) / max(1, len(tokens) + 2))
            if score > 0:
                results.append((score, experience.experience_id, experience))
        results.sort(key=lambda item: (-item[0], item[1]))
        return [
            MemorySearchResult(
                memory_id=experience.experience_id,
                score=score,
                outcome=experience.outcome,
                issue_summary=experience.issue_summary,
                root_cause=experience.root_cause,
                solution_summary=experience.solution_summary,
                applicability_conditions=experience.applicability_conditions,
            )
            for score, _, experience in results[:limit]
        ]

    def record_retrieval(self, record: MemoryRetrievalRecord) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO memory_retrievals (
                    memory_id, source_task_id, query, retrieval_score,
                    planner_adopted, retrieved_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    record.memory_id,
                    record.source_task_id,
                    record.query,
                    record.retrieval_score,
                    int(record.planner_adopted),
                    record.retrieved_at.isoformat(),
                ),
            )
            return int(cursor.lastrowid)

    def set_planner_adoption(self, retrieval_id: int, adopted: bool) -> None:
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE memory_retrievals SET planner_adopted = ? WHERE retrieval_id = ?",
                (int(adopted), retrieval_id),
            )
            if cursor.rowcount != 1:
                raise MemoryWriteError(
                    "memory retrieval record was not found",
                    details={"retrieval_id": retrieval_id},
                )

    def list_retrievals(self, *, memory_id: str | None = None) -> list[MemoryRetrievalRecord]:
        query = "SELECT * FROM memory_retrievals"
        params: tuple[object, ...] = ()
        if memory_id is not None:
            query += " WHERE memory_id = ?"
            params = (memory_id,)
        query += " ORDER BY retrieval_id"
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [
            MemoryRetrievalRecord(
                retrieval_id=row["retrieval_id"],
                memory_id=row["memory_id"],
                source_task_id=row["source_task_id"],
                query=row["query"],
                retrieval_score=row["retrieval_score"],
                planner_adopted=bool(row["planner_adopted"]),
                retrieved_at=datetime.fromisoformat(row["retrieved_at"]),
            )
            for row in rows
        ]


def to_memory_hits(results: Iterable[MemorySearchResult]) -> list[MemoryHit]:
    return [
        MemoryHit(
            experience_id=result.memory_id,
            summary=result.issue_summary,
            source="experience_memory",
            retrieval_score=result.score,
            verified=result.outcome == "verified_success",
        )
        for result in results
    ]
