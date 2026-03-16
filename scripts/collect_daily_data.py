#!/usr/bin/env python
"""Daily data collection script: accumulates data for future proof runs.

Run this daily (e.g., via cron/Task Scheduler) to continuously archive:
  - Prices for all tracked tickers (yfinance)
  - VIX and DXY macro indicators
  - SEC filings (10-K, 10-Q, 8-K)
  - Finnhub news articles
  - Google News RSS headlines
  - Macro news RSS headlines
  - PR Newswire press releases

Data is persisted to consensus.db so that historical proof runs can use it
months/years later. Without daily collection, RSS-based sources (Google News,
PR Newswire) are lost after ~7-90 days.

Usage:
    python scripts/collect_daily_data.py                  # collect all
    python scripts/collect_daily_data.py --prices-only    # just prices
    python scripts/collect_daily_data.py --no-finnhub     # skip finnhub (slow)
    python scripts/collect_daily_data.py --days 3         # lookback 3 days

Schedule (Windows Task Scheduler):
    Program: python
    Arguments: scripts/collect_daily_data.py
    Start in: C:\\Users\\Admin\\Desktop\\Consensus-1
    Trigger: Daily at 6:00 PM EST (after market close)
"""
from __future__ import annotations

import argparse
import logging
import sys
import os
from datetime import date, timedelta

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import get_session
from crud import get_or_create_company

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

# Default universe: same as proof pack
DEFAULT_TICKERS = [
    "NVDA", "AMD", "AVGO", "QCOM", "INTC",
    "MSFT", "GOOGL", "AMZN", "META", "CRM",
    "PLTR", "NOW", "CRWD", "AAPL", "TSLA",
    "SPY",  # benchmark
]


def collect_prices(session, tickers: list[str], days: int = 7):
    """Collect daily prices from yfinance."""
    from connectors.yfinance_prices import YFinancePriceUpdater
    updater = YFinancePriceUpdater()
    total = 0
    for ticker in tickers:
        get_or_create_company(session, ticker)
        r = updater.update(session, ticker, days=days)
        total += r.rows_upserted
        if r.errors:
            logger.error("Price error for %s: %s", ticker, r.errors)
    logger.info("Prices: %d rows upserted for %d tickers", total, len(tickers))
    return total


def collect_macro(session, days: int = 7):
    """Collect VIX, DXY macro indicators."""
    from connectors.vix_connector import VIXUpdater, DXYUpdater
    total = 0

    vix = VIXUpdater()
    r = vix.update(session, days=days)
    total += r.rows_upserted
    logger.info("VIX: %d rows upserted", r.rows_upserted)

    dxy = DXYUpdater()
    r = dxy.update(session, days=days)
    total += r.rows_upserted
    logger.info("DXY: %d rows upserted", r.rows_upserted)

    return total


def collect_sec_filings(session, tickers: list[str], days: int = 7):
    """Collect SEC filings from EDGAR."""
    from connectors.sec_edgar import SECEdgarConnector
    from document_ingestion_service import ingest_document_payload
    from dedupe import is_duplicate_document

    connector = SECEdgarConnector()
    total_fetched = 0
    total_inserted = 0

    for ticker in tickers:
        try:
            payloads = connector.fetch(ticker, days=days)
            total_fetched += len(payloads)
            for payload in payloads:
                if is_duplicate_document(session, payload):
                    continue
                try:
                    ingest_document_payload(session, payload, ticker)
                    total_inserted += 1
                except Exception as e:
                    logger.error("SEC ingest error for %s: %s", ticker, e)
        except Exception as e:
            logger.error("SEC fetch error for %s: %s", ticker, e)

    logger.info("SEC: %d fetched, %d inserted", total_fetched, total_inserted)
    return total_inserted


def collect_news_rss(session, tickers: list[str], days: int = 7):
    """Collect news headlines from Google News RSS."""
    from connectors.google_rss import GoogleRSSConnector
    from document_ingestion_service import ingest_document_payload
    from dedupe import is_duplicate_document

    connector = GoogleRSSConnector()
    total_fetched = 0
    total_inserted = 0

    for ticker in tickers:
        try:
            payloads = connector.fetch(ticker, days=min(days, 7))
            total_fetched += len(payloads)
            for payload in payloads:
                if is_duplicate_document(session, payload):
                    continue
                try:
                    ingest_document_payload(session, payload, ticker)
                    total_inserted += 1
                except Exception as e:
                    logger.error("News ingest error for %s: %s", ticker, e)
        except Exception as e:
            logger.error("News fetch error for %s: %s", ticker, e)

    logger.info("News RSS: %d fetched, %d inserted", total_fetched, total_inserted)
    return total_inserted


