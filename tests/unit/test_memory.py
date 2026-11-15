from datetime import datetime, timezone

import pytest

from repopilot.core.errors import MemoryWriteError
from repopilot.core.schemas import MemoryHit
from repopilot.memory.retriever import MemoryRetriever
from repopilot.memory.schemas import Experience
from repopilot.memory.store import SQLiteExperienceStore


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def experience(
    *,
    experience_id: str,
    issue: str,
    outcome: str,
    source_task_id: str = "task-001",
    target: bool = True,
    regression: bool = True,
    patch_summary: str = "return an empty mapping",
) -> Experience:
    return Experience(
        experience_id=experience_id,
        source_task_id=source_task_id,
        issue_summary=issue,
        error_type="assertion_failure",
        repository_fingerprint="fixture@commit",
        affected_symbols=["parse_config"],
        root_cause=f"root cause for {issue}",
        solution_summary="normalize empty mappings",
        patch_summary=patch_summary,
        validation_summary="target and regression tests passed",
        outcome=outcome,
        target_tests_passed=target,
        regression_tests_passed=regression,
        applicability_conditions=["Python function handling empty mappings"],
        embedding_text=f"{issue} normalize empty mappings",
        created_at=NOW,
    )


def test_verified_success_requires_target_and_regression_tests(tmp_path) -> None:
    store = SQLiteExperienceStore(tmp_path / "memory.db")
    valid = experience(experience_id="exp-ok", issue="parse_config empty mapping", outcome="verified_success")
    invalid = valid.model_copy(update={"target_tests_passed": False})

    store.save(valid)
    with pytest.raises(MemoryWriteError, match="target and regression"):
        store.save(invalid.model_copy(update={"experience_id": "exp-bad"}))


def test_failed_experience_is_saved_but_not_presented_as_success(tmp_path) -> None:
    store = SQLiteExperienceStore(tmp_path / "memory.db")
    store.save(
        experience(
            experience_id="exp-failed",
            issue="parse_config empty mapping",
            outcome="failed",
            target=False,
            regression=False,
        )
    )

    verified_only = store.search("parse_config empty mapping")
    include_failed = store.search("parse_config empty mapping", include_failed=True)

    assert verified_only == []
    assert include_failed
    assert include_failed[0].outcome == "failed"


def test_keyword_search_ranks_exact_issue_and_supports_cross_task_recall(tmp_path) -> None:
    store = SQLiteExperienceStore(tmp_path / "memory.db")
    store.save(
        experience(
            experience_id="exp-specific",
            issue="parse_config empty mapping",
            outcome="verified_success",
            source_task_id="old-task",
        )
    )
    store.save(
        experience(
            experience_id="exp-generic",
            issue="generic parser behavior",
            outcome="verified_success",
            source_task_id="another-task",
        )
    )

    hits = store.search("parse_config empty mapping")

    assert [hit.memory_id for hit in hits] == ["exp-specific", "exp-generic"]
    assert hits[0].score >= hits[1].score


def test_memory_retrieval_records_id_score_and_planner_adoption(tmp_path) -> None:
    store = SQLiteExperienceStore(tmp_path / "memory.db")
    store.save(
        experience(
            experience_id="exp-audit",
            issue="parse_config empty mapping",
            outcome="verified_success",
            source_task_id="old-task",
        )
    )
    retriever = MemoryRetriever(store)

    hits = retriever.retrieve(
        "parse_config empty mapping",
        source_task_id="new-task",
        planner_adopted=True,
    )

    assert isinstance(hits[0], MemoryHit)
    assert hits[0].experience_id == "exp-audit"
    assert hits[0].verified is True
    records = store.list_retrievals(memory_id="exp-audit")
    assert records[0].memory_id == "exp-audit"
    assert records[0].retrieval_score == hits[0].retrieval_score
    assert records[0].planner_adopted is True
    assert records[0].source_task_id == "new-task"


def test_memory_rejects_gold_patch_hidden_answers_and_secrets(tmp_path) -> None:
    store = SQLiteExperienceStore(tmp_path / "memory.db")

    for patch_summary in (
        "diff --git a/app.py b/app.py",
        "gold patch says return {}",
        "hidden test expects success",
        "api_key=sk-secret-value",
    ):
        with pytest.raises(ValueError):
            experience(
                experience_id=f"exp-{abs(hash(patch_summary))}",
                issue="safe issue",
                outcome="failed",
                target=False,
                regression=False,
                patch_summary=patch_summary,
            )

    assert store.search("safe issue") == []
