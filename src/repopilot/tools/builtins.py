"""Registration factory for the first read-only tool set."""

from __future__ import annotations

from repopilot.tools.base import ToolRegistry, ToolSpec
from repopilot.tools.files import (
    ListFilesInput,
    ReadFileInput,
    list_files_handler,
    read_file_handler,
)
from repopilot.tools.git import (
    GitDiffInput,
    GitStatusInput,
    git_diff_handler,
    git_status_handler,
)
from repopilot.tools.search import SearchCodeInput, search_code_handler


def register_read_only_tools(registry: ToolRegistry) -> ToolRegistry:
    registry.register(
        ToolSpec(
            name="list_files",
            description="List files and directories inside the allowed repository root.",
            input_model=ListFilesInput,
            handler=list_files_handler,
            risk_level="read",
            timeout_seconds=10,
            idempotent=True,
            requires_approval=False,
        )
    )
    registry.register(
        ToolSpec(
            name="search_code",
            description="Search source text inside the allowed repository root.",
            input_model=SearchCodeInput,
            handler=search_code_handler,
            risk_level="read",
            timeout_seconds=15,
            idempotent=True,
            requires_approval=False,
        )
    )
    registry.register(
        ToolSpec(
            name="read_file",
            description="Read one UTF-8 text file inside the allowed repository root.",
            input_model=ReadFileInput,
            handler=read_file_handler,
            risk_level="read",
            timeout_seconds=10,
            idempotent=True,
            requires_approval=False,
        )
    )
    registry.register(
        ToolSpec(
            name="git_status",
            description="Read Git working-tree status without modifying the repository.",
            input_model=GitStatusInput,
            handler=git_status_handler,
            risk_level="read",
            timeout_seconds=10,
            idempotent=True,
            requires_approval=False,
        )
    )
    registry.register(
        ToolSpec(
            name="git_diff",
            description="Read a Git diff without modifying the repository.",
            input_model=GitDiffInput,
            handler=git_diff_handler,
            risk_level="read",
            timeout_seconds=15,
            idempotent=True,
            requires_approval=False,
        )
    )
    return registry


def build_default_registry() -> ToolRegistry:
    return register_read_only_tools(ToolRegistry())
