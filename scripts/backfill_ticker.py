#!/usr/bin/env python
"""Backfill historical data for a ticker.

Usage:
    python scripts/backfill_ticker.py --ticker NVDA --days 30
    python scripts/backfill_ticker.py --ticker NVDA --days 30 --documents-only
    python scripts/backfill_ticker.py --ticker NVDA --days 365 --sources sec_edgar
    python scripts/backfill_ticker.py --ticker NVDA --days 90 --dry-run
"""
import argparse
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from models import Base
from pipeline_runner import run_ticker_pipeline


def main():
    parser = argparse.ArgumentParser(description="Backfill historical data for a ticker")
    parser.add_argument("--ticker", type=str, required=True, help="Ticker to backfill")
    parser.add_argument("--days", type=int, required=True, help="Number of days to backfill")
    parser.add_argument("--dry-run", action="store_true", help="Fetch without persisting")
    parser.add_argument("--sources", nargs="+", help="Restrict to specific source keys")
    parser.add_argument("--documents-only", action="store_true", help="Only backfill document sources")
    parser.add_argument("--non-documents-only", action="store_true", help="Only backfill non-document sources")
    parser.add_argument("--use-llm", action="store_true", help="Use LLM for claim extraction")
    parser.add_argument("--db", type=str, default=None, help="Database URL override")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )

    db_url = args.db or os.getenv("DATABASE_URL", "sqlite:///consensus.db")
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)

    print(f"Backfilling {args.ticker} for {args.days} days...")
    if args.dry_run:
        print("[DRY RUN MODE]")

    with Session(engine) as session:
        summary = run_ticker_pipeline(
            session, args.ticker,
            days=args.days,
            dry_run=args.dry_run,
            source_filter=args.sources,
            use_llm=args.use_llm,
            documents_only=args.documents_only,
            non_documents_only=args.non_documents_only,
        )
        if not args.dry_run:
            session.commit()

    print(f"\nBackfill complete for {args.ticker}:")
    print(f"  Docs fetched:    {summary.total_docs_fetched}")
    print(f"  Docs inserted:   {summary.total_docs_inserted}")
    print(f"  Dupes skipped:   {summary.total_duplicates_skipped}")
    print(f"  Claims extracted:{summary.total_claims_extracted}")
    print(f"  Thesis updated:  {summary.thesis_updated}")
    if summary.errors:
        print(f"  Errors: {summary.errors}")

    print("\n--- JSON ---")
    print(json.dumps(summary.to_dict(), indent=2, default=str))


if __name__ == "__main__":
    main()
