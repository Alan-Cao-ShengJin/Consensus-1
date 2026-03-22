"""Batch valuation: populate earnings estimates + compute valuation for all tickers.

Step 1: Fetch consensus estimates from FMP → persist to earnings_estimates table
Step 2: Compute forward PE z-score + peer comparison → write valuation_gap_pct to theses

Usage:
    python scripts/run_valuation_batch.py [--skip-estimates]
"""
import logging
import sys
import time
from datetime import date

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger("valuation_batch")

for name in ("httpx", "httpcore", "urllib3"):
    logging.getLogger(name).setLevel(logging.WARNING)

sys.path.insert(0, ".")

from db import get_session, SessionLocal
from sqlalchemy import text


def get_all_tickers():
    with get_session() as s:
        return s.execute(
            text("SELECT ticker FROM companies ORDER BY ticker")
        ).scalars().all()


def step1_populate_estimates(tickers):
    """Fetch FMP estimates and persist to earnings_estimates table."""
    from connectors.fmp_connector import FMPEstimatesConnector

    connector = FMPEstimatesConnector()
    if not connector.available:
        logger.error("FMP API key not set — cannot fetch estimates")
        return

    total = 0
    errors = 0
    start = time.time()

    for i, ticker in enumerate(tickers, 1):
        session = SessionLocal()
        try:
            count = connector.persist_estimates(session, ticker, days=365 * 5)
            session.commit()
            total += count
            if i % 50 == 0:
                elapsed = time.time() - start
                logger.info(
                    "Estimates: %d/%d tickers, %d rows total, %.0fs elapsed",
                    i, len(tickers), total, elapsed,
                )
        except Exception as e:
            session.rollback()
            errors += 1
            logger.warning("Estimates failed for %s: %s", ticker, e)
        finally:
            session.close()

    logger.info(
        "Step 1 done: %d estimate rows for %d tickers (%d errors)",
        total, len(tickers), errors,
    )


def step2_compute_valuations(tickers):
    """Compute valuation for all tickers with active theses."""
    from auto_valuation import update_thesis_valuation

    as_of = date(2025, 12, 31)  # Valuation as of end of Dec 2025
    total = 0
    computed = 0
    errors = 0

    for i, ticker in enumerate(tickers, 1):
        session = SessionLocal()
        try:
            result = update_thesis_valuation(session, ticker, as_of)
            session.commit()
            total += 1
            if result and result.valuation_gap_pct is not None:
                computed += 1
            if i % 50 == 0:
                logger.info(
                    "Valuation: %d/%d tickers, %d computed",
                    i, len(tickers), computed,
                )
        except Exception as e:
            session.rollback()
            errors += 1
            logger.warning("Valuation failed for %s: %s", ticker, e)
        finally:
            session.close()

    logger.info(
        "Step 2 done: %d/%d tickers valued (%d errors)",
        computed, total, errors,
    )


def main():
    tickers = get_all_tickers()
    logger.info("Valuation batch: %d tickers", len(tickers))

    skip_estimates = "--skip-estimates" in sys.argv

    if not skip_estimates:
        logger.info("=== Step 1: Populate earnings estimates from FMP ===")
        step1_populate_estimates(tickers)
    else:
        logger.info("Skipping Step 1 (--skip-estimates)")

    logger.info("=== Step 2: Compute valuations ===")
    step2_compute_valuations(tickers)

    # Summary
    with get_session() as s:
        est_count = s.execute(text("SELECT COUNT(*) FROM earnings_estimates")).scalar()
        val_count = s.execute(
            text("SELECT COUNT(*) FROM theses WHERE valuation_gap_pct IS NOT NULL AND status_active = 1")
        ).scalar()
        logger.info(
            "\n=== SUMMARY ===\n"
            "Earnings estimates: %d rows\n"
            "Theses with valuation: %d",
            est_count, val_count,
        )


if __name__ == "__main__":
    main()
