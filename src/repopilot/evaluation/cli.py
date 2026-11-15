"""One-command benchmark CLI with honest skipped/mock execution modes."""

from __future__ import annotations

import argparse
from pathlib import Path

from repopilot.evaluation.executors import MockExecutor, SkippedExecutor
from repopilot.evaluation.runner import BenchmarkRunner


def main() -> int:
    parser = argparse.ArgumentParser(description="Run RepoPilot benchmark tasks")
    parser.add_argument("--dataset", default="benchmarks/tasks")
    parser.add_argument("--output", default="benchmark-results")
    parser.add_argument("--group", default="full")
    parser.add_argument("--task-id", action="append", dest="task_ids")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--model-id", default="unspecified")
    parser.add_argument("--prompt-version", default="v1")
    parser.add_argument("--executor", choices=("skipped", "mock", "real"), default="skipped")
    args = parser.parse_args()

    if args.executor == "real":
        from repopilot.evaluation.real_executor import RealRepairExecutor

        executor = RealRepairExecutor()
    else:
        executor = SkippedExecutor() if args.executor == "skipped" else MockExecutor()
    runner = BenchmarkRunner(executor, output_dir=Path(args.output))
    records, summary = runner.run(
        args.dataset,
        dataset_name=Path(args.dataset).name,
        experiment_group=args.group,
        task_ids=args.task_ids,
        repeats=args.repeats,
        model_id=args.model_id,
        prompt_version=args.prompt_version,
    )
    print(f"records={len(records)} successes={summary.success_count} failures={summary.failed_count} skipped={summary.skipped_count}")
    print(f"summary={Path(args.output) / 'summary.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
