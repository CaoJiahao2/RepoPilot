"""Configurable weighted or reciprocal-rank retrieval fusion."""

from __future__ import annotations

from collections import defaultdict
from typing import Mapping

from pydantic import Field

from repopilot.core.schemas import RepoPilotModel
from repopilot.retrieval.models import RetrievalHit


class FusionConfig(RepoPilotModel):
    mode: str = Field(default="weighted", pattern="^(weighted|rrf)$")
    alpha: float = Field(default=0.5, ge=0)
    beta: float = Field(default=0.3, ge=0)
    gamma: float = Field(default=0.2, ge=0)
    rrf_k: int = Field(default=60, ge=1)


def _normalized(group: list[RetrievalHit]) -> dict[str, float]:
    if not group:
        return {}
    maximum = max(hit.score for hit in group)
    return {
        hit.chunk_id: hit.score / maximum if maximum else 0.0
        for hit in group
    }


def fuse_hits(
    groups: Mapping[str, list[RetrievalHit]],
    *,
    config: FusionConfig | None = None,
) -> list[RetrievalHit]:
    config = config or FusionConfig()
    sources_by_chunk: dict[str, set[str]] = defaultdict(set)
    reasons_by_chunk: dict[str, list[str]] = defaultdict(list)
    for hits in groups.values():
        for hit in hits:
            sources_by_chunk[hit.chunk_id].update(hit.sources)
            reasons_by_chunk[hit.chunk_id].append(hit.reason)

    scores: dict[str, float] = defaultdict(float)
    if config.mode == "weighted":
        normalized = {name: _normalized(hits) for name, hits in groups.items()}
        weights = {
            "bm25": config.alpha,
            "vector": config.beta,
            "symbol": config.gamma,
            "path": config.gamma,
            "stack_line": config.gamma,
        }
        for name, values in normalized.items():
            weight = weights.get(name, 0.0)
            for chunk_id, score in values.items():
                scores[chunk_id] += weight * score
    else:
        for hits in groups.values():
            ranked = sorted(hits, key=lambda hit: (-hit.score, hit.chunk_id))
            for rank, hit in enumerate(ranked, start=1):
                scores[hit.chunk_id] += 1.0 / (config.rrf_k + rank)

    return [
        RetrievalHit(
            chunk_id=chunk_id,
            score=score,
            sources=sorted(sources_by_chunk[chunk_id]),
            reason="; ".join(reason for reason in reasons_by_chunk[chunk_id] if reason),
        )
        for chunk_id, score in sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    ]
