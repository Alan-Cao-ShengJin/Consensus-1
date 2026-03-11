#!/usr/bin/env python
"""
CLI: ingest a local document and print results.

Usage:
    python scripts/test_ingest_document.py --file <path> --source-type earnings_transcript --ticker NVDA
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from models import Base, SourceType
from ingest_runner import run_ingestion


SOURCE_TYPE_MAP = {st.value: st for st in SourceType}


def main():
    parser = argparse.ArgumentParser(description="Ingest a local document into the DB")
    parser.add_argument("--file", required=True, help="Path to document file")
    parser.add_argument("--source-type", required=True, choices=list(SOURCE_TYPE_MAP.keys()),
                        help="Document source type")
    parser.add_argument("--ticker", default=None, help="Primary company ticker")
    parser.add_argument("--thesis-id", type=int, default=None, help="Thesis ID to link claims to")
    parser.add_argument("--db-url", default="sqlite:///consensus.db",
                        help="Database URL (default: sqlite:///consensus.db)")
    args = parser.parse_args()

    if not os.path.isfile(args.file):
        print(f"Error: file not found: {args.file}")
        return 1

    engine = create_engine(args.db_url)
    Base.metadata.create_all(engine)

    source_type = SOURCE_TYPE_MAP[args.source_type]

    with Session(engine) as session:
        result = run_ingestion(
            session,
            file_path=args.file,
            source_type=source_type,
            ticker=args.ticker,
            thesis_id=args.thesis_id,
        )
        session.commit()

    print("=" * 50)
    print("  INGESTION RESULT")
    print("=" * 50)
    print(f"  Document ID:      {result.document_id}")
    print(f"  Claims inserted:  {result.num_claims}")
    print(f"  Tickers linked:   {', '.join(result.tickers_linked) or '(none)'}")
    print(f"  Themes linked:    {', '.join(result.themes_linked) or '(none)'}")
    print("=" * 50)
    return 0


if __name__ == "__main__":
    sys.exit(main())
