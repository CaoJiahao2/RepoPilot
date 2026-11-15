"""Benchmark runner preserving raw per-task records and artifacts."""

from __future__ import annotations

import csv
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from repopilot.evaluation.executors import BenchmarkExecutor
from repopilot.evaluation.metrics import summarize
from repopilot.evaluation.models import (
    BenchmarkExecutionResult,
    BenchmarkRecord,
    BenchmarkSummary,
)
from repopilot.evaluation.task import TaskBundle, load_dataset
from repopilot.sandbox.worktree import GitWorktreeManager


def resolve_code_version(path: str | Path) -> str:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(path),
            shell=False,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unversioned"
    return completed.stdout.strip() or "unversioned"


class BenchmarkRunner:
    def __init__(
        self,
        executor: BenchmarkExecutor,
        *,
        output_dir: str | Path,
        worktree_manager: GitWorktreeManager | None = None,
    ) -> None:
        self.executor = executor
        self.output_dir = Path(output_dir)
        self.worktree_manager = worktree_manager or GitWorktreeManager()

    def run(
        self,
        dataset_dir: str | Path,
        *,
        dataset_name: str = "default",
        experiment_group: str = "full",
        task_ids: list[str] | None = None,
        repeats: int = 1,
        model_id: str = "unspecified",
        prompt_version: str = "v1",
        code_version: str | None = None,
        config: Mapping[str, str | int | float | bool | None] | None = None,
        budget: Mapping[str, int | float] | None = None,
    ) -> tuple[list[BenchmarkRecord], BenchmarkSummary]:
        if repeats < 1:
            raise ValueError("repeats must be positive")
        bundles = load_dataset(dataset_dir, task_ids)
        code_version = code_version or resolve_code_version(Path(dataset_dir))
        config_values = dict(config or {})
        budget_values = dict(budget or {})
        records: list[BenchmarkRecord] = []

        for bundle in bundles:
            for run_index in range(repeats):
                records.append(
                    self._run_one(
                        bundle,
                        run_index=run_index,
                        dataset_name=dataset_name,
                        experiment_group=experiment_group,
                        model_id=model_id,
                        prompt_version=prompt_version,
                        code_version=code_version,
                        config=config_values,
                        budget=budget_values,
                    )
                )

        self._write_raw_jsonl(records)
        self._write_raw_csv(records)
        summary = summarize(records, dataset=dataset_name, experiment_group=experiment_group)
        self._write_summary(summary)
        return records, summary

    def _run_one(
        self,
        bundle: TaskBundle,
        *,
        run_index: int,
        dataset_name: str,
        experiment_group: str,
        model_id: str,
        prompt_version: str,
        code_version: str,
        config: dict[str, str | int | float | bool | None],
        budget: dict[str, int | float],
    ) -> BenchmarkRecord:
        run_root = (
            self.output_dir
            / "runs"
            / bundle.public.task_id
            / f"{experiment_group}-{run_index}"
        )
        run_root.mkdir(parents=True, exist_ok=True)
        worktree_path = run_root / "worktree"
        started_at = datetime.now(timezone.utc)
        session = None
        result: BenchmarkExecutionResult
        try:
            session = self.worktree_manager.create(
                bundle.repository_path,
                worktree_path,
                base_ref=bundle.public.base_commit,
            )
            result = self.executor.run(
                bundle.agent_input(),
                workspace_path=session.path,
                run_index=run_index,
            )
        except Exception as exc:
            result = BenchmarkExecutionResult(
                status="failed",
                success=False,
                failure_stage="benchmark_runner",
                failure_type="runner_error",
                logs=f"{type(exc).__name__}: {exc}",
                execution_mode="infrastructure",
            )
        finally:
            if session is not None:
                try:
                    self.worktree_manager.cleanup(session)
                except Exception:
                    pass

        finished_at = datetime.now(timezone.utc)
        record = BenchmarkRecord(
            task_id=bundle.public.task_id,
            dataset=dataset_name,
            experiment_group=experiment_group,
            run_index=run_index,
            model_id=model_id,
            prompt_version=prompt_version,
            code_version=code_version,
            config=config,
            budget=budget,
            started_at=started_at,
            finished_at=finished_at,
            base_commit=bundle.public.base_commit,
            workspace_path=str(worktree_path),
            result=result,
            agent_input_task_id=bundle.public.task_id,
            gold_patch_available_to_agent=False,
            verification_command_available_to_agent=False,
        )
        self._write_run_artifacts(run_root, record)
        return record

    @staticmethod
    def _write_run_artifacts(run_root: Path, record: BenchmarkRecord) -> None:
        (run_root / "record.json").write_text(
            record.model_dump_json(indent=2) + "\n",
            encoding="utf-8",
        )
        if record.result.patch_diff:
            (run_root / "patch.diff").write_text(record.result.patch_diff, encoding="utf-8")
        if record.result.status == "failed":
            (run_root / "failure.log").write_text(record.result.logs or "failure without logs", encoding="utf-8")

    def _write_raw_jsonl(self, records: list[BenchmarkRecord]) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        with (self.output_dir / "raw_results.jsonl").open("w", encoding="utf-8") as handle:
            for record in records:
                handle.write(record.model_dump_json() + "\n")

    def _write_raw_csv(self, records: list[BenchmarkRecord]) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        fieldnames = [
            "task_id",
            "dataset",
            "experiment_group",
            "run_index",
            "model_id",
            "prompt_version",
            "code_version",
            "base_commit",
            "started_at",
            "finished_at",
            "status",
            "success",
            "patch_passed",
            "regression_detected",
            "root_cause_correct",
            "failure_stage",
            "failure_type",
            "duration_seconds",
            "input_tokens",
            "output_tokens",
            "llm_calls",
            "estimated_cost_usd",
            "result_json",
        ]
        with (self.output_dir / "raw_results.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
            writer.writeheader()
            for record in records:
                row = record.model_dump(mode="json")
                result = row.pop("result")
                row.update(
                    {
                        "status": result["status"],
                        "success": result["success"],
                        "patch_passed": result["patch_passed"],
                        "regression_detected": result["regression_detected"],
                        "root_cause_correct": result["root_cause_correct"],
                        "failure_stage": result["failure_stage"],
                        "failure_type": result["failure_type"],
                        "duration_seconds": result["duration_seconds"],
                        "input_tokens": result["input_tokens"],
                        "output_tokens": result["output_tokens"],
                        "llm_calls": result["llm_calls"],
                        "estimated_cost_usd": result["estimated_cost_usd"],
                        "result_json": json.dumps(result, sort_keys=True),
                    }
                )
                writer.writerow({key: row.get(key) for key in fieldnames})

    def _write_summary(self, summary: BenchmarkSummary) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        (self.output_dir / "summary.json").write_text(
            summary.model_dump_json(indent=2) + "\n",
            encoding="utf-8",
        )
        metrics = summary.metrics.model_dump(mode="json")
        with (self.output_dir / "summary.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["metric", "value"], lineterminator="\n")
            writer.writeheader()
            for key, value in metrics.items():
                writer.writerow({"metric": key, "value": value})