def collect_macro_news(session, days: int = 7):
    """Collect macro news headlines from Google News RSS."""
    from connectors.macro_rss import MacroNewsRSSConnector
    from document_ingestion_service import ingest_document_payload
    from dedupe import is_duplicate_document

    connector = MacroNewsRSSConnector()
    total_inserted = 0

    try:
        payloads = connector.fetch(days=days)
        for payload in payloads:
            if is_duplicate_document(session, payload):
                continue
            try:
                get_or_create_company(session, "MACRO")
                ingest_document_payload(session, payload, "MACRO")
                total_inserted += 1
            except Exception as e:
                logger.error("Macro news ingest error: %s", e)
    except Exception as e:
        logger.error("Macro news fetch error: %s", e)

    logger.info("Macro news: %d inserted", total_inserted)
    return total_inserted


def collect_finnhub(session, tickers: list[str], days: int = 7):
    """Collect news from Finnhub API."""
    from connectors.finnhub_connector import FinnhubNewsConnector
    from document_ingestion_service import ingest_document_payload
    from dedupe import is_duplicate_document

    connector = FinnhubNewsConnector()
    if not connector.available:
        logger.info("Finnhub: FINNHUB_API_KEY not set, skipping")
        return 0

    total_fetched = 0
    total_inserted = 0

    for ticker in tickers:
        try:
            payloads = connector.fetch(ticker, days=days)
            total_fetched += len(payloads)
            for payload in payloads:
                if is_duplicate_document(session, payload):
                    continue
                try:
                    ingest_document_payload(session, payload, ticker)
                    total_inserted += 1
                except Exception as e:
                    logger.error("Finnhub ingest error for %s: %s", ticker, e)
        except Exception as e:
            logger.error("Finnhub fetch error for %s: %s", ticker, e)

    logger.info("Finnhub: %d fetched, %d inserted", total_fetched, total_inserted)
    return total_inserted


def collect_pr_rss(session, tickers: list[str], days: int = 7):
    """Collect press releases from PR Newswire RSS."""
    from connectors.pr_rss import PRRSSConnector
    from document_ingestion_service import ingest_document_payload
    from dedupe import is_duplicate_document

    connector = PRRSSConnector()
    total_fetched = 0
    total_inserted = 0

    for ticker in tickers:
        try:
            payloads = connector.fetch(ticker, days=min(days, 90))
            total_fetched += len(payloads)
            for payload in payloads:
                if is_duplicate_document(session, payload):
                    continue
                try:
                    ingest_document_payload(session, payload, ticker)
                    total_inserted += 1
                except Exception as e:
                    logger.error("PR ingest error for %s: %s", ticker, e)
        except Exception as e:
            logger.error("PR fetch error for %s: %s", ticker, e)

    logger.info("PR RSS: %d fetched, %d inserted", total_fetched, total_inserted)
    return total_inserted


def main():
    parser = argparse.ArgumentParser(description="Daily data collection for Consensus-1")
    parser.add_argument("--days", type=int, default=7, help="Lookback days (default 7)")
    parser.add_argument("--tickers", type=str, default=None, help="Comma-separated tickers (default: proof universe)")
    parser.add_argument("--prices-only", action="store_true", help="Only collect prices + macro")
    parser.add_argument("--no-finnhub", action="store_true", help="Skip Finnhub (slow due to rate limits)")
    parser.add_argument("--no-macro-news", action="store_true", help="Skip macro news RSS")
    args = parser.parse_args()

    tickers = args.tickers.split(",") if args.tickers else DEFAULT_TICKERS
    days = args.days

    print(f"Daily data collection: {len(tickers)} tickers, {days}d lookback")
    print(f"Date: {date.today()}")
    print()

    with get_session() as session:
        # Always collect prices and macro
        print("Collecting prices...")
        collect_prices(session, tickers, days)
        print("Collecting VIX/DXY...")
        collect_macro(session, days)

        if args.prices_only:
            print("Done (prices-only mode)")
            return

        # Document sources
        print("Collecting SEC filings...")
        collect_sec_filings(session, tickers, days)

        print("Collecting news RSS...")
        collect_news_rss(session, tickers, days)

        print("Collecting PR RSS...")
        collect_pr_rss(session, tickers, days)

        if not args.no_macro_news:
            print("Collecting macro news...")
            collect_macro_news(session, days)

        if not args.no_finnhub:
            print("Collecting Finnhub news...")
            collect_finnhub(session, tickers, days)

    print()
    print("Daily collection complete.")


if __name__ == "__main__":
    main()
