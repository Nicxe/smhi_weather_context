#!/usr/bin/env python3
"""Enforce a greater-than-95-percent branch coverage gate per integration module."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

DOMAIN_PATH = "custom_components/smhi_weather_context/"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("coverage_json", type=Path)
    parser.add_argument("--minimum", type=float, default=95.0)
    args = parser.parse_args()

    report = json.loads(args.coverage_json.read_text(encoding="utf-8"))
    failures: list[tuple[str, float]] = []
    checked = 0
    for filename, details in sorted(report["files"].items()):
        normalized = filename.replace("\\", "/")
        if DOMAIN_PATH not in normalized or not normalized.endswith(".py"):
            continue
        checked += 1
        covered = float(details["summary"]["percent_covered"])
        print(f"{normalized}: {covered:.2f}%")
        if covered <= args.minimum:
            failures.append((normalized, covered))
    if checked == 0:
        raise SystemExit("No integration modules found in coverage report")
    if failures:
        formatted = ", ".join(
            f"{filename}={covered:.2f}%" for filename, covered in failures
        )
        raise SystemExit(
            f"Per-module coverage must be greater than {args.minimum:.2f}%: {formatted}"
        )
    print(
        f"All {checked} integration modules exceed {args.minimum:.2f}% branch coverage"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
