from repopilot.core.graph import route_after_review
from repopilot.core.schemas import (
    BudgetState,
    ReviewResult,
    RetryCounters,
    TaskRequest,
)


def _state(**overrides):
    state = {
        "task": TaskRequest(task_id="task-001", repo_path="./repo", issue="valid issue"),
        "status": "running",
        "retry_counts": RetryCounters(),
        "budget": BudgetState(max_patch_retries=1, max_replans=1),
    }
    state.update(overrides)
    return state


def test_success_routes_to_report() -> None:
    state = _state(
        review_result=ReviewResult(
            approved=True,
            feedback="tests support the patch",
            next_action="finish",
        )
    )
    assert route_after_review(state) == "report"


def test_patch_failure_routes_to_coding_while_budget_remains() -> None:
    state = _state(
        review_result=ReviewResult(
            approved=False,
            failure_type="patch_error",
            feedback="patch did not apply",
            next_action="re_patch",
        )
    )
    assert route_after_review(state) == "coding"


def test_wrong_root_cause_routes_to_planner() -> None:
    state = _state(
        review_result=ReviewResult(
            approved=False,
            failure_type="wrong_root_cause",
            feedback="the hypothesis was falsified",
            next_action="re_diagnose",
        )
    )
    assert route_after_review(state) == "planner"


def test_terminal_failure_and_exhausted_budget_route_to_report() -> None:
    terminal = _state(
        review_result=ReviewResult(
            approved=False,
            failure_type="test_env_error",
            feedback="the environment is unavailable",
            next_action="fix_environment",
        )
    )
    exhausted = _state(
        status="budget_exceeded",
        review_result=ReviewResult(
            approved=False,
            failure_type="budget_exceeded",
            feedback="retry budget exhausted",
            next_action="re_patch",
        ),
    )

    assert route_after_review(terminal) == "report"
    assert route_after_review(exhausted) == "report"
