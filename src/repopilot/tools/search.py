"""Read-only source search without shell command interpolation."""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import Field

from repopilot.tools.base import ToolContext, ToolInput


class SearchCodeInput(ToolInput):
    query: str = Field(min_length=1)
    path: str = "."
    max_results: int = Field(default=100, ge=1, le=1_000)
    max_file_bytes: int = Field(default=1_000_000, ge=1, le=5_000_000)


def search_code_handler(arguments: SearchCodeInput, context: ToolContext) -> dict:
    root = context.resolve_path(arguments.path, expected="dir", must_exist=True)
    matches: list[dict[str, object]] = []
    truncated = False
    max_file_bytes = min(arguments.max_file_bytes, context.max_file_bytes)

    for current, dirnames, filenames in os.walk(root, followlinks=False):
        current_path = Path(current)
        dirnames[:] = sorted(
            dirname
            for dirname in dirnames
            if not (current_path / dirname).is_symlink()
        )
        for filename in sorted(filenames):
            file_path = current_path / filename
            if file_path.is_symlink() or not file_path.is_file():
                continue
            if file_path.stat().st_size > max_file_bytes:
                continue
            try:
                content = file_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for line_number, line in enumerate(content.splitlines(), start=1):
                if arguments.query in line:
                    matches.append(
                        {
                            "path": file_path.relative_to(context.allowed_root).as_posix(),
                            "line_number": line_number,
                            "line": line[:500],
                        }
                    )
                    if len(matches) >= arguments.max_results:
                        truncated = True
                        break
            if truncated:
                break
        if truncated:
            break

    return {
        "query": arguments.query,
        "path": arguments.path,
        "matches": matches,
        "truncated": truncated,
    }
