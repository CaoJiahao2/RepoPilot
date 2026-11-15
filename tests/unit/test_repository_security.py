from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]


def test_gitignore_excludes_local_secrets_and_machine_config() -> None:
    patterns = set((ROOT / ".gitignore").read_text(encoding="utf-8").splitlines())

    assert ".env" in patterns
    assert ".env.*" in patterns
    assert "!.env.example" in patterns
    assert "*.local.yaml" in patterns
    assert "configs/local.yaml" in patterns
    assert "local.settings.*" in patterns


def test_tracked_config_examples_have_no_nonempty_credentials() -> None:
    sensitive_assignment = re.compile(
        r"^\s*(?:LLM_API_KEY|EMBEDDING_API_KEY|RERANKER_API_KEY|PASSWORD|TOKEN|SECRET)\s*=\s*\S+",
        re.IGNORECASE,
    )

    for relative_path in (".env.example", "configs/app.yaml"):
        content = (ROOT / relative_path).read_text(encoding="utf-8")
        assert sensitive_assignment.search(content) is None
