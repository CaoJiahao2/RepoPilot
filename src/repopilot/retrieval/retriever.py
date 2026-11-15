"""Precise, lexical, vector, and fused code retrieval."""

from __future__ import annotations

import re
from pathlib import Path

from repopilot.core.schemas import Evidence
from repopilot.retrieval.fusion import FusionConfig, fuse_hits
from repopilot.retrieval.models import CodeChunk, CodeIndex, RetrievalHit
from repopilot.retrieval.sparse import BM25Index
from repopilot.retrieval.vector import EmbeddingProvider, VectorIndex

_FILE_LINE_PATTERNS = (
    re.compile(r"File [\"'](?P<path>[^\"']+)[\"'], line (?P<line>\d+)"),
    re.compile(r"(?P<path>[^\s:]+\.py):(?P<line>\d+)"),
)


class CodeRAGRetriever:
    def __init__(
        self,
        index: CodeIndex,
        *,
        vector_provider: EmbeddingProvider | None = None,
        fusion_config: FusionConfig | None = None,
    ) -> None:
        self.index = index
        self.chunks = {chunk.chunk_id: chunk for chunk in index.chunks}
        self.bm25 = BM25Index(index.chunks)
        self.vector = VectorIndex(index.chunks, vector_provider)
        self.fusion_config = fusion_config or FusionConfig()

    def search(
        self,
        query: str,
        *,
        stack_trace: str | None = None,
        file_path: str | None = None,
        symbol: str | None = None,
        limit: int = 5,
    ) -> list[RetrievalHit]:
        groups: dict[str, list[RetrievalHit]] = {
            "path": self._path_hits(file_path),
            "symbol": self._symbol_hits(query, symbol),
            "stack_line": self._stack_hits(stack_trace),
            "bm25": self.bm25.search(query, limit=limit * 2),
            "vector": self.vector.search(query, limit=limit * 2),
        }
        fused = fuse_hits(groups, config=self.fusion_config)
        return fused[:limit]

    def to_evidence(self, hits: list[RetrievalHit]) -> list[Evidence]:
        evidence: list[Evidence] = []
        for hit in hits:
            chunk = self.chunks.get(hit.chunk_id)
            if chunk is None:
                continue
            evidence.append(
                Evidence(
                    evidence_id=f"ev-{chunk.chunk_id}",
                    source_type="source_code",
                    file_path=chunk.file_path,
                    line_start=chunk.start_line,
                    line_end=chunk.end_line,
                    symbol=chunk.symbol,
                    content=chunk.content,
                    retrieval_score=min(1.0, hit.score),
                    retrieval_sources=hit.sources,
                    repository_commit=chunk.repository_commit,
                )
            )
        return evidence

    def _path_hits(self, file_path: str | None) -> list[RetrievalHit]:
        if not file_path:
            return []
        wanted = Path(file_path).as_posix()
        hits = []
        for chunk in self.index.chunks:
            matches = (
                chunk.file_path == wanted
                or chunk.file_path.endswith(f"/{wanted}")
                or Path(chunk.file_path).name == Path(wanted).name
            )
            if matches:
                hits.append(
                    RetrievalHit(
                        chunk_id=chunk.chunk_id,
                        score=1.0,
                        sources=["path"],
                        reason="exact file path match",
                    )
                )
        return hits

    def _symbol_hits(self, query: str, symbol: str | None) -> list[RetrievalHit]:
        query_tokens = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", query.lower()))
        wanted = symbol.lower() if symbol else None
        hits = []
        for chunk in self.index.chunks:
            candidates = {chunk.symbol.lower()} if chunk.symbol else set()
            if chunk.symbol and chunk.parent_symbol:
                candidates.add(f"{chunk.parent_symbol}.{chunk.symbol}".lower())
            matched = (wanted is not None and wanted in candidates) or (
                wanted is None and bool(candidates & query_tokens)
            )
            if matched:
                hits.append(
                    RetrievalHit(
                        chunk_id=chunk.chunk_id,
                        score=1.0,
                        sources=["symbol"],
                        reason="exact symbol match",
                    )
                )
        return hits

    def _stack_hits(self, stack_trace: str | None) -> list[RetrievalHit]:
        if not stack_trace:
            return []
        matches: list[tuple[str, int]] = []
        for pattern in _FILE_LINE_PATTERNS:
            for match in pattern.finditer(stack_trace):
                matches.append((match.group("path"), int(match.group("line"))))
        hits = []
        for path, line_number in matches:
            wanted = Path(path).as_posix()
            for chunk in self.index.chunks:
                path_matches = (
                    chunk.file_path == wanted
                    or chunk.file_path.endswith(f"/{wanted}")
                    or Path(chunk.file_path).name == Path(wanted).name
                )
                if path_matches and chunk.start_line <= line_number <= chunk.end_line:
                    hits.append(
                        RetrievalHit(
                            chunk_id=chunk.chunk_id,
                            score=1.0,
                            sources=["stack_line"],
                            reason=f"stack trace line {line_number}",
                        )
                    )
        return hits
