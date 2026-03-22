"""Rolling thesis rebuild: generate real theses chronologically from claims.

Processes claims in date order. For each ticker:
- First claim batch → generate thesis via LLM (thesis_generator.py)
- Subsequent batches → update thesis via LLM (thesis_update_service.py)

This ensures theses are built only from information available at each point
in time — no look-ahead bias.

Usage:
    python scripts/run_thesis_rebuild.py
    python scripts/run_thesis_rebuild.py --no-llm       # stub mode (fast, no API cost)
    python scripts/run_thesis_rebuild.py --dry-run       # show what would happen
    python scripts/run_thesis_rebuild.py --ticker NVDA   # single ticker
"""
import argparse
import logging
import os
import sys
import time
from collections import defaultdict
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger("thesis_rebuild")

for name in ("httpx", "httpcore", "urllib3", "openai"):
    logging.getLogger(name).setLevel(logging.WARNING)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load .env file for API keys
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Disable graph sync and cross-ticker propagation during rebuild
os.environ["DISABLE_GRAPH_SYNC"] = "1"
os.environ["DISABLE_PROPAGATION"] = "1"

from sqlalchemy import text, select
from db import SessionLocal, get_session
from models import Thesis, ThesisState, ThesisStateHistory


def reset_theses(session, ticker_filter=None):
    """Reset all theses to stubs: conv=50, generic title, FORMING state.

    Also clears thesis_state_history so we rebuild from scratch.
    """
    where_clause = ""
    if ticker_filter:
        where_clause = f"AND company_ticker = '{ticker_filter}'"

    # Clear state history
    session.execute(text(f"""
        DELETE FROM thesis_state_history WHERE thesis_id IN (
            SELECT id FROM theses WHERE status_active = 1 {where_clause}
        )
    """))

    # Clear evidence assessments
    session.execute(text(f"""
        DELETE FROM evidence_assessments WHERE thesis_id IN (
            SELECT id FROM theses WHERE status_active = 1 {where_clause}
        )
    """))

    # Clear thesis-claim links
    session.execute(text(f"""
        DELETE FROM thesis_claim_links WHERE thesis_id IN (
            SELECT id FROM theses WHERE status_active = 1 {where_clause}
        )
    """))

    # Reset thesis fields
    session.execute(text(f"""
        UPDATE theses SET
            title = company_ticker || ' thesis',
            summary = NULL,
            thesis_type = NULL,
            conviction_score = 50.0,
            state = 'FORMING',
            base_case_rerating = NULL,
            bull_case_rerating = NULL,
            bear_case_rerating = NULL,
            updated_at = created_at
        WHERE status_active = 1 {where_clause}
    """))

    # Re-create initial state history entries
    theses = session.execute(text(f"""
        SELECT id, company_ticker, created_at FROM theses
        WHERE status_active = 1 {where_clause}
    """)).fetchall()

    for t in theses:
        created = t[2]
        if isinstance(created, str):
            created = datetime.fromisoformat(created)
        if not created:
            created = datetime(2025, 10, 1)
        session.add(ThesisStateHistory(
            thesis_id=t[0],
            state=ThesisState.FORMING,
            conviction_score=50.0,
            note="Initial thesis creation for S&P 500 universe",
            created_at=created,
        ))

    session.commit()
    logger.info("Reset %d theses to stubs", len(theses))
    return len(theses)


def get_claim_batches(session, ticker_filter=None):
    """Get claims grouped by (ticker, document), ordered by published_at.

    Returns list of (ticker, doc_id, published_at, [claim_ids]).
    """
    where_clause = ""
    if ticker_filter:
        where_clause = f"AND ccl.company_ticker = '{ticker_filter}'"

    rows = session.execute(text(f"""
        SELECT ccl.company_ticker, cl.document_id, d.published_at,
               GROUP_CONCAT(cl.id) as claim_ids
        FROM claims cl
        JOIN claim_company_links ccl ON ccl.claim_id = cl.id
        JOIN documents d ON d.id = cl.document_id
        WHERE cl.novelty_type IN ('NEW', 'CONFIRMING', 'CONFLICTING')
        AND d.published_at < '2027-01-01'
        {where_clause}
        GROUP BY ccl.company_ticker, cl.document_id
        ORDER BY d.published_at ASC, ccl.company_ticker ASC
    """)).fetchall()

    batches = []
    for r in rows:
        claim_ids = [int(x) for x in r[3].split(",")]
        batches.append({
            "ticker": r[0],
            "doc_id": r[1],
            "published_at": r[2],
            "claim_ids": claim_ids,
        })
    return batches


