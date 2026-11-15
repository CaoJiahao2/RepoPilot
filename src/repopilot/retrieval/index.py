"""Repository indexing with gitignore-aware Python chunk collection."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from pathspec import PathSpec

from repopilot.retrieval.models import CodeChunk, CodeIndex
from repopilot.retrieval.parser import PythonASTParser

DEFAULT_IGNORE_PATTERNS = (
    ".git/",
    ".git/**",
    ".venv/",
    "venv/",
    "__pycache__/",
    ".pytest_cache/",
    ".mypy_cache/",
    ".ruff_cache/",
    "build/",
    "dist/",
    "*.egg-info/",
    "node_modules/",
    "*.py[cod]",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "id_rsa*",
    "credentials*",
    ".env",
    ".env.*",
)


def resolve_repository_commit(repo_root: Path) -> str:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo_root),
            shell=False,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unversioned"
    if completed.returncode != 0:
        return "unversioned"
    return completed.stdout.strip() or "unversioned"


class RepositoryIndexer:
    def __init__(
        self,
        *,
        max_file_bytes: int = 1_000_000,
        parser: PythonASTParser | None = None,
    ) -> None:
        self.max_file_bytes = max_file_bytes
        self.parser = parser or PythonASTParser()

    def index(
        self,
        repo_path: str | Path,
        *,
        repository_commit: str | None = None,
    ) -> CodeIndex:
        root = Path(repo_path).expanduser().resolve(strict=True)
        commit = repository_commit or resolve_repository_commit(root)
        ignore_spec = self._ignore_spec(root)
        chunks: list[CodeChunk] = []
        indexed_files: list[str] = []
        errors: list[str] = []

        for current, dirnames, filenames in os.walk(root, followlinks=False):
            current_path = Path(current)
            dirnames[:] = sorted(
                dirname
                for dirname in dirnames
                if not (current_path / dirname).is_symlink()
                and not self._ignored(ignore_spec, root, current_path / dirname, is_dir=True)
            )
            for filename in sorted(filenames):
                file_path = current_path / filename
                relative = file_path.relative_to(root).as_posix()
                if file_path.is_symlink() or self._ignored(ignore_spec, root, file_path):
                    continue
                if file_path.suffix != ".py":
                    continue
                try:
                    size = file_path.stat().st_size
                except OSError as exc:
                    errors.append(f"{relative}: stat failed: {type(exc).__name__}")
                    continue
                if size > self.max_file_bytes:
                    errors.append(f"{relative}: file exceeds {self.max_file_bytes} bytes")
                    continue
                try:
                    data = file_path.read_bytes()
                except OSError as exc:
                    errors.append(f"{relative}: read failed: {type(exc).__name__}")
                    continue
                if b"\x00" in data:
                    errors.append(f"{relative}: binary file excluded")
                    continue
                content = data.decode("utf-8", errors="replace")
                result = self.parser.parse(
                    file_path=relative,
                    content=content,
                    repository_commit=commit,
                )
                chunks.extend(result.chunks)
                errors.extend(result.errors)
                indexed_files.append(relative)

        return CodeIndex(
            repository_commit=commit,
            chunks=chunks,
            indexed_files=sorted(indexed_files),
            errors=sorted(errors),
        )

    def is_current(self, repo_path: str | Path, index: CodeIndex) -> bool:
        root = Path(repo_path).expanduser().resolve(strict=True)
        return resolve_repository_commit(root) == index.repository_commit

    def _ignore_spec(self, root: Path) -> PathSpec:
        lines = list(DEFAULT_IGNORE_PATTERNS)
        gitignore = root / ".gitignore"
        if gitignore.is_file():
            lines.extend(gitignore.read_text(encoding="utf-8", errors="replace").splitlines())
        return PathSpec.from_lines("gitwildmatch", lines)

    def _ignored(
        self,
        spec: PathSpec,
        root: Path,
        path: Path,
        *,
        is_dir: bool = False,
    ) -> bool:
        relative = path.relative_to(root).as_posix()
        candidate = f"{relative}/" if is_dir else relative
        return spec.match_file(candidate)
