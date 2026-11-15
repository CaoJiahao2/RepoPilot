"""Run fixed experiment groups and paired ablation comparisons."""

from __future__ import annotations

import argparse
from pathlib import Path

from repopilot.evaluation.experiments import ExperimentSuiteRunner, standard_experiment_groups
from repopilot.evaluation.executors import MockExecutor, SkippedExecutor


def main() -> int:
    parser = argparse.ArgumentParser(description="Run RepoPilot experiment suite")
    parser.add_argument("--dataset", default="benchmarks/tasks")
    parser.add_argument("--output", default="experiment-results")
    parser.add_argument("--task-id", action="append", dest="task_ids")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--model-id", default="unspecified")
    parser.add_argument("--prompt-version", default="v1")
    parser.add_argument("--executor", choices=("skipped", "mock", "real"), default="skipped")
    args = parser.parse_args()

    if args.executor == "real":
        from repopilot.evaluation.real_executor import RealRepairExecutor

        real_executor = RealRepairExecutor()
        executor_factory = lambda config: real_executor
    else:
        executor_factory = (
            (lambda config: SkippedExecutor())
            if args.executor == "skipped"
            else (lambda config: MockExecutor())
        )
    groups = standard_experiment_groups(
        model_id=args.model_id,
        prompt_version=args.prompt_version,
    )
    report = ExperimentSuiteRunner(
        executor_factory=executor_factory,
        output_dir=Path(args.output),
    ).run(
        args.dataset,
        groups=groups,
        task_ids=args.task_ids,
        repeats=args.repeats,
    )
    print(f"data_status={report.data_status}")
    print(f"groups={len(report.groups)} comparisons={len(report.paired_comparisons)}")
    print(f"output={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
