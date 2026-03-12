"""CLI entrypoint: run account sync, reconciliation, and live-readiness checks.

Usage:
  python scripts/run_account_sync.py --mode live-readonly
  python scripts/run_account_sync.py --broker mock
  python scripts/run_account_sync.py --broker file --snapshot path/to/snapshot.json
  python scripts/run_account_sync.py --json
  python scripts/run_account_sync.py --readiness-only
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from account_sync import (
    InternalState,
    InternalPosition,
    run_account_sync,
    format_reconciliation_text,
)
from approval_hardened import load_approval
from broker_interface import BrokerPosition
from broker_readonly_adapter import create_broker_adapter
from config import Environment, get_default_config
from live_readiness_checks import (
    run_readiness_checks,
    format_readiness_text,
)


def setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def _build_demo_internal_state() -> InternalState:
    """Build a synthetic internal state for demo/testing."""
    return InternalState(
        cash=500_000.0,
        total_value=1_000_000.0,
        positions=[
            InternalPosition(ticker="AAPL", shares=100.0, market_value=150_000.0, weight=15.0),
            InternalPosition(ticker="MSFT", shares=80.0, market_value=200_000.0, weight=20.0),
            InternalPosition(ticker="GOOG", shares=50.0, market_value=150_000.0, weight=15.0),
        ],
    )


def _build_demo_broker_kwargs() -> dict:
    """Build kwargs for MockBrokerAdapter matching the demo internal state."""
    return {
        "cash": 498_000.0,  # Slightly different for reconciliation testing
        "positions": [
            BrokerPosition(ticker="AAPL", shares=100.0, market_value=150_500.0,
                         avg_cost=120.0, last_price=1505.0),
            BrokerPosition(ticker="MSFT", shares=80.0, market_value=200_000.0,
                         avg_cost=200.0, last_price=2500.0),
            # GOOG missing from broker — tests missing_broker detection
        ],
        "prices": {"AAPL": 1505.0, "MSFT": 2500.0, "GOOG": 3000.0},
    }


def main():
    parser = argparse.ArgumentParser(
        description="Run account sync, reconciliation, and live-readiness checks",
    )
    parser.add_argument("--mode", type=str, default="live-readonly",
                       choices=["demo", "paper", "live-readonly", "live-disabled"],
                       help="Operating mode")
    parser.add_argument("--broker", type=str, default="mock",
                       choices=["mock", "file"],
                       help="Broker adapter type")
    parser.add_argument("--snapshot", type=str, default=None,
                       help="Broker snapshot file path (for --broker file)")
    parser.add_argument("--output-dir", type=str, default=None,
                       help="Output directory for artifacts")
    parser.add_argument("--json", dest="json_output", action="store_true",
                       help="Output as JSON")
    parser.add_argument("--readiness-only", action="store_true",
                       help="Run only readiness checks (skip sync)")
    parser.add_argument("--approval-dir", type=str, default=None,
                       help="Directory containing approval artifact")
    parser.add_argument("--verbose", "-v", action="store_true")

    args = parser.parse_args()
    setup_logging(args.verbose)

    # Map mode to environment
    mode_to_env = {
        "demo": Environment.DEMO,
        "paper": Environment.PAPER,
        "live-readonly": Environment.LIVE_READONLY,
        "live-disabled": Environment.LIVE_DISABLED,
    }
    environment = mode_to_env[args.mode]

    today = datetime.utcnow().strftime("%Y-%m-%d")
    output_dir = args.output_dir or os.path.join(
        "artifacts", "live_readiness", today,
    )

    reconciliation = None

    if not args.readiness_only:
        # Create broker adapter
        if args.broker == "mock":
            broker = create_broker_adapter(
                mode="mock", **_build_demo_broker_kwargs()
            )
        else:
            broker = create_broker_adapter(
                mode="file", snapshot_path=args.snapshot
            )

        # Build internal state (demo for now)
        internal_state = _build_demo_internal_state()

        # Run sync
        reconciliation = run_account_sync(
            broker=broker,
            internal_state=internal_state,
            output_dir=output_dir,
        )

        if args.json_output:
            print(json.dumps(reconciliation.to_dict(), indent=2, default=str))
        else:
            print(format_reconciliation_text(reconciliation))

    # Run readiness checks
    approval = None
    if args.approval_dir:
        approval = load_approval(args.approval_dir)

    readiness = run_readiness_checks(
        environment=environment,
        reconciliation=reconciliation,
        approval=approval,
    )

    if args.json_output:
        print(json.dumps(readiness.to_dict(), indent=2, default=str))
    else:
        print(format_readiness_text(readiness))

    # Export readiness report
    os.makedirs(output_dir, exist_ok=True)
    readiness_path = os.path.join(output_dir, "readiness_report.json")
    with open(readiness_path, "w") as f:
        json.dump(readiness.to_dict(), f, indent=2, default=str)

    if not args.json_output:
        print(f"\nArtifacts exported to: {output_dir}")

    sys.exit(0 if readiness.all_passed else 1)


if __name__ == "__main__":
    main()