def run_rebuild(use_llm=True, ticker_filter=None, dry_run=False, generate_only=False):
    """Run the full thesis rebuild pipeline."""
    from thesis_generator import generate_thesis
    from thesis_update_service import update_thesis_from_claims

    session = SessionLocal()

    try:
        # Step 1: Reset all theses
        if not dry_run:
            reset_count = reset_theses(session, ticker_filter)
        else:
            reset_count = session.execute(text(
                "SELECT COUNT(*) FROM theses WHERE status_active = 1"
            )).scalar()
            logger.info("[DRY RUN] Would reset %d theses", reset_count)

        # Step 2: Get claim batches in chronological order
        batches = get_claim_batches(session, ticker_filter)
        logger.info("Found %d claim batches to process", len(batches))

        if dry_run:
            # Show summary
            tickers_seen = set()
            gen_count = 0
            update_count = 0
            for b in batches:
                if b["ticker"] not in tickers_seen:
                    gen_count += 1
                    tickers_seen.add(b["ticker"])
                else:
                    update_count += 1
            logger.info(
                "[DRY RUN] Would make %d thesis generation calls + %d update calls = %d total",
                gen_count, update_count, gen_count + update_count,
            )
            return

        # Step 3: Process batches chronologically
        tickers_generated = set()  # track which tickers have had thesis generated
        stats = {
            "generated": 0,
            "updated": 0,
            "errors": 0,
            "skipped": 0,
        }
        start_time = time.time()

        for i, batch in enumerate(batches, 1):
            ticker = batch["ticker"]
            claim_ids = batch["claim_ids"]
            published_at = batch["published_at"]

            # Parse published_at if string
            if isinstance(published_at, str):
                published_at = datetime.fromisoformat(published_at)

            try:
                if ticker not in tickers_generated:
                    # First batch for this ticker → generate thesis
                    thesis = generate_thesis(
                        session, ticker, use_llm=use_llm,
                    )
                    if thesis:
                        # Back-date the thesis history to document published_at
                        _backdate_latest_history(session, ticker, published_at)
                        session.commit()
                        tickers_generated.add(ticker)
                        stats["generated"] += 1
                    else:
                        stats["skipped"] += 1
                        tickers_generated.add(ticker)  # don't retry
                        session.commit()
                        continue

                    # Now also run the update with these specific claims
                    # so claim links and evidence assessments are created
                    if not generate_only:
                        thesis_obj = session.scalars(
                            select(Thesis).where(
                                Thesis.company_ticker == ticker,
                                Thesis.status_active == True,
                            ).limit(1)
                        ).first()
                        if thesis_obj:
                            update_thesis_from_claims(
                                session, thesis_obj.id, claim_ids,
                                use_llm=use_llm,
                                reference_time=published_at,
                            )
                            _backdate_latest_history(session, ticker, published_at)
                            session.commit()

                else:
                    if generate_only:
                        # Skip subsequent updates in generate-only mode
                        continue

                    # Subsequent batch → update thesis
                    thesis_obj = session.scalars(
                        select(Thesis).where(
                            Thesis.company_ticker == ticker,
                            Thesis.status_active == True,
                        ).limit(1)
                    ).first()
                    if thesis_obj:
                        update_thesis_from_claims(
                            session, thesis_obj.id, claim_ids,
                            use_llm=use_llm,
                            reference_time=published_at,
                        )
                        _backdate_latest_history(session, ticker, published_at)
                        session.commit()
                        stats["updated"] += 1
                    else:
                        stats["skipped"] += 1

            except Exception as e:
                session.rollback()
                stats["errors"] += 1
                logger.warning("Error processing %s batch %d: %s", ticker, i, e)

            # Progress logging
            if i % 50 == 0:
                elapsed = time.time() - start_time
                rate = i / elapsed
                remaining = (len(batches) - i) / rate if rate > 0 else 0
                logger.info(
                    "Progress: %d/%d batches (%.0f/s, ~%.0fm remaining) | "
                    "gen=%d upd=%d err=%d skip=%d",
                    i, len(batches), rate, remaining / 60,
                    stats["generated"], stats["updated"],
                    stats["errors"], stats["skipped"],
                )

        elapsed = time.time() - start_time
        logger.info(
            "\n=== REBUILD COMPLETE ===\n"
            "Batches processed: %d in %.0fs (%.1f/s)\n"
            "Theses generated:  %d\n"
            "Thesis updates:    %d\n"
            "Errors:            %d\n"
            "Skipped:           %d",
            len(batches), elapsed, len(batches) / elapsed if elapsed > 0 else 0,
            stats["generated"], stats["updated"],
            stats["errors"], stats["skipped"],
        )

        # Show conviction distribution after rebuild
        _show_conviction_distribution(session)

    finally:
        session.close()


