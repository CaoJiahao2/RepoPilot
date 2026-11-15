"""Experiment groups, paired comparisons, bootstrap intervals, and suite artifacts."""

from __future__ import annotations

import csv
import json
import random
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from pydantic import Field

from repopilot.core.schemas import RepoPilotModel
from repopilot.evaluation.executors import BenchmarkExecutor
from repopilot.evaluation.metrics import calculate_metrics, summarize
from repopilot.evaluation.models import BenchmarkRecord, BenchmarkSummary
from repopilot.evaluation.runner import BenchmarkRunner
from repopilot.evaluation.task import load_dataset


class ExperimentConfig(RepoPilotModel):
    name: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    label: str = Field(min_length=1)
    description: str = Field(min_length=1)
    multi_agent: bool
    memory_enabled: bool
    reflection_enabled: bool
    adaptive_planning: bool
    model_id: str
    prompt_version: str
    generation_params: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    tool_set: list[str] = Field(default_factory=list)
    budget: dict[str, int | float] = Field(default_factory=dict)
    notes: str = ""


class BootstrapInterval(RepoPilotModel):
    lower: float | None = None
    upper: float | None = None
    sample_size: int = Field(default=0, ge=0)
    resamples: int = Field(default=0, ge=0)


class PairedComparison(RepoPilotModel):
    comparison: str
    left_group: str
    right_group: str
    paired_tasks: int = Field(ge=0)
    left_wins: int = Field(ge=0)
    right_wins: int = Field(ge=0)
    ties: int = Field(ge=0)
    left_success_rate: float | None = Field(default=None, ge=0, le=1)
    right_success_rate: float | None = Field(default=None, ge=0, le=1)
    success_rate_difference: float | None = None
    bootstrap_95: BootstrapInterval
    interpretation: str


class FailureBreakdown(RepoPilotModel):
    group: str
    failure_stage: str | None
    failure_type: str | None
    count: int = Field(ge=0)


class ExperimentSuiteReport(RepoPilotModel):
    dataset: str
    created_at: datetime
    groups: list[ExperimentConfig]
    summaries: dict[str, BenchmarkSummary]
    paired_comparisons: list[PairedComparison]
    failure_breakdown: list[FailureBreakdown]
    data_status: str
    limitations: list[str]


def standard_experiment_groups(
    *,
    model_id: str = "unspecified",
    prompt_version: str = "v1",
) -> list[ExperimentConfig]:
    common_tools = ["list_files", "search_code", "read_file", "git_status", "git_diff"]
    budget = {
        "max_llm_calls": 30,
        "max_total_tokens": 100000,
        "max_tool_calls": 100,
        "max_runtime_seconds": 900,
    }
    groups = [
        ExperimentConfig(
            name="A_single_agent_tools",
            label="A. Single Agent + Tools",
            description="One agent with the common tool set.",
            multi_agent=False,
            memory_enabled=False,
            reflection_enabled=False,
            adaptive_planning=False,
            model_id=model_id,
            prompt_version=prompt_version,
            tool_set=common_tools,
            budget=budget,
        ),
        ExperimentConfig(
            name="B_static_multi_agent",
            label="B. Static Multi-Agent",
            description="Fixed multi-agent workflow without memory or reflection.",
            multi_agent=True,
            memory_enabled=False,
            reflection_enabled=False,
            adaptive_planning=False,
            model_id=model_id,
            prompt_version=prompt_version,
            tool_set=common_tools,
            budget=budget,
        ),
        ExperimentConfig(
            name="C_static_memory",
            label="C. Static Multi-Agent + Memory",
            description="Static multi-agent workflow with cross-task experience memory.",
            multi_agent=True,
            memory_enabled=True,
            reflection_enabled=False,
            adaptive_planning=False,
            model_id=model_id,
            prompt_version=prompt_version,
            tool_set=common_tools,
            budget=budget,
        ),
        ExperimentConfig(
            name="D_static_reflection",
            label="D. Static Multi-Agent + Reflection",
            description="Static multi-agent workflow with execution-aware reflection.",
            multi_agent=True,
            memory_enabled=False,
            reflection_enabled=True,
            adaptive_planning=False,
            model_id=model_id,
            prompt_version=prompt_version,
            tool_set=common_tools,
            budget=budget,
        ),
        ExperimentConfig(
            name="E_full",
            label="E. Full RepoPilot",
            description="Adaptive planning with memory and reflection.",
            multi_agent=True,
            memory_enabled=True,
            reflection_enabled=True,
            adaptive_planning=True,
            model_id=model_id,
            prompt_version=prompt_version,
            tool_set=common_tools,
            budget=budget,
        ),
        ExperimentConfig(
            name="abl_no_adaptive",
            label="Full vs No Adaptive Planning",
            description="Full system with adaptive planning disabled.",
            multi_agent=True,
            memory_enabled=True,
            reflection_enabled=True,
            adaptive_planning=False,
            model_id=model_id,
            prompt_version=prompt_version,
            tool_set=common_tools,
            budget=budget,
        ),
        ExperimentConfig(
            name="abl_no_memory",
            label="Full vs No Memory",
            description="Full system with experience memory disabled.",
            multi_agent=True,
            memory_enabled=False,
            reflection_enabled=True,
            adaptive_planning=True,
            model_id=model_id,
            prompt_version=prompt_version,
            tool_set=common_tools,
            budget=budget,
        ),
        ExperimentConfig(
            name="abl_no_reflection",
            label="Full vs No Reflection",
            description="Full system with reflection disabled.",
            multi_agent=True,
            memory_enabled=True,
            reflection_enabled=False,
            adaptive_planning=True,
            model_id=model_id,
            prompt_version=prompt_version,
            tool_set=common_tools,
            budget=budget,
        ),
    ]
    return groups


