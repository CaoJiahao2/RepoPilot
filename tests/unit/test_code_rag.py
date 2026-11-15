import subprocess
from pathlib import Path

from repopilot.core.schemas import TaskRequest
from repopilot.retrieval.fusion import FusionConfig, fuse_hits
from repopilot.retrieval.index import RepositoryIndexer
from repopilot.retrieval.models import RetrievalHit
from repopilot.retrieval.research import CodeRAGResearchAgent
from repopilot.retrieval.retriever import CodeRAGRetriever
from repopilot.retrieval.sparse import BM25Index
from repopilot.retrieval.vector import VectorIndex


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=str(repo),
        shell=False,
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout.strip()


def _fixture_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "tests").mkdir(parents=True)
    (repo / ".venv").mkdir()
    (repo / "build").mkdir()
    (repo / ".gitignore").write_text(
        "ignored.py\n*.pem\n.venv/\nbuild/\n",
        encoding="utf-8",
    )
    (repo / "app.py").write_text(
        '''\
def parse_config(value):
    if not value:
        return {}
    return dict(value)


class ConfigLoader:
    def load(self, value):
        return parse_config(value)
''',
        encoding="utf-8",
    )
    (repo / "ignored.py").write_text("SHOULD_NOT_INDEX = True\n", encoding="utf-8")
    (repo / "secret.pem").write_text("private", encoding="utf-8")
    (repo / ".venv" / "lib.py").write_text("IGNORED = True\n", encoding="utf-8")
    (repo / "build" / "generated.py").write_text("IGNORED = True\n", encoding="utf-8")
    (repo / "broken.py").write_text("def broken(:\n", encoding="utf-8")
    _git(repo, "init")
    _git(repo, "add", ".gitignore", "app.py", "broken.py")
    _git(
        repo,
        "-c",
        "user.name=RepoPilot Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "-m",
        "RAG fixture",
    )
    return repo


class FakeEmbeddingProvider:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    def embed(self, texts):
        if self.fail:
            raise RuntimeError("embedding unavailable")
        return [[float(len(text)), 1.0] for text in texts]


def test_ast_chunking_records_symbols_lines_and_parent_symbols(tmp_path: Path) -> None:
    repo = _fixture_repo(tmp_path)
    index = RepositoryIndexer().index(repo)
    chunks = {chunk.chunk_id: chunk for chunk in index.chunks}

    parse_chunk = next(chunk for chunk in index.chunks if chunk.symbol == "parse_config")
    class_chunk = next(chunk for chunk in index.chunks if chunk.symbol == "ConfigLoader")
    method_chunk = next(chunk for chunk in index.chunks if chunk.symbol == "load")

    assert parse_chunk.symbol_type == "function"
    assert parse_chunk.start_line == 1
    assert parse_chunk.end_line == 4
    assert class_chunk.symbol_type == "class"
    assert method_chunk.symbol_type == "method"
    assert method_chunk.parent_symbol == "ConfigLoader"
    assert method_chunk.start_line < method_chunk.end_line
    assert chunks[parse_chunk.chunk_id].repository_commit == index.repository_commit


def test_index_respects_gitignore_defaults_binary_and_records_ast_fallback(tmp_path: Path) -> None:
    repo = _fixture_repo(tmp_path)
    index = RepositoryIndexer().index(repo)

    assert "app.py" in index.indexed_files
    assert "ignored.py" not in index.indexed_files
    assert "secret.pem" not in index.indexed_files
    assert not any(chunk.file_path.startswith(".venv/") for chunk in index.chunks)
    assert not any(chunk.file_path.startswith("build/") for chunk in index.chunks)
    assert any(chunk.file_path == "broken.py" and chunk.symbol_type == "text" for chunk in index.chunks)
    assert any("AST parse failed" in error for error in index.errors)


def test_exact_path_symbol_and_stack_line_retrieval(tmp_path: Path) -> None:
    repo = _fixture_repo(tmp_path)
    index = RepositoryIndexer().index(repo)
    retriever = CodeRAGRetriever(index)

    path_hits = retriever.search("anything", file_path="app.py", limit=10)
    symbol_hits = retriever.search("anything", symbol="parse_config", limit=10)
    class_hits = retriever.search("anything", symbol="ConfigLoader", limit=10)
    stack_hits = retriever.search(
        "anything",
        stack_trace='File "app.py", line 3, in <module>',
        limit=10,
    )

    assert path_hits and all("path" in hit.sources for hit in path_hits[:1])
    assert symbol_hits and any("symbol" in hit.sources for hit in symbol_hits)
    assert class_hits and any("symbol" in hit.sources for hit in class_hits)
    assert stack_hits and any("stack_line" in hit.sources for hit in stack_hits)
    evidence = retriever.to_evidence(symbol_hits[:1])
    assert evidence[0].file_path == "app.py"
    assert evidence[0].line_start <= 3 <= evidence[0].line_end
    assert evidence[0].repository_commit == index.repository_commit


