"""Public agent task and private evaluator task loading."""

from __future__ import annotations

import json
import tarfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import Field

from repopilot.core.errors import SchemaValidationError
from repopilot.core.schemas import RepoPilotModel


class AgentTask(RepoPilotModel):
    task_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    repository_fixture: str = Field(min_length=1)
    base_commit: str = Field(min_length=1)
    issue: str = Field(min_length=5)
    stack_trace: str | None = None
    test_command: list[str] = Field(min_length=1)
    expected_behavior: str = Field(min_length=1)
    metadata: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class EvaluationTask(RepoPilotModel):
    task_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    gold_patch: str = Field(min_length=1)
    verification_command: list[str] = Field(min_length=1)
    expected_root_cause: str = Field(min_length=1)
    regression_command: list[str] | None = None


@dataclass(frozen=True)
class TaskBundle:
    root: Path
    public: AgentTask
    private: EvaluationTask

    @property
    def repository_path(self) -> Path:
        repository = (self.root / self.public.repository_fixture).resolve()
        self._restore_git_metadata(repository)
        return repository

    def _restore_git_metadata(self, repository: Path) -> None:
        if (repository / ".git").exists():
            return
        archive_path = self.root / "repo-git.tar.gz"
        if not archive_path.is_file():
            raise SchemaValidationError(
                "repository fixture has no Git metadata archive",
                details={"task_id": self.public.task_id},
            )
        with tarfile.open(archive_path, "r:gz") as archive:
            for member in archive.getmembers():
                parts = Path(member.name).parts
                if member.name not in {".git", ".git/"} and (not parts or parts[0] != ".git" or ".." in parts):
                    raise SchemaValidationError(
                        "repository Git metadata archive contains an unsafe path",
                        details={"task_id": self.public.task_id},
                    )
            archive.extractall(repository, filter="data")

    def agent_input(self) -> AgentTask:
        return self.public.model_copy(deep=True)


def load_task_bundle(task_dir: str | Path) -> TaskBundle:
    root = Path(task_dir).expanduser().resolve(strict=True)
    public_path = root / "task.json"
    private_path = root / "private" / "evaluation.json"
    try:
        public_data = json.loads(public_path.read_text(encoding="utf-8"))
        private_data = json.loads(private_path.read_text(encoding="utf-8"))
        public = AgentTask.model_validate(public_data)
        private = EvaluationTask.model_validate(private_data)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise SchemaValidationError(
            "benchmark task files are invalid",
            details={"task_dir": str(root), "reason": type(exc).__name__},
        ) from exc
    if public.task_id != private.task_id:
        raise SchemaValidationError(
            "public and private task IDs do not match",
            details={"task_dir": str(root)},
        )
    return TaskBundle(root=root, public=public, private=private)


def load_dataset(dataset_dir: str | Path, task_ids: list[str] | None = None) -> list[TaskBundle]:
    root = Path(dataset_dir).expanduser().resolve(strict=True)
    selected = set(task_ids or [])
    bundles = [
        load_task_bundle(path)
        for path in sorted(root.iterdir())
        if path.is_dir() and (path / "task.json").is_file()
    ]
    if selected:
        bundles = [bundle for bundle in bundles if bundle.public.task_id in selected]
        found = {bundle.public.task_id for bundle in bundles}
        missing = sorted(selected - found)
        if missing:
            raise SchemaValidationError(
                "requested benchmark tasks were not found",
                details={"task_ids": missing},
            )
    return bundles
