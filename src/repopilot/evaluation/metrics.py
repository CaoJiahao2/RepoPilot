"""Aggregate benchmark metrics while preserving unknown values."""

from __future__ import annotations

from collections.abc import Iterable
from statistics import median

from repopilot.evaluation.models import BenchmarkRecord, BenchmarkSummary, MetricSummary


def _rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _quantile(values: list[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = probability * (len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def calculate_metrics(records: Iterable[BenchmarkRecord]) -> MetricSummary:
    records = list(records)
    total = len(records)
    observed = [record for record in records if record.result.status != "skipped"]
    successes = sum(record.result.success for record in observed)
    patch_evaluated = observed
    patch_passed = sum(record.result.patch_passed for record in patch_evaluated)
    regressions = sum(record.result.regression_detected for record in patch_evaluated)
    root_known = [record for record in records if record.result.root_cause_correct is not None]
    root_correct = sum(record.result.root_cause_correct is True for record in root_known)
    tool_calls = sum(record.result.tool_calls for record in records)
    tool_successes = sum(record.result.tool_successes for record in records)
    replans = sum(record.result.replans > 0 for record in observed)
    reflection_attempts = sum(record.result.reflection_attempts for record in records)
    reflection_recoveries = sum(record.result.reflection_recoveries for record in records)
    memory_retrievals = sum(record.result.memory_retrievals for record in records)
    memory_hits = sum(record.result.memory_hits for record in records)
    known_tokens = [record for record in records if record.result.input_tokens is not None and record.result.output_tokens is not None]
    known_costs = [record for record in records if record.result.estimated_cost_usd is not None]
    durations = [record.result.duration_seconds for record in observed]

    return MetricSummary(
        resolution_rate=_rate(successes, len(observed)),
        patch_pass_rate=_rate(patch_passed, len(patch_evaluated)),
        regression_rate=_rate(regressions, len(patch_evaluated)),
        root_cause_accuracy=_rate(root_correct, len(root_known)),
        tool_success_rate=_rate(tool_successes, tool_calls),
        replanning_rate=_rate(replans, len(observed)),
        reflection_recovery_rate=_rate(reflection_recoveries, reflection_attempts),
        memory_retrieval_hit_rate=_rate(memory_hits, memory_retrievals),
        latency_p50_seconds=_quantile(durations, 0.50),
        latency_p95_seconds=_quantile(durations, 0.95),
        total_input_tokens=sum(record.result.input_tokens for record in known_tokens) if known_tokens else None,
        total_output_tokens=sum(record.result.output_tokens for record in known_tokens) if known_tokens else None,
        total_llm_calls=sum(record.result.llm_calls for record in records),
        total_estimated_cost_usd=sum(record.result.estimated_cost_usd for record in known_costs) if known_costs else None,
        unknown_token_or_cost_tasks=total - len(known_tokens),
    )


def summarize(records: Iterable[BenchmarkRecord], *, dataset: str, experiment_group: str) -> BenchmarkSummary:
    records = list(records)
    return BenchmarkSummary(
        dataset=dataset,
        experiment_group=experiment_group,
        task_count=len({record.task_id for record in records}),
        run_count=len(records),
        success_count=sum(record.result.success for record in records),
        failed_count=sum(record.result.status == "failed" for record in records),
        skipped_count=sum(record.result.status == "skipped" for record in records),
        metrics=calculate_metrics(records),
    )
