#!/usr/bin/env python
"""Run the ingestion pipeline for one or more tickers.

Usage:
    python scripts/run_pipeline.py --ticker NVDA --dry-run
    python scripts/run_pipeline.py --ticker NVDA
    python scripts/run_pipeline.py --all-active
    python scripts/run_pipeline.py --all-active --sources sec_edgar google_rss
    python scripts/run_pipeline.py --ticker NVDA --days 30 --use-llm
"""
import argparse
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from models import Base
from source_registry import UNIVERSE_TICKERS
from pipeline_runner import run_pipeline


def main():
    parser = argparse.ArgumentParser(description="Run ingestion pipeline")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--ticker", type=str, help="Single ticker to process")
    group.add_argument("--all-active", action="store_true", help="Process all universe tickers")

    parser.add_argument("--days", type=int, default=7, help="Backfill depth in days (default: 7)")
    parser.add_argument("--dry-run", action="store_true", help="Fetch and dedupe without persisting")
    parser.add_argument("--sources", nargs="+", help="Restrict to specific source keys")
    parser.add_argument("--use-llm", action="store_true", help="Use LLM for claim extraction")
    parser.add_argument("--documents-only", action="store_true", help="Only run document sources")
    parser.add_argument("--non-documents-only", action="store_true", help="Only run non-document sources")
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

    tickers = [args.ticker] if args.ticker else UNIVERSE_TICKERS

    with Session(engine) as session:
        summaries = run_pipeline(
            session, tickers,
            days=args.days,
            dry_run=args.dry_run,
            source_filter=args.sources,
            use_llm=args.use_llm,
            documents_only=args.documents_only,
            non_documents_only=args.non_documents_only,
        )
        if not args.dry_run:
            session.commit()

    # Print summary
    print("\n" + "=" * 70)
    print("PIPELINE RUN SUMMARY")
    print("=" * 70)

    for s in summaries:
        print(f"\n--- {s.ticker} ---")
        print(f"  Docs fetched:    {s.total_docs_fetched}")
        print(f"  Docs inserted:   {s.total_docs_inserted}")
        print(f"  Dupes skipped:   {s.total_duplicates_skipped}")
        print(f"  Claims extracted:{s.total_claims_extracted}")
        print(f"  Thesis updated:  {s.thesis_updated}")
        if s.errors:
            print(f"  Errors:          {len(s.errors)}")
            for e in s.errors:
                print(f"    - {e}")

        for src in s.source_summaries:
            line = f"    [{src.source}]"
            parts = []
            if src.docs_fetched:
                parts.append(f"fetched={src.docs_fetched}")
            if src.docs_inserted:
                parts.append(f"inserted={src.docs_inserted}")
            if src.duplicates_skipped:
                parts.append(f"dupes={src.duplicates_skipped}")
            if src.claims_extracted:
                parts.append(f"claims={src.claims_extracted}")
            if src.prices_upserted:
                parts.append(f"prices={src.prices_upserted}")
            if src.checkpoints_upserted:
                parts.append(f"checkpoints={src.checkpoints_upserted}")
            if src.company_fields_updated:
                parts.append(f"enriched={src.company_fields_updated}")
            if parts:
                line += " " + ", ".join(parts)
            if src.errors:
                line += f" ERRORS: {src.errors}"
            print(line)

    if args.dry_run:
        print("\n[DRY RUN] No data was persisted.")

    # Machine-readable JSON output
    output = [s.to_dict() for s in summaries]
    print("\n--- JSON ---")
    print(json.dumps(output, indent=2, default=str))


if __name__ == "__main__":
    main()
