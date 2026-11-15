from datetime import datetime, timezone

import pytest

from repopilot.approval import (
    ApprovalDecision,
    ApprovalRequest,
    CLIApprovalGate,
    PatchExporter,
    SQLiteApprovalStore,
)
from repopilot.core.errors import ApprovalError

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _request() -> ApprovalRequest:
    return ApprovalRequest(
        request_id="approval-001",
        task_id="task-001",
        patch_summary="fix parser empty mapping",
        unified_diff="--- a/app.py\n+++ b/app.py\n",
        created_at=NOW,
    )


def test_cli_approval_records_approval_and_exports_patch(tmp_path) -> None:
    store = SQLiteApprovalStore(tmp_path / "approvals.db")
    gate = CLIApprovalGate(store, input_fn=lambda _: "approve")
    request = _request()

    decision = gate.request(request, actor="alice")
    exported = PatchExporter(store).export(request.request_id)

    assert decision.approved is True
    assert decision.actor == "alice"
    assert decision.reason
    assert exported.approved_by == "alice"
    assert exported.unified_diff == request.unified_diff
    assert store.get_decision(request.request_id).approved is True


def test_cli_rejection_blocks_patch_export(tmp_path) -> None:
    store = SQLiteApprovalStore(tmp_path / "approvals.db")
    request = _request()
    CLIApprovalGate(store, input_fn=lambda _: "reject").request(request, actor="bob")

    with pytest.raises(ApprovalError, match="rejected"):
        PatchExporter(store).export(request.request_id)

    decision = store.get_decision(request.request_id)
    assert decision is not None
    assert decision.approved is False
    assert decision.actor == "bob"


def test_export_requires_recorded_request_and_decision(tmp_path) -> None:
    store = SQLiteApprovalStore(tmp_path / "approvals.db")

    with pytest.raises(ApprovalError, match="requires an approval request"):
        PatchExporter(store).export("missing")
