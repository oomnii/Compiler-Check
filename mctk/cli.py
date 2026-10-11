"""Command-line entry."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from mctk.pipeline import execute_suite
from mctk.report import write_report
from mctk.suite_loader import load_suite


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="CompilerCheck — C++17 compile-once per config, run-many verification."
    )
    parser.add_argument("suite", type=Path, help="Path to suite YAML")
    parser.add_argument("--cache-dir", type=Path, default=Path(".mctk_cache"))
    parser.add_argument("--report", type=Path, default=Path("report.json"))
    parser.add_argument(
        "--report-text",
        type=Path,
        default=None,
        help="Text report (default: report path with .txt)",
    )
    args = parser.parse_args(argv)

    loaded = load_suite(args.suite)
    report = execute_suite(
        loaded.profiles,
        loaded.limits,
        args.cache_dir.resolve(),
        suite_path=args.suite.resolve(),
        expected_release_by_source=loaded.expected_release_by_source,
        requested_release_by_source=loaded.requested_release_by_source,
        unfulfilled_requested=loaded.unfulfilled_requested,
        enable_ubsan=loaded.enable_ubsan,
        skipped_toolchains=loaded.skipped_toolchains,
    )
    write_report(report, args.report, args.report_text)

    summary = {
        "profiles": len(report.profiles),
        "overall_verdict": report.interpretation.get("overall_verdict"),
        "coverage": report.interpretation.get("coverage"),
        "issue_count": len(report.interpretation.get("issues") or []),
        "report_json": str(args.report),
        "report_text": str(args.report_text or args.report.with_suffix(".txt")),
    }
    print(json.dumps(summary, indent=2))

    if summary["overall_verdict"] != "PASS":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
