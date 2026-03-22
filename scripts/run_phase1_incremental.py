"""Phase 1: Incremental document ingestion with per-ticker commits.

Processes one ticker at a time, commits after each ticker so that
a crash never loses more than one ticker's worth of work.

Usage:
    python scripts/run_phase1_incremental.py [--resume]

The --resume flag skips tickers that already have documents in the DB.
"""
import logging
import sys
import time
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger("phase1")

# Suppress noisy loggers
for name in ("httpx", "httpcore", "urllib3", "edgar", "httpxthrottlecache"):
    logging.getLogger(name).setLevel(logging.WARNING)

sys.path.insert(0, ".")

from db import get_session, SessionLocal
from sqlalchemy import text, select
from models import Company, Document
from pipeline_runner import (
    run_ticker_pipeline,
    PRRSSConnector,
)

SOURCE_FILTER = [
    "sec_edgar",
    "earnings_transcript_fmp",
    "financials_fmp",
    "consensus_estimates_fmp",
    "earnings_alphavantage",
    "earnings_transcript_defeatbeta",
    "press_release_rss",
]

DAYS = 108  # reaches back to ~Dec 1 2025 from Mar 18 2026
USE_LLM = True
RESUME = "--resume" in sys.argv


def get_all_tickers():
    with get_session() as s:
        return s.execute(text("SELECT ticker FROM companies ORDER BY ticker")).scalars().all()


def get_completed_tickers():
    """Return tickers that already have documents (for resume mode)."""
    if not RESUME:
        return set()
    with get_session() as s:
        rows = s.execute(
            text("SELECT DISTINCT primary_company_ticker FROM documents")
        ).scalars().all()
        return set(rows)


def scan_broadcast_pr(tickers):
    """Scan PR RSS once for all tickers."""
    try:
        with get_session() as session:
            pr_scanner = PRRSSConnector()
            ticker_set = set(tickers)
            name_map = {}
            companies = session.scalars(
                select(Company).where(Company.ticker.in_(tickers))
            ).all()
            for co in companies:
                if co.name and len(co.name) >= 4:
                    name_upper = co.name.upper()
                    name_map[name_upper] = co.ticker
                    first_word = name_upper.split()[0] if " " in name_upper else ""
                    if first_word and len(first_word) >= 5:
                        name_map[first_word] = co.ticker
            broadcast_docs = pr_scanner.scan_all(ticker_set, days=DAYS, name_to_ticker=name_map)
            total = sum(len(v) for v in broadcast_docs.values())
            logger.info("Broadcast PR scan: %d press releases for %d tickers", total, len(broadcast_docs))
            return broadcast_docs
    except Exception as e:
        logger.warning("Broadcast PR scan failed: %s", e)
        return {}


def main():
    all_tickers = get_all_tickers()
    completed = get_completed_tickers()
    remaining = [t for t in all_tickers if t not in completed]

    logger.info(
        "Phase 1: %d tickers total, %d completed, %d remaining",
        len(all_tickers), len(completed), len(remaining),
    )
    logger.info("Sources: %s", SOURCE_FILTER)
    logger.info("USE_LLM=%s, DAYS=%d, RESUME=%s", USE_LLM, DAYS, RESUME)

    # Broadcast PR scan (one-time)
    broadcast_docs = scan_broadcast_pr(all_tickers)

    # Stats
    total_docs = 0
    total_claims = 0
    total_errors = 0
    start_time = time.time()

    for i, ticker in enumerate(remaining, 1):
        ticker_start = time.time()
        logger.info(
            "=== [%d/%d] %s ===",
            i + len(completed), len(all_tickers), ticker,
        )

        # Each ticker gets its own session → auto-commit on success
        session = SessionLocal()
        try:
            summary = run_ticker_pipeline(
                session, ticker,
                days=DAYS,
                dry_run=False,
                source_filter=SOURCE_FILTER,
                use_llm=USE_LLM,
                documents_only=True,
                broadcast_payloads=broadcast_docs.get(ticker),
            )
            session.commit()

            docs = summary.total_docs_inserted
            claims = summary.total_claims_extracted
            elapsed = time.time() - ticker_start
            total_docs += docs
            total_claims += claims
            total_errors += len(summary.errors)

            logger.info(
                "[%d/%d] %s done: %d docs, %d claims, %.1fs | Running total: %d docs, %d claims",
                i + len(completed), len(all_tickers), ticker,
                docs, claims, elapsed,
                total_docs, total_claims,
            )

            # Progress estimate
            if i % 10 == 0:
                avg_sec = (time.time() - start_time) / i
                eta_sec = avg_sec * (len(remaining) - i)
                eta_hrs = eta_sec / 3600
                logger.info(
                    "Progress: %d/%d (%.1f%%) | Avg %.1fs/ticker | ETA %.1f hrs",
                    i + len(completed), len(all_tickers),
                    100 * (i + len(completed)) / len(all_tickers),
                    avg_sec, eta_hrs,
                )

        except Exception as e:
            session.rollback()
            total_errors += 1
            logger.error("[%d/%d] %s FAILED: %s", i + len(completed), len(all_tickers), ticker, e)
        finally:
            session.close()

    elapsed_total = (time.time() - start_time) / 3600
    logger.info(
        "\n=== PHASE 1 COMPLETE ===\n"
        "Tickers processed: %d\n"
        "Documents inserted: %d\n"
        "Claims extracted: %d\n"
        "Errors: %d\n"
        "Total time: %.1f hours",
        len(remaining), total_docs, total_claims, total_errors, elapsed_total,
    )


if __name__ == "__main__":
    main()