def _backdate_latest_history(session, ticker: str, target_dt: datetime):
    """Back-date the most recent thesis state history entry for a ticker."""
    thesis = session.scalars(
        select(Thesis).where(
            Thesis.company_ticker == ticker,
            Thesis.status_active == True,
        ).limit(1)
    ).first()
    if not thesis:
        return

    latest = session.execute(text("""
        SELECT id FROM thesis_state_history
        WHERE thesis_id = :tid
        ORDER BY created_at DESC LIMIT 1
    """), {"tid": thesis.id}).fetchone()

    if latest:
        session.execute(text("""
            UPDATE thesis_state_history
            SET created_at = :dt
            WHERE id = :hid
        """), {"dt": target_dt, "hid": latest[0]})


def _show_conviction_distribution(session):
    """Show post-rebuild conviction distribution."""
    rows = session.execute(text("""
        SELECT
            CASE
                WHEN conviction_score >= 75 THEN '75-100 (high)'
                WHEN conviction_score >= 60 THEN '60-75 (moderate)'
                WHEN conviction_score >= 45 THEN '45-60 (neutral)'
                WHEN conviction_score >= 30 THEN '30-45 (low)'
                ELSE '0-30 (very low)'
            END as bucket,
            COUNT(*) as cnt,
            AVG(conviction_score) as avg_score
        FROM theses
        WHERE status_active = 1
        GROUP BY bucket
        ORDER BY bucket DESC
    """)).fetchall()

    logger.info("\n=== CONVICTION DISTRIBUTION ===")
    for r in rows:
        logger.info("  %s: %d theses (avg %.1f)", r[0], r[1], r[2])

    # Show state distribution
    states = session.execute(text("""
        SELECT state, COUNT(*) FROM theses WHERE status_active = 1
        GROUP BY state ORDER BY COUNT(*) DESC
    """)).fetchall()
    logger.info("\n=== STATE DISTRIBUTION ===")
    for r in states:
        logger.info("  %s: %d", r[0], r[1])


def main():
    parser = argparse.ArgumentParser(description="Rolling thesis rebuild")
    parser.add_argument("--no-llm", action="store_true",
                        help="Stub mode — no LLM API calls")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show plan without executing")
    parser.add_argument("--ticker", type=str, default=None,
                        help="Process only this ticker")
    parser.add_argument("--generate-only", action="store_true",
                        help="Only generate theses, skip claim-by-claim updates")
    args = parser.parse_args()

    run_rebuild(
        use_llm=not args.no_llm,
        ticker_filter=args.ticker,
        dry_run=args.dry_run,
        generate_only=args.generate_only,
    )


if __name__ == "__main__":
    main()