def bootstrap_mean_interval(
    values: Iterable[float],
    *,
    resamples: int = 2000,
    seed: int = 17,
) -> BootstrapInterval:
    values = list(values)
    if not values:
        return BootstrapInterval(sample_size=0, resamples=resamples)
    rng = random.Random(seed)
    means = []
    for _ in range(resamples):
        sample = [values[rng.randrange(len(values))] for _ in values]
        means.append(sum(sample) / len(sample))
    means.sort()
    lower = means[int(0.025 * (len(means) - 1))]
    upper = means[int(0.975 * (len(means) - 1))]
    return BootstrapInterval(
        lower=lower,
        upper=upper,
        sample_size=len(values),
        resamples=resamples,
    )


def paired_comparison(
    records: Mapping[str, list[BenchmarkRecord]],
    *,
    comparison: str,
    left_group: str,
    right_group: str,
    seed: int = 17,
) -> PairedComparison:
    left = {
        (record.task_id, record.run_index): record
        for record in records.get(left_group, [])
    }
    right = {
        (record.task_id, record.run_index): record
        for record in records.get(right_group, [])
    }
    paired_keys = sorted(set(left) & set(right))
    differences: list[float] = []
    left_wins = right_wins = ties = 0
    left_known = right_known = 0
    left_successes = right_successes = 0
    for key in paired_keys:
        left_result = left[key].result
        right_result = right[key].result
        if left_result.status != "skipped":
            left_known += 1
            left_successes += int(left_result.success)
        if right_result.status != "skipped":
            right_known += 1
            right_successes += int(right_result.success)
        if left_result.status == "skipped" or right_result.status == "skipped":
            continue
        delta = float(left_result.success) - float(right_result.success)
        differences.append(delta)
        if delta > 0:
            left_wins += 1
        elif delta < 0:
            right_wins += 1
        else:
            ties += 1

    left_rate = left_successes / left_known if left_known else None
    right_rate = right_successes / right_known if right_known else None
    difference = left_rate - right_rate if left_rate is not None and right_rate is not None else None
    interval = bootstrap_mean_interval(differences, seed=seed)
    if not differences:
        interpretation = "unknown: no paired non-skipped results"
    elif difference is None:
        interpretation = "unknown: paired result rates are incomplete"
    else:
        interpretation = (
            f"left group differs by {difference:+.3f} on paired known tasks; "
            "interpret with small-sample uncertainty"
        )
    return PairedComparison(
        comparison=comparison,
        left_group=left_group,
        right_group=right_group,
        paired_tasks=len(paired_keys),
        left_wins=left_wins,
        right_wins=right_wins,
        ties=ties,
        left_success_rate=left_rate,
        right_success_rate=right_rate,
        success_rate_difference=difference,
        bootstrap_95=interval,
        interpretation=interpretation,
    )


