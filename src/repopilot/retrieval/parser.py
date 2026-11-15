"""Python AST parsing and structured Function/Class/Method chunking."""

from __future__ import annotations

import ast
from dataclasses import dataclass

from repopilot.retrieval.models import CodeChunk, SymbolType


@dataclass(frozen=True)
class ChunkingResult:
    chunks: list[CodeChunk]
    errors: list[str]


class PythonASTParser:
    def parse(
        self,
        *,
        file_path: str,
        content: str,
        repository_commit: str,
    ) -> ChunkingResult:
        try:
            tree = ast.parse(content, filename=file_path)
        except (SyntaxError, ValueError) as exc:
            chunk = self._text_chunk(
                file_path=file_path,
                content=content,
                repository_commit=repository_commit,
            )
            return ChunkingResult(
                chunks=[chunk] if chunk is not None else [],
                errors=[f"{file_path}: AST parse failed: {type(exc).__name__}: {exc}"],
            )

        lines = content.splitlines()
        chunks: list[CodeChunk] = []

        def source_for(node: ast.AST) -> str:
            start = getattr(node, "lineno", 1)
            end = getattr(node, "end_lineno", start) or start
            return "\n".join(lines[start - 1 : end]) + "\n"

        def add_chunk(
            node: ast.AST,
            *,
            symbol_type: SymbolType,
            symbol: str | None,
            parent_symbol: str | None,
        ) -> None:
            start = getattr(node, "lineno", 1)
            end = getattr(node, "end_lineno", start) or start
            if end < start:
                end = start
            chunks.append(
                CodeChunk(
                    chunk_id=f"{file_path}:{start}:{symbol_type}:{symbol or 'module'}",
                    file_path=file_path,
                    start_line=start,
                    end_line=end,
                    symbol=symbol,
                    symbol_type=symbol_type,
                    parent_symbol=parent_symbol,
                    content=source_for(node),
                    repository_commit=repository_commit,
                )
            )

        def visit(node: ast.AST, parent_symbol: str | None = None) -> None:
            if isinstance(node, ast.ClassDef):
                add_chunk(
                    node,
                    symbol_type="class",
                    symbol=node.name,
                    parent_symbol=parent_symbol,
                )
                class_name = f"{parent_symbol}.{node.name}" if parent_symbol else node.name
                for child in node.body:
                    visit(child, parent_symbol=class_name)
                return
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                is_method = parent_symbol is not None
                add_chunk(
                    node,
                    symbol_type="method" if is_method else "function",
                    symbol=node.name,
                    parent_symbol=parent_symbol,
                )
                function_name = f"{parent_symbol}.{node.name}" if parent_symbol else node.name
                for child in node.body:
                    visit(child, parent_symbol=function_name)
                return
            for child in ast.iter_child_nodes(node):
                visit(child, parent_symbol=parent_symbol)

        for node in tree.body:
            visit(node)
        return ChunkingResult(chunks=chunks, errors=[])

    def _text_chunk(
        self,
        *,
        file_path: str,
        content: str,
        repository_commit: str,
    ) -> CodeChunk | None:
        if not content:
            return None
        end_line = max(1, len(content.splitlines()))
        return CodeChunk(
            chunk_id=f"{file_path}:1:text:module",
            file_path=file_path,
            start_line=1,
            end_line=end_line,
            symbol=None,
            symbol_type="text",
            parent_symbol=None,
            content=content,
            repository_commit=repository_commit,
        )
