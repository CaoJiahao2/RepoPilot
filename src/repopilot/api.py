"""FastAPI surface for asynchronous task lifecycle operations."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from repopilot.core.errors import ApprovalError, CheckpointError
from repopilot.core.schemas import EndToEndReport, TaskRequest, TraceEvent
from repopilot.service import TaskArtifacts, TaskRecord, TaskService


class TaskSubmitResponse(BaseModel):
    task_id: str
    status: str
    message: str = "task submitted"


class TaskStatusResponse(BaseModel):
    task_id: str
    status: str
    created_at: str
    updated_at: str
    approval_status: str
    error_code: str | None = None
    error_message: str | None = None


class TraceResponse(BaseModel):
    task_id: str
    trace: list[TraceEvent]


class ArtifactsResponse(BaseModel):
    task_id: str
    patch_diff: str | None = None
    baseline_test_report: Any = None
    post_patch_test_report: Any = None
    review_result: Any = None
    report: EndToEndReport | None = None


class ApprovalCommand(BaseModel):
    approved: bool
    actor: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class CancelCommand(BaseModel):
    reason: str = Field(default="cancelled", min_length=1)


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    error: ErrorBody


def _status(record: TaskRecord) -> TaskStatusResponse:
    return TaskStatusResponse(
        task_id=record.task_id,
        status=record.status,
        created_at=record.created_at.isoformat(),
        updated_at=record.updated_at.isoformat(),
        approval_status=record.approval_status,
        error_code=record.error_code,
        error_message=record.error_message,
    )


def create_app(task_service: TaskService | None = None) -> FastAPI:
    service = task_service or TaskService()
    app = FastAPI(title="RepoPilot API", version="0.1.0")

    @app.exception_handler(KeyError)
    async def key_error_handler(request: Request, exc: KeyError) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={"error": {"code": "task_not_found", "message": "task was not found", "details": {"task_id": str(exc)}}},
        )

    @app.exception_handler(CheckpointError)
    async def checkpoint_error_handler(request: Request, exc: CheckpointError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"error": exc.to_dict()})

    @app.exception_handler(ApprovalError)
    async def approval_error_handler(request: Request, exc: ApprovalError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"error": exc.to_dict()})

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "validation_error",
                    "message": "request validation failed",
                    "details": {"errors": jsonable_encoder(exc.errors())},
                }
            },
        )

    @app.get("/api/v1/tasks", response_model=list[TaskStatusResponse])
    async def list_tasks() -> list[TaskStatusResponse]:
        return [_status(record) for record in service.list()]

    @app.post("/api/v1/tasks", response_model=TaskSubmitResponse)
    async def submit_task(task: TaskRequest) -> TaskSubmitResponse:
        record = service.submit(task)
        return TaskSubmitResponse(task_id=record.task_id, status=record.status)

    @app.get("/api/v1/tasks/{task_id}", response_model=TaskStatusResponse)
    async def get_task(task_id: str) -> TaskStatusResponse:
        return _status(service.get(task_id))

    @app.get("/api/v1/tasks/{task_id}/trace", response_model=TraceResponse)
    async def get_trace(task_id: str) -> TraceResponse:
        return TraceResponse(task_id=task_id, trace=service.trace(task_id))

    @app.get("/api/v1/tasks/{task_id}/artifacts", response_model=ArtifactsResponse)
    async def get_artifacts(task_id: str) -> ArtifactsResponse:
        artifacts = service.artifacts(task_id)
        return ArtifactsResponse(**artifacts.model_dump())

    @app.post("/api/v1/tasks/{task_id}/approve", response_model=TaskStatusResponse)
    async def approve_task(task_id: str, command: ApprovalCommand) -> TaskStatusResponse:
        record = service.approve(
            task_id,
            approved=command.approved,
            actor=command.actor,
            reason=command.reason,
        )
        return _status(record)

    @app.post("/api/v1/tasks/{task_id}/cancel", response_model=TaskStatusResponse)
    async def cancel_task(task_id: str, command: CancelCommand) -> TaskStatusResponse:
        return _status(service.cancel(task_id, reason=command.reason))

    frontend_dir = Path(__file__).resolve().parents[2] / "frontend"
    if frontend_dir.exists():
        app.mount("/assets", StaticFiles(directory=frontend_dir / "assets"), name="assets")

        @app.get("/", include_in_schema=False)
        async def index() -> FileResponse:
            return FileResponse(frontend_dir / "index.html")

    return app
