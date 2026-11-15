"""Memory retrieval with planner-adoption auditing."""

from __future__ import annotations

from datetime import datetime, timezone

from repopilot.core.schemas import MemoryHit
from repopilot.memory.schemas import MemoryRetrievalRecord
from repopilot.memory.store import ExperienceStore, to_memory_hits


class MemoryRetriever:
    def __init__(self, store: ExperienceStore) -> None:
        self.store = store

    def retrieve(
        self,
        query: str,
        *,
        source_task_id: str | None = None,
        limit: int = 5,
        include_failed: bool = False,
        planner_adopted: bool = False,
    ) -> list[MemoryHit]:
        results = self.store.search(query, limit=limit, include_failed=include_failed)
        now = datetime.now(timezone.utc)
        for result in results:
            self.store.record_retrieval(
                MemoryRetrievalRecord(
                    memory_id=result.memory_id,
                    source_task_id=source_task_id,
                    query=query,
                    retrieval_score=result.score,
                    planner_adopted=planner_adopted,
                    retrieved_at=now,
                )
            )
        return to_memory_hits(results)
