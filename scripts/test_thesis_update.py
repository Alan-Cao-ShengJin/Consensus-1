#!/usr/bin/env python
"""
CLI: ingest a document, extract claims, then run thesis update.

Usage:
    python scripts/test_thesis_update.py \
        --file tests/fixtures/nvda_earnings.txt \
        --source-type earnings_transcript \
        --ticker NVDA \
        --extractor stub \
        --thesis-title "AI Capex Thesis"

    # With LLM (requires OPENAI_API_KEY):
    python scripts/test_thesis_update.py \
        --file tests/fixtures/nvda_earnings.txt \
        --source-type earnings_transcript \
        --ticker NVDA \
        --extractor llm \
        --thesis-title "AI Capex Thesis"
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from models import Base, Company, Thesis, Claim, SourceType, ThesisState  # noqa: E402
from ingest_runner import run_ingestion  # noqa: E402
from thesis_update_service import update_thesis_from_claims  # noqa: E402


SOURCE_TYPE_MAP = {st.value: st for st in SourceType}


def main():
    parser = argparse.ArgumentParser(description="Ingest + thesis update demo")
    parser.add_argument("--file", required=True, help="Path to document file")
    parser.add_argument("--source-type", required=True, choices=list(SOURCE_TYPE_MAP.keys()))
    parser.add_argument("--ticker", default="NVDA", help="Primary company ticker")
    parser.add_argument("--extractor", choices=["stub", "llm"], default="stub")
    parser.add_argument("--thesis-title", default="AI Capex Thesis")
    parser.add_argument("--thesis-id", type=int, default=None, help="Existing thesis ID")
    parser.add_argument("--use-llm-update", action="store_true",
                        help="Use LLM for thesis update classification (requires OPENAI_API_KEY)")
    parser.add_argument("--db-url", default="sqlite:///consensus.db")
    args = parser.parse_args()

    if not os.path.isfile(args.file):
        print(f"Error: file not found: {args.file}")
        return 1

    engine = create_engine(args.db_url)
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        # --- Step 1: Ingest document ---
        result = run_ingestion(
            session,
            file_path=args.file,
            source_type=SOURCE_TYPE_MAP[args.source_type],
            ticker=args.ticker,
            extractor_type=args.extractor,
        )
        session.commit()

        print("=" * 60)
        print("  INGESTION")
        print("=" * 60)
        print(f"  Document ID:     {result.document_id}")
        print(f"  Claims inserted: {result.num_claims}")
        print(f"  Tickers:         {', '.join(result.tickers_linked) or '(none)'}")
        print(f"  Themes:          {', '.join(result.themes_linked) or '(none)'}")

        # --- Step 2: Get or create thesis ---
        if args.thesis_id:
            thesis = session.get(Thesis, args.thesis_id)
            if not thesis:
                print(f"Error: thesis {args.thesis_id} not found")
                return 1
        else:
            # Ensure company exists
            company = session.get(Company, args.ticker)
            if not company:
                company = Company(ticker=args.ticker, name=args.ticker)
                session.add(company)
                session.flush()

            thesis = Thesis(
                title=args.thesis_title,
                company_ticker=args.ticker,
                state=ThesisState.FORMING,
                conviction_score=50.0,
                summary=f"Investment thesis for {args.ticker}",
            )
            session.add(thesis)
            session.flush()
            session.commit()

        print()
        print("=" * 60)
        print("  THESIS (BEFORE)")
        print("=" * 60)
        print(f"  Thesis ID:       {thesis.id}")
        print(f"  Title:           {thesis.title}")
        print(f"  State:           {thesis.state.value}")
        print(f"  Conviction:      {thesis.conviction_score}")

        # --- Step 3: Get claim IDs from the ingested document ---
        claim_ids = [
            cid for (cid,) in session.execute(
                select(Claim.id).where(Claim.document_id == result.document_id)
            ).all()
        ]

        # --- Step 4: Run thesis update ---
        update_result = update_thesis_from_claims(
            session,
            thesis.id,
            claim_ids,
            use_llm=args.use_llm_update,
        )
        session.commit()

        print()
        print("=" * 60)
        print("  THESIS UPDATE RESULT")
        print("=" * 60)
        print(f"  State:  {update_result['before_state']} -> {update_result['after_state']}")
        print(f"  Score:  {update_result['before_score']} -> {update_result['after_score']}")
        print(f"  Note:   {update_result.get('summary_note', '')}")
        print()
        print("  Claim assessments:")
        for a in update_result.get("assessments", []):
            print(f"    claim_id={a['claim_id']}  impact={a['impact']}  "
                  f"materiality={a['materiality']}  delta={a['delta']}")
        print("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