def failure_breakdown(records: Iterable[BenchmarkRecord]) -> list[FailureBreakdown]:
    counter: Counter[tuple[str, str | None, str | None]] = Counter()
    for record in records:
        if record.result.status == "failed":
            counter[
                (
                    record.experiment_group,
                    record.result.failure_stage,
                    record.result.failure_type,
                )
            ] += 1
    return [
        FailureBreakdown(
            group=group,
            failure_stage=stage,
            failure_type=failure_type,
            count=count,
        )
        for (group, stage, failure_type), count in sorted(counter.items())
    ]


class ExperimentSuiteRunner:
    def __init__(
        self,
        *,
        executor_factory: Callable[[ExperimentConfig], BenchmarkExecutor],
        output_dir: str | Path,
    ) -> None:
        self.executor_factory = executor_factory
        self.output_dir = Path(output_dir)

    def run(
        self,
        dataset_dir: str | Path,
        *,
        groups: list[ExperimentConfig] | None = None,
        task_ids: list[str] | None = None,
        repeats: int = 1,
    ) -> ExperimentSuiteReport:
        groups = groups or standard_experiment_groups()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        records_by_group: dict[str, list[BenchmarkRecord]] = {}
        summaries: dict[str, BenchmarkSummary] = {}

        for group in groups:
            group_dir = self.output_dir / group.name
            runner = BenchmarkRunner(
                self.executor_factory(group),
                output_dir=group_dir,
            )
            records, summary = runner.run(
                dataset_dir,
                dataset_name=Path(dataset_dir).name,
                experiment_group=group.name,
                task_ids=task_ids,
                repeats=repeats,
                model_id=group.model_id,
                prompt_version=group.prompt_version,
                config=group.model_dump(mode="json"),
                budget=group.budget,
            )
            records_by_group[group.name] = records
            summaries[group.name] = summary

        comparisons = [
            paired_comparison(
                records_by_group,
                comparison="Multi-Agent vs Single-Agent",
                left_group="B_static_multi_agent",
                right_group="A_single_agent_tools",
            ),
            paired_comparison(
                records_by_group,
                comparison="Memory vs Static",
                left_group="C_static_memory",
                right_group="B_static_multi_agent",
            ),
            paired_comparison(
                records_by_group,
                comparison="Reflection vs Static",
                left_group="D_static_reflection",
                right_group="B_static_multi_agent",
            ),
            paired_comparison(
                records_by_group,
                comparison="Adaptive Planning ablation",
                left_group="E_full",
                right_group="abl_no_adaptive",
            ),
            paired_comparison(
                records_by_group,
                comparison="Memory ablation",
                left_group="E_full",
                right_group="abl_no_memory",
            ),
            paired_comparison(
                records_by_group,
                comparison="Reflection ablation",
                left_group="E_full",
                right_group="abl_no_reflection",
            ),
        ]
        all_records = [record for records in records_by_group.values() for record in records]
        breakdown = failure_breakdown(all_records)
        report = ExperimentSuiteReport(
            dataset=str(dataset_dir),
            created_at=datetime.now(timezone.utc),
            groups=groups,
            summaries=summaries,
            paired_comparisons=comparisons,
            failure_breakdown=breakdown,
            data_status="verified" if any(record.result.status != "skipped" for record in all_records) else "not_verified",
            limitations=[
                "results marked skipped or unknown are not agent benchmark evidence",
                "bootstrap intervals require paired non-skipped task results",
                "cost is unknown unless the executor reports token and price data",
            ],
        )
        self._write_manifest(groups)
        self._write_suite_raw(all_records)
        self._write_experiment_table(summaries)
        self._write_comparisons(comparisons)
        self._write_failures(breakdown)
        self._write_report(report)
        return report

    def _write_manifest(self, groups: list[ExperimentConfig]) -> None:
        payload = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "groups": [group.model_dump(mode="json") for group in groups],
            "paired_task_key": ["task_id", "run_index"],
            "fixed_fields": ["model_id", "prompt_version", "tool_set", "budget"],
            "disclosed_differences": [
                "memory_enabled",
                "reflection_enabled",
                "adaptive_planning",
                "multi_agent",
            ],
        }
        (self.output_dir / "experiment_manifest.json").write_text(
            json.dumps(payload, indent=2) + "\n",
            encoding="utf-8",
        )

    def _write_suite_raw(self, records: list[BenchmarkRecord]) -> None:
        with (self.output_dir / "suite_raw.jsonl").open("w", encoding="utf-8") as handle:
            for record in records:
                handle.write(record.model_dump_json() + "\n")
        with (self.output_dir / "suite_raw.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(["experiment_group", "task_id", "run_index", "status", "success", "failure_type", "duration_seconds"])
            for record in records:
                writer.writerow([
                    record.experiment_group,
                    record.task_id,
                    record.run_index,
                    record.result.status,
                    record.result.success,
                    record.result.failure_type,
                    record.result.duration_seconds,
                ])

    def _write_experiment_table(self, summaries: Mapping[str, BenchmarkSummary]) -> None:
        metrics = [
            "resolution_rate",
            "patch_pass_rate",
            "regression_rate",
            "root_cause_accuracy",
            "tool_success_rate",
            "replanning_rate",
            "reflection_recovery_rate",
            "memory_retrieval_hit_rate",
            "latency_p50_seconds",
            "latency_p95_seconds",
            "total_input_tokens",
            "total_output_tokens",
            "total_llm_calls",
            "total_estimated_cost_usd",
        ]
        with (self.output_dir / "experiment_table.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["experiment_group", *metrics], lineterminator="\n")
            writer.writeheader()
            for group_name, summary in summaries.items():
                values = summary.metrics.model_dump(mode="json")
                writer.writerow({"experiment_group": group_name, **{metric: values.get(metric) for metric in metrics}})

    def _write_comparisons(self, comparisons: list[PairedComparison]) -> None:
        (self.output_dir / "paired_comparisons.json").write_text(
            json.dumps([item.model_dump(mode="json") for item in comparisons], indent=2) + "\n",
            encoding="utf-8",
        )
        with (self.output_dir / "paired_comparisons.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow([
                "comparison",
                "left_group",
                "right_group",
                "paired_tasks",
                "left_wins",
                "right_wins",
                "ties",
                "left_success_rate",
                "right_success_rate",
                "success_rate_difference",
                "ci95_lower",
                "ci95_upper",
                "interpretation",
            ])
            for item in comparisons:
                writer.writerow([
                    item.comparison,
                    item.left_group,
                    item.right_group,
                    item.paired_tasks,
                    item.left_wins,
                    item.right_wins,
                    item.ties,
                    item.left_success_rate,
                    item.right_success_rate,
                    item.success_rate_difference,
                    item.bootstrap_95.lower,
                    item.bootstrap_95.upper,
                    item.interpretation,
                ])

    def _write_failures(self, breakdown: list[FailureBreakdown]) -> None:
        (self.output_dir / "failure_analysis.json").write_text(
            json.dumps([item.model_dump(mode="json") for item in breakdown], indent=2) + "\n",
            encoding="utf-8",
        )
        with (self.output_dir / "failure_analysis.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(["group", "failure_stage", "failure_type", "count"])
            for item in breakdown:
                writer.writerow([item.group, item.failure_stage, item.failure_type, item.count])

    def _write_report(self, report: ExperimentSuiteReport) -> None:
        (self.output_dir / "suite_report.json").write_text(
            report.model_dump_json(indent=2) + "\n",
            encoding="utf-8",
        )
