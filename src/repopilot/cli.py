"""RepoPilot CLI for task lifecycle, artifacts, benchmark, and demo."""

from __future__ import annotations

import argparse
import json
import shlex
import sys
import uuid
from pathlib import Path

from pydantic import ValidationError

from repopilot.core.schemas import TaskRequest
from repopilot.demo import DemoRepairExecutor
from repopilot.evaluation.executors import MockExecutor, SkippedExecutor
from repopilot.evaluation.runner import BenchmarkRunner
from repopilot.evaluation.task import load_task_bundle
from repopilot.service import (
    InMemoryTaskStore,
    SQLiteTaskStore,
    TaskService,
    UnavailableExecutor,
)


def _service(args, executor=None) -> TaskService:
    store = SQLiteTaskStore(args.store) if getattr(args, "store", None) else InMemoryTaskStore()
    return TaskService(executor=executor or UnavailableExecutor(), store=store)


def _parse_test_command(raw: str) -> list[str]:
    stripped = raw.strip()
    if stripped.startswith("["):
        value = json.loads(stripped)
        if not isinstance(value, list) or not value or not all(isinstance(item, str) and item for item in value):
            raise ValueError("test command JSON must be a non-empty string array")
        return value
    value = shlex.split(stripped)
    if not value:
        raise ValueError("test command must not be empty")
    return value


def _task_from_args(args) -> TaskRequest:
    values = {
        "task_id": args.task_id or f"task-{uuid.uuid4().hex[:12]}",
        "repo_path": args.repo,
        "issue": args.issue,
        "stack_trace": args.stack_trace,
        "test_command": _parse_test_command(args.test_command),
        "allowed_paths": args.allow_path or [],
        "forbidden_paths": args.forbid_path or [],
        "max_runtime_seconds": args.max_runtime_seconds,
        "max_llm_calls": args.max_llm_calls,
        "max_total_tokens": args.max_total_tokens,
        "max_tool_calls": args.max_tool_calls,
        "max_patch_retries": args.max_patch_retries,
    }
    return TaskRequest.model_validate(values)


def _print_json(value) -> None:
    print(json.dumps(value.model_dump(mode="json"), indent=2, sort_keys=True))


def _cmd_run(args) -> int:
    try:
        task = _task_from_args(args)
    except ValidationError as exc:
        print(json.dumps({"error": {"code": "validation_error", "errors": exc.errors()}}, indent=2), file=sys.stderr)
        return 2
    executor = DemoRepairExecutor() if args.executor == "demo" else UnavailableExecutor()
    service = _service(args, executor)
    record = service.submit(task)
    if args.wait:
        record = service.wait(task.task_id, timeout=args.wait_timeout)
    _print_json(record)
    return 0


def _cmd_status(args) -> int:
    service = _service(args)
    _print_json(service.get(args.task_id))
    return 0


def _cmd_trace(args) -> int:
    service = _service(args)
    print(json.dumps([event.model_dump(mode="json") for event in service.trace(args.task_id)], indent=2))
    return 0


def _cmd_artifacts(args) -> int:
    service = _service(args)
    _print_json(service.artifacts(args.task_id))
    return 0


def _cmd_approve(args) -> int:
    service = _service(args)
    record = service.approve(
        args.task_id,
        approved=args.approved,
        actor=args.actor,
        reason=args.reason,
    )
    _print_json(record)
    return 0


def _cmd_cancel(args) -> int:
    service = _service(args)
    _print_json(service.cancel(args.task_id, reason=args.reason))
    return 0


def _cmd_demo(args) -> int:
    bundle = load_task_bundle(args.task_dir)
    public = bundle.public
    task = TaskRequest(
        task_id=public.task_id,
        repo_path=str(bundle.repository_path),
        issue=public.issue,
        stack_trace=public.stack_trace,
        test_command=public.test_command,
    )
    report = DemoRepairExecutor().run(task)
    _print_json(report)
    return 0 if report.status == "succeeded" else 1