def test_bm25_and_fusion_orders_relevant_chunks(tmp_path: Path) -> None:
    repo = _fixture_repo(tmp_path)
    index = RepositoryIndexer().index(repo)
    retriever = CodeRAGRetriever(index)

    bm25_hits = retriever.bm25.search("parse_config empty mapping", limit=3)
    assert bm25_hits
    assert any(chunk.chunk_id.endswith("function:parse_config") for chunk in bm25_hits)

    relevant = bm25_hits[0]
    groups = {
        "bm25": [relevant],
        "vector": [RetrievalHit(chunk_id=relevant.chunk_id, score=0.2, sources=["vector"])],
        "symbol": [RetrievalHit(chunk_id=relevant.chunk_id, score=1.0, sources=["symbol"])],
    }
    weighted = fuse_hits(groups, config=FusionConfig(mode="weighted", alpha=1, beta=1, gamma=1))
    rrf = fuse_hits(groups, config=FusionConfig(mode="rrf", rrf_k=1))

    assert weighted[0].chunk_id == relevant.chunk_id
    assert rrf[0].chunk_id == relevant.chunk_id
    assert set(weighted[0].sources) == {"bm25", "symbol", "vector"}


def test_vector_retrieval_degrades_when_embedding_is_unavailable(tmp_path: Path) -> None:
    repo = _fixture_repo(tmp_path)
    index = RepositoryIndexer().index(repo)
    chunks = index.chunks

    disabled = VectorIndex(chunks, provider=None)
    failed = VectorIndex(chunks, provider=FakeEmbeddingProvider(fail=True))
    retriever = CodeRAGRetriever(index)

    assert disabled.available is False
    assert failed.available is False
    assert retriever.search("parse_config", limit=3)

    working = CodeRAGRetriever(index, vector_provider=FakeEmbeddingProvider())
    vector_hits = working.vector.search("parse_config", limit=3)
    assert working.vector.available is True
    assert vector_hits
    assert vector_hits[0].sources == ["vector"]


def test_index_is_stale_after_new_git_commit(tmp_path: Path) -> None:
    repo = _fixture_repo(tmp_path)
    indexer = RepositoryIndexer()
    index = indexer.index(repo)
    assert indexer.is_current(repo, index) is True

    (repo / "app.py").write_text(
        (repo / "app.py").read_text(encoding="utf-8") + "\n# changed\n",
        encoding="utf-8",
    )
    _git(repo, "add", "app.py")
    _git(
        repo,
        "-c",
        "user.name=RepoPilot Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "-m",
        "change source",
    )

    assert indexer.is_current(repo, index) is False


def test_research_agent_converts_rag_hits_to_evidence_without_llm(tmp_path: Path) -> None:
    repo = _fixture_repo(tmp_path)
    index = RepositoryIndexer().index(repo)
    retriever = CodeRAGRetriever(index)
    task = TaskRequest(
        task_id="task-rag",
        repo_path=str(repo),
        issue="parse_config empty mapping returns the wrong value",
    )

    result = CodeRAGResearchAgent(retriever).run({"task": task})

    assert result.evidence
    assert result.evidence[0].file_path == "app.py"
    assert result.evidence[0].line_start >= 1
    assert result.evidence[0].retrieval_sources
    assert result.evidence[0].repository_commit == index.repository_commit


def test_embedding_provider_can_be_disabled_or_built_from_config() -> None:
    from unittest.mock import patch

    from repopilot.core.config import load_config
    from repopilot.retrieval.vector import (
        OpenAICompatibleEmbeddingClient,
        build_embedding_provider,
    )

    assert build_embedding_provider(load_config(env={})) is None

    config = load_config(
        env={
            "EMBEDDING_ENABLED": "true",
            "EMBEDDING_PROVIDER": "openai-compatible",
            "EMBEDDING_BASE_URL": "https://example.invalid/v1",
            "EMBEDDING_API_KEY": "sk-test-key",
            "EMBEDDING_MODEL": "embed-model",
        }
    )
    provider = build_embedding_provider(config)
    assert isinstance(provider, OpenAICompatibleEmbeddingClient)

    payload = {"data": [{"embedding": [0.1, 0.2]}, {"embedding": [0.3, 0.4]}]}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return __import__("json").dumps(payload).encode("utf-8")

    with patch("urllib.request.urlopen", return_value=Response()):
        assert provider.embed(["one", "two"]) == [[0.1, 0.2], [0.3, 0.4]]
