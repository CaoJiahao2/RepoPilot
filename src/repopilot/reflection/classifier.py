"""Classify failures from real execution artifacts."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from repopilot.core.schemas import (
    Diagnosis,
    Evidence,
    FailureType,
    PatchResult,
    TestReport,
    ToolResult,
    TraceEvent,
)
from repopilot.reflection.models import ReflectionEvidence


class FailureClassification:
    def __init__(
        self,
        failure_type: FailureType,
        reason: str,
        evidence: list[ReflectionEvidence],
    ) -> None:
        self.failure_type = failure_type
        self.reason = reason
        self.evidence = evidence


class FailureClassifier:
    def classify(
        self,
        *,
        test_report: TestReport | None = None,
        baseline_test_report: TestReport | None = None,
        tool_results: Iterable[ToolResult] = (),
        patch_application: Mapping[str, Any] | None = None,
        diagnosis: Diagnosis | None = None,
        evidence: Iterable[Evidence] = (),
        trace: Iterable[TraceEvent] = (),
        status: str | None = None,
    ) -> FailureClassification:
        tool_results = list(tool_results)
        trace = list(trace)
        evidence = list(evidence)

        if status == "budget_exceeded" or (
            test_report is not None and test_report.failure_type == "budget_exceeded"
        ):
            return self._result(
                "budget_exceeded",
                "budget was exhausted before recovery completed",
                [self._evidence("budget", "budget", "execution budget exhausted")],
            )

        if patch_application:
            patch_applied = (
                patch_application.get("patch_applied")
                if isinstance(patch_application, Mapping)
                else getattr(patch_application, "patch_applied", True)
            )
            if patch_applied is False:
                error_message = (
                    patch_application.get("error_message")
                    if isinstance(patch_application, Mapping)
                    else getattr(patch_application, "error_message", None)
                )
                error_code = (
                    patch_application.get("error_code")
                    if isinstance(patch_application, Mapping)
                    else getattr(patch_application, "error_code", None)
                )
                return self._result(
                    "patch_error",
                    str(error_message or "patch failed"),
                    [
                        self._evidence(
                            "diff",
                            "patch_application",
                            str(error_code or "patch_error"),
                        )
                    ],
                )

        failed_tools = [result for result in tool_results if not result.success]
        if failed_tools:
            result = failed_tools[-1]
            failure_type: FailureType = (
                "test_env_error"
                if result.error_code in {"dependency_error", "collection_error", "timeout"}
                else "tool_failure"
            )
            return self._result(
                failure_type,
                result.error_message or "tool execution failed",
                [
                    self._evidence(
                        "tool_result",
                        result.tool_name,
                        result.error_code or "tool_failure",
                        failure_type,
                    )
                ],
            )

        if test_report is not None:
            if test_report.status in {"dependency_error", "collection_error", "timeout"}:
                return self._result(
                    "test_env_error",
                    f"test environment failed with status {test_report.status}",
                    [self._evidence("test_report", "post_patch_test", test_report.status)],
                )
            if test_report.status == "execution_error":
                return self._result(
                    "tool_failure",
                    "test execution failed unexpectedly",
                    [self._evidence("test_report", "post_patch_test", "execution_error", "tool_failure")],
                )
            if test_report.status == "assertion_failed":
                if baseline_test_report is not None and baseline_test_report.status == "passed":
                    return self._result(
                        "regression",
                        "baseline passed but post-patch tests failed",
                        [
                            self._evidence(
                                "test_report",
                                "baseline_test",
                                baseline_test_report.status,
                                "regression",
                            ),
                            self._evidence(
                                "test_report",
                                "post_patch_test",
                                test_report.status,
                                "regression",
                            ),
                        ],
                    )
                return self._result(
                    "wrong_root_cause",
                    "target test remains failing after the proposed fix",
                    [
                        self._evidence(
                            "test_report",
                            "post_patch_test",
                            test_report.status,
                            "wrong_root_cause",
                        )
                    ],
                )

        if diagnosis is not None and not evidence:
            return self._result(
                "missing_context",
                "diagnosis has no current source evidence",
                [self._evidence("diagnosis", diagnosis.root_cause, "no current evidence", "missing_context")],
            )

        failed_trace = [event for event in trace if event.status == "failed"]
        if failed_trace:
            event = failed_trace[-1]
            failure_type = "patch_error" if event.action in {"apply_patch", "validate_diff"} else "tool_failure"
            return self._result(
                failure_type,
                event.message or "execution trace recorded a failure",
                [self._evidence("trace", event.event_id, event.action, failure_type)],
            )

        return self._result(
            "missing_context",
            "execution did not contain enough evidence to explain the failure",
            [self._evidence("trace", "execution", "insufficient execution evidence", "missing_context")],
        )

    @staticmethod
    def _evidence(
        source_type: str,
        reference: str,
        summary: str,
        failure_type: FailureType | None = None,
    ) -> ReflectionEvidence:
        return ReflectionEvidence(
            source_type=source_type,  # type: ignore[arg-type]
            reference=reference,
            summary=summary,
            failure_type=failure_type,
        )

    @staticmethod
    def _result(
        failure_type: FailureType,
        reason: str,
        evidence: list[ReflectionEvidence],
    ) -> FailureClassification:
        return FailureClassification(failure_type, reason, evidence)
