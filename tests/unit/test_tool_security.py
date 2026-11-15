import os
from pathlib import Path

from repopilot.tools.base import ToolContext, ToolGateway
from repopilot.tools.builtins import build_default_registry


def _gateway(tmp_path: Path, **context_overrides) -> ToolGateway:
    return ToolGateway(
        build_default_registry(),
        ToolContext(allowed_root=tmp_path, **context_overrides),
    )


def test_path_traversal_absolute_path_and_symlink_escape_are_blocked(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    outside = tmp_path / "outside"
    repo.mkdir()
    outside.mkdir()
    (outside / "secret.txt").write_text("secret", encoding="utf-8")
    os.symlink(outside / "secret.txt", repo / "escape.txt")

    gateway = _gateway(repo)

    traversal = gateway.execute("read_file", {"path": "../outside/secret.txt"})
    absolute = gateway.execute("read_file", {"path": str(outside / "secret.txt")})
    symlink = gateway.execute("read_file", {"path": "escape.txt"})

    for result in (traversal, absolute, symlink):
        assert result.success is False
        assert result.error_code == "sandbox_violation"
    assert "secret" not in traversal.output + absolute.output + symlink.output


def test_list_files_does_not_follow_or_expose_symlinks(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    outside = tmp_path / "outside"
    repo.mkdir()
    outside.mkdir()
    (repo / "normal.txt").write_text("ok", encoding="utf-8")
    (outside / "secret.txt").write_text("secret", encoding="utf-8")
    os.symlink(outside, repo / "outside_link")

    result = _gateway(repo).execute("list_files", {"path": "."})

    assert result.success is True
    assert "normal.txt" in result.output
    assert "outside_link" not in result.output
    assert "secret.txt" not in result.output


def test_read_file_rejects_large_and_binary_files(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "large.txt").write_text("x" * 100, encoding="utf-8")
    (repo / "binary.bin").write_bytes(b"abc\x00def")

    gateway = _gateway(repo, max_output_bytes=20, max_file_bytes=20)

    large = gateway.execute("read_file", {"path": "large.txt", "max_bytes": 20})
    binary = gateway.execute("read_file", {"path": "binary.bin", "max_bytes": 20})

    assert large.success is False
    assert large.error_code == "file_too_large"
    assert binary.success is False
    assert binary.error_code == "binary_file"


def test_invalid_tool_arguments_never_reach_handlers(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    gateway = _gateway(repo)

    result = gateway.execute("read_file", {"path": ""})

    assert result.success is False
    assert result.error_code == "invalid_input"