def _cmd_benchmark(args) -> int:
    executor = SkippedExecutor() if args.executor == "skipped" else MockExecutor()
    runner = BenchmarkRunner(executor, output_dir=Path(args.output))
    records, summary = runner.run(
        args.dataset,
        dataset_name=Path(args.dataset).name,
        experiment_group=args.group,
        task_ids=args.task_id,
        repeats=args.repeats,
        model_id=args.model_id,
        prompt_version=args.prompt_version,
    )
    print(json.dumps({"records": len(records), "summary": summary.model_dump(mode="json")}, indent=2))
    return 0


def _add_task_store(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--store", default="repopilot-tasks.db")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="repopilot", description="RepoPilot task CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="submit a repair task")
    _add_task_store(run)
    run.add_argument("--repo", required=True)
    run.add_argument("--issue", required=True)
    run.add_argument("--test-command", required=True, help="argument vector as a quoted command string or JSON array")
    run.add_argument("--task-id")
    run.add_argument("--stack-trace")
    run.add_argument("--allow-path", action="append")
    run.add_argument("--forbid-path", action="append")
    run.add_argument("--max-runtime-seconds", type=int, default=900)
    run.add_argument("--max-llm-calls", type=int, default=30)
    run.add_argument("--max-total-tokens", type=int, default=100000)
    run.add_argument("--max-tool-calls", type=int, default=100)
    run.add_argument("--max-patch-retries", type=int, default=3)
    run.add_argument("--executor", choices=("unavailable", "demo"), default="unavailable")
    run.add_argument("--wait", action="store_true")
    run.add_argument("--wait-timeout", type=float, default=30)
    run.set_defaults(func=_cmd_run)

    status = sub.add_parser("status", help="show task status")
    _add_task_store(status)
    status.add_argument("task_id")
    status.set_defaults(func=_cmd_status)

    trace = sub.add_parser("trace", help="show task trace")
    _add_task_store(trace)
    trace.add_argument("task_id")
    trace.set_defaults(func=_cmd_trace)

    artifacts = sub.add_parser("artifacts", help="show task artifacts")
    _add_task_store(artifacts)
    artifacts.add_argument("task_id")
    artifacts.set_defaults(func=_cmd_artifacts)

    approve = sub.add_parser("approve", help="record CLI patch approval")
    _add_task_store(approve)
    approve.add_argument("task_id")
    approve.add_argument("--approved", action="store_true")
    approve.add_argument("--actor", required=True)
    approve.add_argument("--reason", required=True)
    approve.set_defaults(func=_cmd_approve)

    cancel = sub.add_parser("cancel", help="cancel a task")
    _add_task_store(cancel)
    cancel.add_argument("task_id")
    cancel.add_argument("--reason", default="cancelled by operator")
    cancel.set_defaults(func=_cmd_cancel)

    demo = sub.add_parser("demo", help="run the honest Fake-LLM task-001 demo")
    demo.add_argument("--task-dir", default="benchmarks/tasks/task-001")
    demo.set_defaults(func=_cmd_demo)

    benchmark = sub.add_parser("benchmark", help="run benchmark infrastructure")
    benchmark_sub = benchmark.add_subparsers(dest="benchmark_command", required=True)
    benchmark_run = benchmark_sub.add_parser("run")
    benchmark_run.add_argument("--dataset", default="benchmarks/tasks")
    benchmark_run.add_argument("--output", default="benchmark-results")
    benchmark_run.add_argument("--group", default="full")
    benchmark_run.add_argument("--task-id", action="append")
    benchmark_run.add_argument("--repeats", type=int, default=1)
    benchmark_run.add_argument("--model-id", default="unspecified")
    benchmark_run.add_argument("--prompt-version", default="v1")
    benchmark_run.add_argument("--executor", choices=("skipped", "mock"), default="skipped")
    benchmark_run.set_defaults(func=_cmd_benchmark)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
