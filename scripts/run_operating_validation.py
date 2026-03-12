"""CLI entrypoint: run operating validation over repeated paper cycles.

Usage:
  python scripts/run_operating_validation.py --scenario happy_path
  python scripts/run_operating_validation.py --scenario duplicate_run
  python scripts/run_operating_validation.py --scenario failure_resume
  python scripts/run_operating_validation.py --all
  python scripts/run_operating_validation.py --scenario happy_path --json
  python scripts/run_operating_validation.py --list-scenarios
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import tempfile
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from operating_validator import OperatingValidator, SCENARIOS
from validation_report import build_report, format_report_text, export_report


def setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def main():
    parser = argparse.ArgumentParser(
        description="Run operating validation over repeated paper cycles",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--scenario", type=str, metavar="NAME",
                       help="Run a specific scenario")
    mode.add_argument("--all", action="store_true",
                       help="Run all predefined scenarios")
    mode.add_argument("--list-scenarios", action="store_true",
                       help="List available scenarios")

    parser.add_argument("--output-dir", type=str, default=None,
                       help="Output directory for validation artifacts")
    parser.add_argument("--json", dest="json_output", action="store_true",
                       help="Output report as JSON")
    parser.add_argument("--verbose", "-v", action="store_true")

    args = parser.parse_args()
    setup_logging(args.verbose)

    if args.list_scenarios:
        print("Available scenarios:")
        for name, sc in sorted(SCENARIOS.items()):
            print(f"  {name:30s} {sc.description}")
        return

    # Use temp dir for validation artifacts to avoid polluting real artifacts
    today = datetime.utcnow().strftime("%Y-%m-%d")
    output_dir = args.output_dir or os.path.join(
        "artifacts", "validation", today,
    )
    artifact_base = os.path.join(output_dir, "runs")

    validator = OperatingValidator(artifact_base_dir=artifact_base)

    if args.scenario:
        if args.scenario not in SCENARIOS:
            print(f"Unknown scenario: {args.scenario}")
            print(f"Available: {', '.join(sorted(SCENARIOS.keys()))}")
            sys.exit(1)
        results = [validator.run_scenario(args.scenario)]
    else:
        results = validator.run_all()

    # Build report
    report = build_report(results)

    if args.json_output:
        print(json.dumps(report.to_dict(), indent=2, default=str))
    else:
        print(format_report_text(report))

    # Export artifacts
    paths = export_report(report, output_dir)
    if not args.json_output:
        print(f"\nArtifacts exported to: {output_dir}")
        for fmt, path in paths.items():
            print(f"  {fmt}: {path}")

    # Exit code
    sys.exit(0 if report.overall_passed else 1)


if __name__ == "__main__":
    main()
