#!/usr/bin/env python
"""Run a historical replay of the portfolio decision engine.

Usage:
    python scripts/run_replay.py --start 2025-01-01 --end 2025-12-31
    python scripts/run_replay.py --start 2025-01-01 --end 2025-12-31 --initial-cash 1000000
    python scripts/run_replay.py --start 2025-01-01 --end 2025-12-31 --no-apply
    python scripts/run_replay.py --start 2025-01-01 --end 2025-12-31 --json
    python scripts/run_replay.py --ticker NVDA --start 2025-01-01 --end 2025-06-30
    python scripts/run_replay.py --start 2025-01-01 --end 2025-12-31 --cadence 14
    python scripts/run_replay.py --start 2025-01-01 --end 2025-12-31 --cost-bps 5
"""
import argparse
import json
import logging
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from models import Base
from replay_runner import run_replay, export_replay_json, format_replay_text


def main():
    parser = argparse.ArgumentParser(description="Run historical portfolio replay")
    parser.add_argument("--start", type=str, required=True,
                        help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, required=True,
                        help="End date (YYYY-MM-DD)")
    parser.add_argument("--initial-cash", type=float, default=1_000_000.0,
                        help="Initial cash (default: 1000000)")
    parser.add_argument("--cadence", type=int, default=7,
                        help="Days between reviews (default: 7)")
    parser.add_argument("--ticker", type=str, default=None,
                        help="Replay only this ticker")
    parser.add_argument("--no-apply", action="store_true",
                        help="Do not apply trades — recommendation history only")
    parser.add_argument("--json", action="store_true",
                        help="Output in JSON format")
    parser.add_argument("--export", action="store_true",
                        help="Export full results to replay_outputs/ JSON file")
    parser.add_argument("--cost-bps", type=float, default=10.0,
                        help="Transaction cost in basis points (default: 10)")
    parser.add_argument("--strict", action="store_true",
                        help="Strict replay: skip impure inputs instead of fallbacks")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Verbose logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)

    db_url = os.environ.get("DATABASE_URL", "sqlite:///consensus.db")
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        run_result, portfolio, metrics = run_replay(
            session,
            start_date=start,
            end_date=end,
            cadence_days=args.cadence,
            initial_cash=args.initial_cash,
            apply_trades=not args.no_apply,
            ticker_filter=args.ticker,
            transaction_cost_bps=args.cost_bps,
            strict_replay=args.strict,
        )

        if args.export:
            filepath = export_replay_json(run_result, portfolio, metrics)
            print(f"Exported to {filepath}")

        if args.json:
            output = {
                "run": run_result.to_dict(),
                "metrics": metrics.to_dict(),
                "portfolio": portfolio.to_dict(),
            }
            print(json.dumps(output, indent=2))
        else:
            print(format_replay_text(run_result, portfolio, metrics))


if __name__ == "__main__":
    main()
