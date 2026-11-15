"""Optional embedding-backed vector retrieval with graceful degradation."""

from __future__ import annotations

import json
import math
import urllib.error
import urllib.request
from typing import Protocol, Sequence

from repopilot.core.config import AppConfig
from repopilot.core.errors import ExternalServiceUnavailableError
from repopilot.retrieval.models import CodeChunk, RetrievalHit


class EmbeddingProvider(Protocol):
    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        ...


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    numerator = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if not left_norm or not right_norm:
        return 0.0
    return numerator / (left_norm * right_norm)


class VectorIndex:
    def __init__(self, chunks: list[CodeChunk], provider: EmbeddingProvider | None = None) -> None:
        self.chunks = chunks
        self.provider = provider
        self.vectors: list[list[float]] = []
        self.available = False
        self.disabled_reason: str | None = None
        self._build()

    def _build(self) -> None:
        if self.provider is None:
            self.disabled_reason = "embedding provider is not configured"
            return
        try:
            vectors = self.provider.embed([chunk.content for chunk in self.chunks])
        except Exception as exc:
            self.disabled_reason = f"embedding provider failed: {type(exc).__name__}"
            return
        if len(vectors) != len(self.chunks) or any(not vector for vector in vectors):
            self.disabled_reason = "embedding provider returned invalid vectors"
            return
        self.vectors = vectors
        self.available = True

    def search(self, query: str, *, limit: int = 5) -> list[RetrievalHit]:
        if not self.available or not self.chunks:
            return []
        try:
            query_vectors = self.provider.embed([query])
        except Exception as exc:
            self.disabled_reason = f"embedding query failed: {type(exc).__name__}"
            self.available = False
            return []
        if not query_vectors or not query_vectors[0]:
            return []
        scores = [
            (_cosine(query_vectors[0], vector), chunk.chunk_id)
            for vector, chunk in zip(self.vectors, self.chunks)
        ]
        scores.sort(key=lambda item: (-item[0], item[1]))
        return [
            RetrievalHit(
                chunk_id=chunk_id,
                score=max(0.0, score),
                sources=["vector"],
                reason="cosine embedding similarity",
            )
            for score, chunk_id in scores[:limit]
            if score > 0
        ]


class OpenAICompatibleEmbeddingClient:
    """Optional OpenAI-compatible embeddings adapter."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: float = 60.0,
    ) -> None:
        if not base_url or not api_key or not model:
            raise ValueError("base_url, api_key, and model are required")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        request = urllib.request.Request(
            f"{self.base_url}/embeddings",
            data=json.dumps({"model": self.model, "input": list(texts)}).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise ExternalServiceUnavailableError(
                "embedding API request failed",
                details={"provider": "openai-compatible", "reason": type(exc).__name__},
            ) from exc
        try:
            return [item["embedding"] for item in payload["data"]]
        except (KeyError, TypeError) as exc:
            raise ExternalServiceUnavailableError(
                "embedding API response did not contain vectors",
                details={"provider": "openai-compatible"},
            ) from exc


def build_embedding_provider(config: AppConfig) -> EmbeddingProvider | None:
    if not config.embedding.enabled:
        return None
    provider = (config.embedding.provider or "").lower()
    if provider not in {"openai", "openai-compatible"}:
        raise ExternalServiceUnavailableError(
            "configured embedding provider is not supported",
            details={"provider": provider or "unknown"},
        )
    if not config.embedding.base_url or not config.embedding.api_key or not config.embedding.model:
        raise ExternalServiceUnavailableError(
            "enabled embedding provider is missing base_url, api_key, or model",
            details={"provider": provider},
        )
    return OpenAICompatibleEmbeddingClient(
        base_url=config.embedding.base_url,
        api_key=config.embedding.api_key.get_secret_value(),
        model=config.embedding.model,
    )
