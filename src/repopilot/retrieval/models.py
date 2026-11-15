"""Code RAG data models."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from repopilot.core.schemas import RepoPilotModel

SymbolType = Literal["function", "class", "method", "text"]
RetrievalSource = Literal["path", "symbol", "stack_line", "bm25", "vector", "memory"]


class CodeChunk(RepoPilotModel):
    chunk_id: str = Field(min_length=1)
    file_path: str = Field(min_length=1)
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    symbol: str | None = Field(default=None, min_length=1)
    symbol_type: SymbolType
    parent_symbol: str | None = Field(default=None, min_length=1)
    content: str = Field(min_length=1)
    repository_commit: str = Field(min_length=1)


class RetrievalHit(RepoPilotModel):
    chunk_id: str = Field(min_length=1)
    score: float = Field(ge=0)
    sources: list[RetrievalSource] = Field(min_length=1)
    reason: str = ""


class CodeIndex(RepoPilotModel):
    repository_commit: str = Field(min_length=1)
    chunks: list[CodeChunk] = Field(default_factory=list)
    indexed_files: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
