"""Small dependency-free BM25 index for code chunks."""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict

from repopilot.retrieval.models import CodeChunk, RetrievalHit

_TOKEN_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|\d+")


def tokenize(text: str) -> list[str]:
    return _TOKEN_PATTERN.findall(text.lower())


class BM25Index:
    def __init__(
        self,
        chunks: list[CodeChunk],
        *,
        k1: float = 1.5,
        b: float = 0.75,
    ) -> None:
        self.chunks = chunks
        self.k1 = k1
        self.b = b
        self._tokens = [tokenize(chunk.content) for chunk in chunks]
        self._term_counts = [Counter(tokens) for tokens in self._tokens]
        self._doc_lengths = [len(tokens) for tokens in self._tokens]
        self._average_length = (
            sum(self._doc_lengths) / len(self._doc_lengths) if self._doc_lengths else 0.0
        )
        document_frequency: dict[str, int] = defaultdict(int)
        for counts in self._term_counts:
            for term in counts:
                document_frequency[term] += 1
        self._idf = {
            term: math.log(
                1.0 + (len(chunks) - frequency + 0.5) / (frequency + 0.5)
            )
            for term, frequency in document_frequency.items()
        }

    def search(self, query: str, *, limit: int = 5) -> list[RetrievalHit]:
        query_terms = tokenize(query)
        if not query_terms or not self.chunks:
            return []
        scores: list[tuple[float, str]] = []
        for index, counts in enumerate(self._term_counts):
            score = 0.0
            document_length = self._doc_lengths[index] or 1
            for term in query_terms:
                frequency = counts.get(term, 0)
                if not frequency:
                    continue
                idf = self._idf.get(term, 0.0)
                denominator = frequency + self.k1 * (
                    1.0 - self.b + self.b * document_length / (self._average_length or 1.0)
                )
                score += idf * frequency * (self.k1 + 1.0) / denominator
            if score > 0:
                scores.append((score, self.chunks[index].chunk_id))
        scores.sort(key=lambda item: (-item[0], item[1]))
        return [
            RetrievalHit(chunk_id=chunk_id, score=score, sources=["bm25"], reason="BM25 lexical match")
            for score, chunk_id in scores[:limit]
        ]
