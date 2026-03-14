"""Historical backfill runner: fetch historical source data for proof runs.

Fetches price data, SEC filings, and news/PR RSS for a monitored universe
over a specified date range. Persists data so that later ingestion can
process documents in timestamp order.

Source coverage limitations are tracked and reported — gaps are explicit,
not silently skipped.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from historical_eval_config import HistoricalEvalConfig
from crud import get_or_create_company

logger = logging.getLogger(__name__)


@dataclass
class BackfillSourceResult:
    """Result for one source type across all tickers."""
    source: str
    tickers_attempted: int = 0
    tickers_succeeded: int = 0
    tickers_failed: int = 0
    rows_upserted: int = 0
    docs_fetched: int = 0
    docs_inserted: int = 0
    docs_skipped_duplicate: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class BackfillResult:
    """Aggregated result of a full historical backfill."""
    config: HistoricalEvalConfig
    source_results: list[BackfillSourceResult] = field(default_factory=list)
    total_tickers: int = 0
    total_errors: int = 0
    total_warnings: int = 0

    def to_dict(self) -> dict:
        return {
            "total_tickers": self.total_tickers,
            "total_errors": self.total_errors,
            "total_warnings": self.total_warnings,
            "sources": [
                {
                    "source": r.source,
                    "tickers_attempted": r.tickers_attempted,
                    "tickers_succeeded": r.tickers_succeeded,
                    "tickers_failed": r.tickers_failed,
                    "rows_upserted": r.rows_upserted,
                    "docs_fetched": r.docs_fetched,
                    "docs_inserted": r.docs_inserted,
                    "docs_skipped_duplicate": r.docs_skipped_duplicate,
                    "errors": r.errors,
                    "warnings": r.warnings,
                }
                for r in self.source_results
            ],
        }


def run_backfill(session: Session, config: HistoricalEvalConfig) -> BackfillResult:
    """Run historical data backfill for all configured sources.

    Steps:
      1. Ensure all universe companies exist
      2. Backfill price data (yfinance)
      3. Backfill SEC filings (EDGAR)
      4. Backfill news RSS (Google)
      5. Backfill PR RSS (PRNewswire)

    Returns structured result with per-source coverage stats.
    """
    tickers = config.effective_tickers()
    result = BackfillResult(config=config, total_tickers=len(tickers))

    # Ensure companies exist
    for ticker in tickers:
        get_or_create_company(session, ticker)
    session.flush()

    # Calculate backfill depth in days
    backfill_days = (config.backfill_end - config.backfill_start).days
    if backfill_days <= 0:
        logger.warning("Backfill window is empty: %s to %s", config.backfill_start, config.backfill_end)
        return result

    logger.info(
        "Starting backfill: %d tickers, %s to %s (%d days)",
        len(tickers), config.backfill_start, config.backfill_end, backfill_days,
    )

    # 1. Price data
    if config.backfill_prices:
        price_result = _backfill_prices(session, tickers, backfill_days, config)
        result.source_results.append(price_result)

    # 2. SEC filings
    if config.backfill_sec_filings:
        sec_result = _backfill_sec_filings(session, tickers, backfill_days, config)
        result.source_results.append(sec_result)

    # 3. News RSS
    if config.backfill_news_rss:
        news_result = _backfill_news_rss(session, tickers, backfill_days, config)
        result.source_results.append(news_result)

    # 4. PR RSS
    if config.backfill_pr_rss:
        pr_result = _backfill_pr_rss(session, tickers, backfill_days, config)
        result.source_results.append(pr_result)

    # 5. Finnhub news
    if config.backfill_finnhub:
        finnhub_result = _backfill_finnhub(session, tickers, backfill_days, config)
        result.source_results.append(finnhub_result)

    # 6. FMP (transcripts, financials, estimates)
    if config.backfill_fmp:
        fmp_result = _backfill_fmp(session, tickers, backfill_days, config)
        result.source_results.append(fmp_result)

    # 7. Alpha Vantage (earnings surprises)
    if getattr(config, 'backfill_alphavantage', True):
        av_result = _backfill_alphavantage(session, tickers, backfill_days, config)
        result.source_results.append(av_result)

    # Aggregate totals
    for sr in result.source_results:
        result.total_errors += len(sr.errors)
        result.total_warnings += len(sr.warnings)

    session.commit()
    logger.info(
        "Backfill complete: %d sources, %d errors, %d warnings",
        len(result.source_results), result.total_errors, result.total_warnings,
    )

    return result


def _backfill_prices(
    session: Session,
    tickers: list[str],
    days: int,
    config: HistoricalEvalConfig,
) -> BackfillSourceResult:
    """Backfill price data from yfinance."""
    result = BackfillSourceResult(source="price_daily")

    try:
        from connectors.yfinance_prices import YFinancePriceUpdater
        updater = YFinancePriceUpdater()
    except ImportError:
        result.errors.append("yfinance not available")
        return result

    for ticker in tickers:
        result.tickers_attempted += 1
        try:
            r = updater.update(session, ticker, days=days)
            result.rows_upserted += r.rows_upserted
            if r.errors:
                result.errors.extend(r.errors)
                result.tickers_failed += 1
            else:
                result.tickers_succeeded += 1
                if r.rows_upserted == 0:
                    result.warnings.append(f"{ticker}: no price data returned")
        except Exception as e:
            result.tickers_failed += 1
            result.errors.append(f"{ticker}: {e}")

    # Also backfill benchmark ticker
    if config.benchmark_ticker not in tickers:
        try:
            get_or_create_company(session, config.benchmark_ticker)
            r = updater.update(session, config.benchmark_ticker, days=days)
            result.rows_upserted += r.rows_upserted
        except Exception as e:
            result.warnings.append(f"Benchmark {config.benchmark_ticker}: {e}")

    logger.info("Price backfill: %d tickers, %d rows upserted", result.tickers_attempted, result.rows_upserted)
    return result


def _backfill_sec_filings(
    session: Session,
    tickers: list[str],
    days: int,
    config: HistoricalEvalConfig,
) -> BackfillSourceResult:
    """Backfill SEC filings from EDGAR."""
    result = BackfillSourceResult(source="sec_filings")

    try:
        from connectors.sec_edgar import SECEdgarConnector
        from document_ingestion_service import ingest_document_payload
        from dedupe import is_duplicate_document
        connector = SECEdgarConnector()
    except ImportError as e:
        result.errors.append(f"SEC connector not available: {e}")
        return result

    for ticker in tickers:
        result.tickers_attempted += 1
        try:
            payloads = connector.fetch(ticker, days=days)
            result.docs_fetched += len(payloads)

            inserted = 0
            for payload in payloads:
                if is_duplicate_document(session, payload):
                    result.docs_skipped_duplicate += 1
                    continue
                try:
                    ingest_document_payload(session, payload, ticker, use_llm=config.use_llm)
                    inserted += 1
                except Exception as e:
                    result.errors.append(f"{ticker} doc ingest: {e}")

            result.docs_inserted += inserted
            result.tickers_succeeded += 1
        except Exception as e:
            result.tickers_failed += 1
            result.errors.append(f"{ticker}: {e}")

    if days < 365:
        result.warnings.append(
            f"SEC backfill depth ({days}d) may miss older filings. "
            f"10-K backfill typically needs 1095d."
        )

    logger.info(
        "SEC backfill: %d tickers, %d docs fetched, %d inserted, %d dupes",
        result.tickers_attempted, result.docs_fetched, result.docs_inserted,
        result.docs_skipped_duplicate,
    )
    return result


def _backfill_news_rss(
    session: Session,
    tickers: list[str],
    days: int,
    config: HistoricalEvalConfig,
) -> BackfillSourceResult:
    """Backfill news from Google RSS. Coverage limited to ~7 days retention."""
    result = BackfillSourceResult(source="news_google_rss")

    if days > 7:
        result.warnings.append(
            f"Google News RSS retains only ~7 days of articles. "
            f"Requested {days}d backfill will have significant gaps."
        )

    try:
        from connectors.google_rss import GoogleRSSConnector
        from document_ingestion_service import ingest_document_payload
        from dedupe import is_duplicate_document
        connector = GoogleRSSConnector()
    except ImportError as e:
        result.errors.append(f"Google RSS connector not available: {e}")
        return result

    for ticker in tickers:
        result.tickers_attempted += 1
        try:
            payloads = connector.fetch(ticker, days=min(days, 7))
            result.docs_fetched += len(payloads)

            for payload in payloads:
                if is_duplicate_document(session, payload):
                    result.docs_skipped_duplicate += 1
                    continue
                try:
                    ingest_document_payload(session, payload, ticker, use_llm=config.use_llm)
                    result.docs_inserted += 1
                except Exception as e:
                    result.errors.append(f"{ticker} news ingest: {e}")

            result.tickers_succeeded += 1
        except Exception as e:
            result.tickers_failed += 1
            result.errors.append(f"{ticker}: {e}")

    logger.info(
        "News RSS backfill: %d tickers, %d docs fetched, %d inserted",
        result.tickers_attempted, result.docs_fetched, result.docs_inserted,
    )
    return result


def _backfill_pr_rss(
    session: Session,
    tickers: list[str],
    days: int,
    config: HistoricalEvalConfig,
) -> BackfillSourceResult:
    """Backfill press releases from PR Newswire RSS. Limited to ~90 days."""
    result = BackfillSourceResult(source="press_release_rss")

    if days > 90:
        result.warnings.append(
            f"PR Newswire RSS retains ~90 days. "
            f"Requested {days}d backfill will have gaps beyond 90d."
        )

    try:
        from connectors.pr_rss import PRRSSConnector
        from document_ingestion_service import ingest_document_payload
        from dedupe import is_duplicate_document
        connector = PRRSSConnector()
    except ImportError as e:
        result.errors.append(f"PR RSS connector not available: {e}")
        return result

    for ticker in tickers:
        result.tickers_attempted += 1
        try:
            payloads = connector.fetch(ticker, days=min(days, 90))
            result.docs_fetched += len(payloads)

            for payload in payloads:
                if is_duplicate_document(session, payload):
                    result.docs_skipped_duplicate += 1
                    continue
                try:
                    ingest_document_payload(session, payload, ticker, use_llm=config.use_llm)
                    result.docs_inserted += 1
                except Exception as e:
                    result.errors.append(f"{ticker} PR ingest: {e}")

            result.tickers_succeeded += 1
        except Exception as e:
            result.tickers_failed += 1
            result.errors.append(f"{ticker}: {e}")

    logger.info(
        "PR RSS backfill: %d tickers, %d docs fetched, %d inserted",
        result.tickers_attempted, result.docs_fetched, result.docs_inserted,
    )
    return result


def _backfill_finnhub(
    session: Session,
    tickers: list[str],
    days: int,
    config: HistoricalEvalConfig,
) -> BackfillSourceResult:
    """Backfill news from Finnhub. 1-year archive with ticker filtering."""
    result = BackfillSourceResult(source="news_finnhub")

    try:
        from connectors.finnhub_connector import FinnhubNewsConnector
        from document_ingestion_service import ingest_document_payload
        from dedupe import is_duplicate_document
        connector = FinnhubNewsConnector()
        if not connector.available:
            result.warnings.append("Finnhub: FINNHUB_API_KEY not set, skipping")
            return result
    except ImportError as e:
        result.errors.append(f"Finnhub connector not available: {e}")
        return result

    for ticker in tickers:
        result.tickers_attempted += 1
        try:
            payloads = connector.fetch(ticker, days=min(days, 365))
            result.docs_fetched += len(payloads)

            for payload in payloads:
                if is_duplicate_document(session, payload):
                    result.docs_skipped_duplicate += 1
                    continue
                try:
                    ingest_document_payload(session, payload, ticker, use_llm=config.use_llm)
                    result.docs_inserted += 1
                except Exception as e:
                    result.errors.append(f"{ticker} finnhub ingest: {e}")

            result.tickers_succeeded += 1
        except Exception as e:
            result.tickers_failed += 1
            result.errors.append(f"{ticker}: {e}")

    logger.info(
        "Finnhub backfill: %d tickers, %d docs fetched, %d inserted",
        result.tickers_attempted, result.docs_fetched, result.docs_inserted,
    )
    return result


def _backfill_fmp(
    session: Session,
    tickers: list[str],
    days: int,
    config: HistoricalEvalConfig,
) -> BackfillSourceResult:
    """Backfill FMP data: transcripts, financials, estimates."""
    result = BackfillSourceResult(source="fmp")

    try:
        from connectors.fmp_connector import (
            FMPTranscriptConnector, FMPFinancialsConnector, FMPEstimatesConnector,
        )
        from document_ingestion_service import ingest_document_payload
        from dedupe import is_duplicate_document

        connectors = []
        for ConnCls in (FMPTranscriptConnector, FMPFinancialsConnector, FMPEstimatesConnector):
            conn = ConnCls()
            if conn.available:
                connectors.append(conn)

        if not connectors:
            result.warnings.append("FMP: FMP_API_KEY not set, skipping")
            return result
    except ImportError as e:
        result.errors.append(f"FMP connector not available: {e}")
        return result

    for ticker in tickers:
        result.tickers_attempted += 1
        try:
            for connector in connectors:
                payloads = connector.fetch(ticker, days=min(days, 365))
                result.docs_fetched += len(payloads)

                for payload in payloads:
                    if is_duplicate_document(session, payload):
                        result.docs_skipped_duplicate += 1
                        continue
                    try:
                        ingest_document_payload(session, payload, ticker, use_llm=config.use_llm)
                        result.docs_inserted += 1
                    except Exception as e:
                        result.errors.append(f"{ticker} fmp ingest: {e}")

            result.tickers_succeeded += 1
        except Exception as e:
            result.tickers_failed += 1
            result.errors.append(f"{ticker}: {e}")

    logger.info(
        "FMP backfill: %d tickers, %d docs fetched, %d inserted",
        result.tickers_attempted, result.docs_fetched, result.docs_inserted,
    )
    return result


def _backfill_alphavantage(
    session: Session,
    tickers: list[str],
    days: int,
    config: HistoricalEvalConfig,
) -> BackfillSourceResult:
    """Backfill Alpha Vantage earnings surprise data."""
    result = BackfillSourceResult(source="alphavantage")

    try:
        from connectors.alphavantage_connector import AlphaVantageEarningsConnector
        from document_ingestion_service import ingest_document_payload
        from dedupe import is_duplicate_document

        connector = AlphaVantageEarningsConnector()
        if not connector.available:
            result.warnings.append("Alpha Vantage: ALPHAVANTAGE_API_KEY not set, skipping")
            return result
    except ImportError as e:
        result.errors.append(f"Alpha Vantage connector not available: {e}")
        return result

    for ticker in tickers:
        result.tickers_attempted += 1
        try:
            payloads = connector.fetch(ticker, days=min(days, 365))
            result.docs_fetched += len(payloads)

            for payload in payloads:
                if is_duplicate_document(session, payload):
                    result.docs_skipped_duplicate += 1
                    continue
                try:
                    ingest_document_payload(session, payload, ticker, use_llm=config.use_llm)
                    result.docs_inserted += 1
                except Exception as e:
                    result.errors.append(f"{ticker} alphavantage ingest: {e}")

            result.tickers_succeeded += 1
        except Exception as e:
            result.tickers_failed += 1
            result.errors.append(f"{ticker}: {e}")

    logger.info(
        "Alpha Vantage backfill: %d tickers, %d docs fetched, %d inserted",
        result.tickers_attempted, result.docs_fetched, result.docs_inserted,
    )
    return result
