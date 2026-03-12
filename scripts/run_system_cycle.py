"""CLI entrypoint for Step 10: run a full system cycle.

Usage examples:
  python scripts/run_system_cycle.py --demo
  python scripts/run_system_cycle.py --paper
  python scripts/run_system_cycle.py --paper --tickers NVDA MSFT
  python scripts/run_system_cycle.py --paper --dry-run
  python scripts/run_system_cycle.py --paper --paper-execute
  python scripts/run_system_cycle.py --paper --paper-execute --require-approval
  python scripts/run_system_cycle.py --paper --approve-batch <batch_id>
  python scripts/run_system_cycle.py --paper --resume-from review
  python scripts/run_system_cycle.py --demo --paper-execute
  python scripts/run_system_cycle.py --config config.json
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import date

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import SystemConfig, Environment, get_default_config
from run_manager import (
    RunManager, RunManifest, RunStatus,
    approve_batch, load_approval_state, ApprovalStatus,
    run_system_cycle, _find_existing_manifests,
)


def setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def handle_approve(args):
    """Handle --approve-batch: approve a pending execution batch."""
    batch_id = args.approve_batch
    artifact_base = args.artifact_dir or "artifacts"
    run_date = args.date or date.today().isoformat()

    # Find manifests for this date
    manifests = _find_existing_manifests(artifact_base, run_date)
    if not manifests:
        print(f"No runs found for date {run_date}")
        return

    approved = False
    for path in manifests:
        manifest = RunManifest.load(path)
        if manifest.batch_id == batch_id:
            artifact_dir = manifest.artifact_dir
            if approve_batch(artifact_dir, batch_id):
                print(f"Batch {batch_id} approved.")
                print(f"Re-run with --paper-execute to execute.")
                approved = True
                break

    if not approved:
        # Try approving by searching all run dirs
        for path in manifests:
            manifest = RunManifest.load(path)
            artifact_dir = manifest.artifact_dir
            if approve_batch(artifact_dir, batch_id):
                print(f"Batch {batch_id} approved.")
                approved = True
                break

    if not approved:
        print(f"Batch {batch_id} not found or already processed.")


def format_manifest_text(manifest: RunManifest) -> str:
    """Format a run manifest as human-readable text."""
    lines = [
        "=" * 60,
        "SYSTEM CYCLE SUMMARY",
        "=" * 60,
        f"  Run ID:       {manifest.run_id}",
        f"  Environment:  {manifest.environment}",
        f"  Date:         {manifest.run_date}",
        f"  Status:       {manifest.status}",
        f"  Started:      {manifest.started_at}",
        f"  Ended:        {manifest.ended_at or 'N/A'}",
    ]

    if manifest.batch_id:
        lines.append(f"  Batch ID:     {manifest.batch_id}")
    if manifest.approval_status != ApprovalStatus.NOT_REQUIRED:
        lines.append(f"  Approval:     {manifest.approval_status}")
    if manifest.error_summary:
        lines.append(f"  Error:        {manifest.error_summary}")
    lines.append("")

    lines.append("STAGES:")
    for name, sr in manifest.stages.items():
        status_icon = {
            "COMPLETED": "+",
            "FAILED": "X",
            "SKIPPED": "-",
            "RUNNING": "~",
            "PENDING": ".",
        }.get(sr.status, "?")
        lines.append(f"  [{status_icon}] {name:25s} {sr.status}")
        if sr.counts:
            counts_str = ", ".join(f"{k}={v}" for k, v in sr.counts.items())
            lines.append(f"      {counts_str}")
        if sr.error:
            lines.append(f"      ERROR: {sr.error}")
        if sr.warnings:
            for w in sr.warnings[:3]:
                lines.append(f"      WARN: {w}")
    lines.append("")

    if manifest.artifact_dir:
        lines.append(f"  Artifacts: {manifest.artifact_dir}")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Step 10: Run a full system cycle",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Environment
    env_group = parser.add_mutually_exclusive_group(required=True)
    env_group.add_argument("--demo", action="store_true", help="Demo mode (synthetic data, no DB)")
    env_group.add_argument("--paper", action="store_true", help="Paper mode (real DB, paper fills)")
    env_group.add_argument("--approve-batch", type=str, metavar="BATCH_ID",
                           help="Approve a pending execution batch")

    # Tickers
    parser.add_argument("--tickers", nargs="+", help="Ticker symbols to process")

    # Execution
    parser.add_argument("--paper-execute", action="store_true",
                        help="Execute paper fills for approved intents")
    parser.add_argument("--require-approval", action="store_true",
                        help="Require human approval before paper execution")
    parser.add_argument("--dry-run", action="store_true",
                        help="Dry run: no persistence, no artifacts")
    parser.add_argument("--force", action="store_true",
                        help="Force run even if duplicate detected")

    # Recovery
    parser.add_argument("--resume-from", type=str, metavar="STAGE",
                        choices=RunManager.STAGES,
                        help="Resume from a specific stage")

    # Config
    parser.add_argument("--config", type=str, metavar="FILE",
                        help="Load configuration from JSON/YAML file")
    parser.add_argument("--artifact-dir", type=str, default="artifacts",
                        help="Base directory for artifacts")
    parser.add_argument("--portfolio-value", type=float,
                        help="Portfolio value in dollars")
    parser.add_argument("--date", type=str,
                        help="Run date (YYYY-MM-DD, default: today)")

    # Output
    parser.add_argument("--json", dest="json_output", action="store_true",
                        help="Output manifest as JSON")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Verbose logging")

    args = parser.parse_args()
    setup_logging(args.verbose)

    # Handle approve-batch separately
    if args.approve_batch:
        handle_approve(args)
        return

    # Determine environment
    environment = Environment.DEMO if args.demo else Environment.PAPER

    # Build config
    if args.config:
        config = SystemConfig.from_file(args.config)
        config = config.merge({"environment": environment})
    else:
        config = get_default_config(environment)

    # Apply CLI overrides
    overrides = {}
    if args.tickers:
        overrides["tickers"] = args.tickers
    if args.paper_execute:
        overrides["paper_execute"] = True
        # If paper-execute is requested and dry-run is not explicitly set,
        # ensure dry_run is False so execution actually happens
        if not args.dry_run:
            overrides["dry_run"] = False
    if args.require_approval:
        overrides["require_approval"] = True
    if args.dry_run:
        overrides["dry_run"] = True
    if args.artifact_dir:
        overrides["artifact_base_dir"] = args.artifact_dir
    if args.portfolio_value:
        overrides["portfolio_value"] = args.portfolio_value

    if overrides:
        config = config.merge(overrides)

    # Parse run date
    run_date_obj = None
    if args.date:
        run_date_obj = date.fromisoformat(args.date)

    # Run cycle
    manifest = run_system_cycle(
        config=config,
        run_date=run_date_obj,
        resume_from=args.resume_from,
        force=args.force,
    )

    # Output
    if args.json_output:
        print(json.dumps(manifest.to_dict(), indent=2))
    else:
        print(format_manifest_text(manifest))


if __name__ == "__main__":
    main()
