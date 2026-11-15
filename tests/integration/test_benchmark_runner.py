import csv
import json
import subprocess
import sys
from pathlib import Path

from repopilot.evaluation.metrics import calculate_metrics, summarize
from repopilot.evaluation.models import BenchmarkExecutionResult
from repopilot.evaluation.runner import BenchmarkRunner
from repopilot.evaluation.task import load_dataset, load_task_bundle

ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "benchmarks" / "tasks"


class RecordingExecutor:
    def __init__(self, outcome_by_task: dict[str, BenchmarkExecutionResult]) -> None:
        self.outcome_by_task = outcome_by_task
        self.calls = []

    def run(self, task, *, workspace_path, run_index):
        workspace = Path(workspace_path)
        self.calls.append((task.task_id, workspace, run_index, task, (workspace / "app.py").exists()))
        return self.outcome_by_task[task.task_id]


def test_task_format_isolates_gold_patch_and_verification_command() -> None:
    bundle = load_task_bundle(DATASET / "task-001")
    agent_task = bundle.agent_input()
    dumped = agent_task.model_dump()

    assert "gold_patch" not in dumped
    assert "verification_command" not in dumped
    assert dumped["task_id"] == "task-001"
    assert bundle.private.gold_patch
    assert bundle.private.verification_command
    assert bundle.private.expected_root_cause


def test_runner_uses_clean_base_commit_and_independent_workspaces(tmp_path: Path) -> None:
    result = BenchmarkExecutionResult(
        status="succeeded",
        success=True,
        patch_passed=True,
        root_cause_correct=True,
        duration_seconds=1.0,
        input_tokens=10,
        output_tokens=5,
        llm_calls=2,
    )
    executor = RecordingExecutor({"task-001": result, "task-002": result})
    runner = BenchmarkRunner(executor, output_dir=tmp_path / "results")

    records, summary = runner.run(
        DATASET,
        dataset_name="fixtures",
        experiment_group="realistic",
        task_ids=["task-001", "task-002"],
        repeats=2,
        model_id="fake-model",
        prompt_version="v1",
    )

    assert len(records) == 4
    assert len(executor.calls) == 4
    assert len({path for _, path, _, _, _ in executor.calls}) == 4
    assert all(app_exists for _, _, _, _, app_exists in executor.calls)
    assert all(record.base_commit == record.result.status or record.base_commit for record in records)
    assert summary.task_count == 2
    assert summary.run_count == 4
    assert summary.success_count == 4
    assert (tmp_path / "results" / "raw_results.jsonl").exists()
    assert (tmp_path / "results" / "raw_results.csv").exists()
    assert (tmp_path / "results" / "summary.json").exists()
    assert (tmp_path / "results" / "summary.csv").exists()


def test_failed_task_is_not_successful_and_keeps_logs_and_diff(tmp_path: Path) -> None:
    failed = BenchmarkExecutionResult(
        status="failed",
        success=False,
        patch_passed=False,
        regression_detected=True,
        root_cause_correct=False,
        patch_diff="--- a/app.py\n+++ b/app.py\n",
        logs="verification failed",
        failure_type="wrong_root_cause",
        duration_seconds=2.0,
    )
    executor = RecordingExecutor({"task-001": failed})
    runner = BenchmarkRunner(executor, output_dir=tmp_path / "results")

    records, summary = runner.run(
        DATASET,
        task_ids=["task-001"],
        experiment_group="failure",
    )

    assert records[0].result.success is False
    assert summary.success_count == 0
    assert summary.failed_count == 1
    run_dir = tmp_path / "results" / "runs" / "task-001" / "failure-0"
    assert (run_dir / "failure.log").read_text(encoding="utf-8") == "verification failed"
    assert (run_dir / "patch.diff").exists()


def test_metrics_keep_unknown_token_and_cost_values() -> None:
    success = BenchmarkExecutionResult(
        status="succeeded",
        success=True,
        patch_passed=True,
        root_cause_correct=True,
        tool_calls=4,
        tool_successes=3,
        replans=1,
        reflection_attempts=2,
        reflection_recoveries=1,
        memory_retrievals=2,
        memory_hits=1,
        duration_seconds=1.0,
    )
    unknown = BenchmarkExecutionResult(
        status="skipped",
        success=False,
        duration_seconds=3.0,
        execution_mode="skipped",
    )
    records = [
        record
        for record in [
            __import__("repopilot.evaluation.models", fromlist=["BenchmarkRecord"]).BenchmarkRecord(
                task_id="task-001",
                dataset="fixtures",
                experiment_group="metrics",
                run_index=0,
                model_id="m",
                prompt_version="v1",
                code_version="c",
                config={},
                budget={},
                started_at=success.duration_seconds and __import__("datetime").datetime.now(__import__("datetime").timezone.utc),
                finished_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
                base_commit="commit",
                workspace_path="/tmp/a",
                result=success,
                agent_input_task_id="task-001",
            ),
            __import__("repopilot.evaluation.models", fromlist=["BenchmarkRecord"]).BenchmarkRecord(
                task_id="task-002",
                dataset="fixtures",
                experiment_group="metrics",
                run_index=0,
                model_id="m",
                prompt_version="v1",
                code_version="c",
                config={},
                budget={},
                started_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
                finished_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
                base_commit="commit",
                workspace_path="/tmp/b",
                result=unknown,
                agent_input_task_id="task-002",
            ),
        ]
    ]
    metrics = calculate_metrics(records)

    assert metrics.resolution_rate == 1.0
    assert metrics.tool_success_rate == 0.75
    assert metrics.replanning_rate == 1.0
    assert metrics.reflection_recovery_rate == 0.5
    assert metrics.memory_retrieval_hit_rate == 0.5
    assert metrics.total_input_tokens is None
    assert metrics.total_estimated_cost_usd is None
    assert metrics.unknown_token_or_cost_tasks == 2


def test_one_command_cli_writes_benchmark_outputs(tmp_path: Path) -> None:
    output = tmp_path / "cli-results"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "repopilot.evaluation.cli",
            "--dataset",
            str(DATASET),
            "--output",
            str(output),
            "--task-id",
            "task-001",
            "--group",
            "infrastructure-smoke",
            "--executor",
            "skipped",
        ],
        cwd=str(ROOT),
        shell=False,
        capture_output=True,
        text=True,
        check=True,
    )

    assert "records=1" in completed.stdout
    assert (output / "raw_results.jsonl").exists()
    assert (output / "raw_results.csv").exists()
    assert (output / "summary.json").exists()
    assert (output / "summary.csv").exists()
    payload = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    assert payload["skipped_count"] == 1
