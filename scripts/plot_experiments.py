#!/usr/bin/env python3
"""Render reproducible SVG experiment charts without third-party plotting packages."""

from __future__ import annotations

import csv
import html
import sys
from pathlib import Path


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _float(value: str | None) -> float | None:
    if value in (None, "", "None"):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _svg(title: str, subtitle: str, rows: list[tuple[str, float | None, str]], output: Path) -> None:
    width = 920
    height = 180 + 42 * max(1, len(rows))
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<style>text{font-family:Arial,sans-serif;fill:#17202a}.title{font-size:22px;font-weight:700}.sub{font-size:13px;fill:#566573}.bar{fill:#2874a6}.unknown{fill:#b3b6b7}.label{font-size:13px}.value{font-size:12px;fill:#34495e}</style>',
        f'<rect width="{width}" height="{height}" fill="white"/>',
        f'<text x="28" y="38" class="title">{html.escape(title)}</text>',
        f'<text x="28" y="64" class="sub">{html.escape(subtitle)}</text>',
    ]
    y = 98
    for label, value, status in rows:
        parts.append(f'<text x="28" y="{y + 18}" class="label">{html.escape(label)}</text>')
        if value is None:
            parts.append(f'<rect x="310" y="{y}" width="360" height="26" class="unknown"/>')
            parts.append(f'<text x="685" y="{y + 18}" class="value">unknown</text>')
        else:
            bar_width = max(2, int(360 * max(0.0, min(1.0, value))))
            parts.append(f'<rect x="310" y="{y}" width="{bar_width}" height="26" class="bar"/>')
            parts.append(f'<text x="685" y="{y + 18}" class="value">{value:.3f} ({status})</text>')
        y += 42
    parts.append("</svg>")
    output.write_text("\n".join(parts) + "\n", encoding="utf-8")


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: plot_experiments.py RESULTS_DIR OUTPUT_DIR", file=sys.stderr)
        return 2
    results = Path(sys.argv[1])
    output = Path(sys.argv[2])
    output.mkdir(parents=True, exist_ok=True)

    table = _read_csv(results / "experiment_table.csv")
    rows = [(row["experiment_group"], _float(row.get("resolution_rate")), "resolution") for row in table]
    _svg("Experiment Resolution Rate", "Unknown values are not agent benchmark evidence.", rows, output / "resolution_rate.svg")

    latency_rows = [
        (row["experiment_group"], _float(row.get("latency_p50_seconds")), "p50 seconds")
        for row in table
    ]
    _svg("Experiment Latency P50", "Values are seconds; unknown means no verified execution.", latency_rows, output / "latency_p50.svg")

    failure_rows = []
    failure_path = results / "failure_analysis.csv"
    if failure_path.exists():
        for row in _read_csv(failure_path):
            failure_rows.append((
                f"{row['group']} / {row['failure_stage'] or 'unknown'} / {row['failure_type'] or 'unknown'}",
                None if not row.get("count") else min(1.0, float(row["count"]) / 10.0),
                f"count={row.get('count', '0')}",
            ))
    if not failure_rows:
        failure_rows = [("No verified failure cases", None, "not verified")]
    _svg("Failure Breakdown", "Failure stages/types require real executor results.", failure_rows, output / "failure_breakdown.svg")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
