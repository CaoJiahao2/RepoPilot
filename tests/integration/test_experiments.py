import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from repopilot.evaluation.experiments import (
    ExperimentSuiteRunner,
    bootstrap_mean_interval,
    paired_comparison,
    standard_experiment_groups,
)
from repopilot.evaluation.executors import SkippedExecutor
from repopilot.evaluation.models import BenchmarkExecutionResult, BenchmarkRecord

ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "benchmarks" / "tasks"
NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _record(group: str, task_id: str, *, success: bool, status: str = "succeeded", duration: float = 1.0) -> BenchmarkRecord:
    return BenchmarkRecord(
        task_id=task_id,
        dataset="fixtures",
        experiment_group=group,
        run_index=0,
        model_id="model",
        prompt_version="v1",
        code_version="code",
        config={},
        budget={},
        started_at=NOW,
        finished_at=NOW,
        base_commit="commit",
        workspace_path=f"/tmp/{group}-{task_id}",
        result=BenchmarkExecutionResult(
            status=status,
            success=success,
            duration_seconds=duration,
            input_tokens=None if not success else 10,
            output_tokens=None if not success else 5,
            llm_calls=1 if success else 0,
        ),
        agent_input_task_id=task_id,
    )


def test_standard_groups_cover_required_comparison_and_ablations() -> None:
    groups = standard_experiment_groups(model_id="model", prompt_version="v2")
    names = [group.name for group in groups]

    assert names == [
        "A_single_agent_tools",
        "B_static_multi_agent",
        "C_static_memory",
        "D_static_reflection",
        "E_full",
        "abl_no_adaptive",
        "abl_no_memory",
        "abl_no_reflection",
    ]
    full = next(group for group in groups if group.name == "E_full")
    assert full.adaptive_planning and full.memory_enabled and full.reflection_enabled
    assert all(group.model_id == "model" and group.prompt_version == "v2" for group in groups)
    assert all(group.tool_set == groups[0].tool_set for group in groups)
    assert all(group.budget == groups[0].budget for group in groups)


def test_bootstrap_and_paired_comparison_preserve_unknown_results() -> None:
    interval = bootstrap_mean_interval([1.0, 0.0], resamples=100, seed=3)
    assert interval.sample_size == 2
    assert interval.lower is not None and interval.upper is not None

    records = {
        "left": [_record("left", "t1", success=True), _record("left", "t2", success=True)],
        "right": [_record("right", "t1", success=False), _record("right", "t2", success=True)],
    }
    comparison = paired_comparison(
        records,
        comparison="Left vs Right",
        left_group="left",
        right_group="right",
    )
    assert comparison.left_wins == 1
    assert comparison.right_wins == 0
    assert comparison.ties == 1
    assert comparison.success_rate_difference == 0.5

    skipped = {
        "left": [_record("left", "t1", success=False, status="skipped")],
        "right": [_record("right", "t1", success=False, status="skipped")],
    }
    unknown = paired_comparison(
        skipped,
        comparison="Unknown",
        left_group="left",
        right_group="right",
    )
    assert unknown.success_rate_difference is None
    assert unknown.bootstrap_95.sample_size == 0


def test_suite_creates_independent_group_outputs_and_unknown_summary(tmp_path: Path) -> None:
    report = ExperimentSuiteRunner(
        executor_factory=lambda config: SkippedExecutor(),
        output_dir=tmp_path / "experiments",
    ).run(DATASET, task_ids=["task-001", "task-002"])

    assert report.data_status == "not_verified"
    assert len(report.groups) == 8
    assert len(report.paired_comparisons) == 6
    assert all(summary.metrics.resolution_rate is None for summary in report.summaries.values())
    assert (tmp_path / "experiments" / "experiment_manifest.json").exists()
    assert (tmp_path / "experiments" / "suite_raw.jsonl").exists()
    assert (tmp_path / "experiments" / "suite_raw.csv").exists()
    assert (tmp_path / "experiments" / "experiment_table.csv").exists()
    assert (tmp_path / "experiments" / "paired_comparisons.json").exists()
    assert (tmp_path / "experiments" / "failure_analysis.json").exists()
    for group in report.groups:
        assert (tmp_path / "experiments" / group.name / "raw_results.jsonl").exists()


def test_plot_script_generates_reproducible_svg_charts(tmp_path: Path) -> None:
    results = tmp_path / "experiments"
    ExperimentSuiteRunner(
        executor_factory=lambda config: SkippedExecutor(),
        output_dir=results,
    ).run(DATASET, task_ids=["task-001"])

    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "plot_experiments.py"), str(results), str(tmp_path / "plots")],
        cwd=str(ROOT),
        shell=False,
        capture_output=True,
        text=True,
        check=True,
    )
    assert completed.returncode == 0
    assert (tmp_path / "plots" / "resolution_rate.svg").exists()
    assert (tmp_path / "plots" / "latency_p50.svg").exists()
    assert (tmp_path / "plots" / "failure_breakdown.svg").exists()
