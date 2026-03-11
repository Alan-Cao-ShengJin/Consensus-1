#!/usr/bin/env python
"""Run a portfolio review cycle.

Usage:
    python scripts/run_portfolio_review.py
    python scripts/run_portfolio_review.py --as-of 2026-03-12
    python scripts/run_portfolio_review.py --json
    python scripts/run_portfolio_review.py --ticker NVDA
    python scripts/run_portfolio_review.py --type immediate
    python scripts/run_portfolio_review.py --no-persist
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
from portfolio_review_service import run_portfolio_review, format_review_text


def main():
    parser = argparse.ArgumentParser(description="Run portfolio review")
    parser.add_argument("--as-of", type=str, default=None,
                        help="Review date (YYYY-MM-DD, default: today)")
    parser.add_argument("--ticker", type=str, default=None,
                        help="Review only this ticker")
    parser.add_argument("--type", type=str, default="weekly",
                        choices=["weekly", "immediate", "ad_hoc"],
                        help="Review type (default: weekly)")
    parser.add_argument("--json", action="store_true",
                        help="Output in JSON format")
    parser.add_argument("--no-persist", action="store_true",
                        help="Do not persist review to DB")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Verbose logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    review_date = None
    if args.as_of:
        review_date = date.fromisoformat(args.as_of)

    db_url = os.environ.get("DATABASE_URL", "sqlite:///consensus.db")
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        result = run_portfolio_review(
            session,
            as_of=review_date,
            review_type=args.type,
            ticker_filter=args.ticker,
            persist=not args.no_persist,
        )

        if not args.no_persist:
            session.commit()

        if args.json:
            print(json.dumps(result.to_dict(), indent=2))
        else:
            print(format_review_text(result))


if __name__ == "__main__":
    main()
