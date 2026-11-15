"""Read-only file tools with repository path confinement."""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import Field

from repopilot.core.errors import ToolExecutionError
from repopilot.tools.base import ToolContext, ToolInput


class ListFilesInput(ToolInput):
    path: str = "."
    max_entries: int = Field(default=1_000, ge=1, le=10_000)


class ReadFileInput(ToolInput):
    path: str = Field(min_length=1)
    max_bytes: int = Field(default=100_000, ge=1, le=1_000_000)


def list_files_handler(arguments: ListFilesInput, context: ToolContext) -> dict:
    root = context.resolve_path(arguments.path, expected="dir", must_exist=True)
    files: list[str] = []
    directories: list[str] = []
    truncated = False

    for current, dirnames, filenames in os.walk(root, followlinks=False):
        current_path = Path(current)
        dirnames[:] = sorted(
            dirname
            for dirname in dirnames
            if not (current_path / dirname).is_symlink()
        )
        for dirname in dirnames:
            if len(files) + len(directories) >= arguments.max_entries:
                truncated = True
                break
            directories.append((current_path / dirname).relative_to(context.allowed_root).as_posix())
        if truncated:
            break

        for filename in sorted(filenames):
            if len(files) + len(directories) >= arguments.max_entries:
                truncated = True
                break
            file_path = current_path / filename
            if file_path.is_symlink():
                continue
            files.append(file_path.relative_to(context.allowed_root).as_posix())
        if truncated:
            break

    return {
        "path": arguments.path,
        "directories": sorted(directories),
        "files": sorted(files),
        "truncated": truncated,
    }


def read_file_handler(arguments: ReadFileInput, context: ToolContext) -> str:
    target = context.resolve_path(arguments.path, expected="file", must_exist=True)
    limit = min(arguments.max_bytes, context.max_output_bytes, context.max_file_bytes)
    size = target.stat().st_size
    if size > limit:
        raise ToolExecutionError(
            "file exceeds configured read limit",
            details={
                "error_code": "file_too_large",
                "path": arguments.path,
                "file_size": size,
                "limit_bytes": limit,
            },
        )

    data = target.read_bytes()
    if len(data) > limit:
        raise ToolExecutionError(
            "file exceeds configured read limit",
            details={
                "error_code": "file_too_large",
                "path": arguments.path,
                "file_size": len(data),
                "limit_bytes": limit,
            },
        )
    if b"\x00" in data:
        raise ToolExecutionError(
            "binary files are not supported by read_file",
            details={"error_code": "binary_file", "path": arguments.path},
        )
    return data.decode("utf-8", errors="replace")
