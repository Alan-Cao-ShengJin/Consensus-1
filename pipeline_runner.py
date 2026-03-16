"""Pipeline runner: orchestrates one ticker-run across document and non-document sources.

Two lanes:
  1. Document sources: fetch -> dedupe -> insert -> extract claims -> thesis update
  2. Non-document sources: prices, calendar, ticker info -> dedicated storage

One thesis update per ticker-run (not per document).
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import select
from sqlalchemy.orm import Session

from models import Thesis
from connectors.base import DocumentConnector, NonDocumentUpdater
from connectors.sec_edgar import SECEdgarConnector
from connectors.google_rss import GoogleRSSConnector
from connectors.pr_rss import PRRSSConnector
from connectors.newsapi_connector import NewsAPIConnector
from connectors.yfinance_prices import YFinancePriceUpdater
from connectors.yfinance_calendar import YFinanceCalendarUpdater
from connectors.yfinance_ticker_info import YFinanceTickerInfoUpdater
from dedupe import is_duplicate_document
from document_ingestion_service import ingest_document_payload
from crud import get_or_create_company

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Summary dataclasses
# ---------------------------------------------------------------------------

@dataclass
class SourceRunSummary:
    """Summary for one source within a ticker-run."""
    source: str
    ticker: str
    docs_fetched: int = 0
    docs_inserted: int = 0
    duplicates_skipped: int = 0
    claims_extracted: int = 0
    prices_upserted: int = 0
    checkpoints_upserted: int = 0
    company_fields_updated: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass
class TickerRunSummary:
    """Summary for a complete ticker-run across all sources."""
    ticker: str
    started_at: datetime = field(default_factory=datetime.utcnow)
    finished_at: Optional[datetime] = None
    source_summaries: list[SourceRunSummary] = field(default_factory=list)
    thesis_updated: bool = False
    thesis_update_result: Optional[dict] = None
    total_docs_fetched: int = 0
    total_docs_inserted: int = 0
    total_duplicates_skipped: int = 0
    total_claims_extracted: int = 0
    errors: list[str] = field(default_factory=list)

    def finalize(self):
        self.finished_at = datetime.utcnow()
        self.total_docs_fetched = sum(s.docs_fetched for s in self.source_summaries)
        self.total_docs_inserted = sum(s.docs_inserted for s in self.source_summaries)
        self.total_duplicates_skipped = sum(s.duplicates_skipped for s in self.source_summaries)
        self.total_claims_extracted = sum(s.claims_extracted for s in self.source_summaries)

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "total_docs_fetched": self.total_docs_fetched,
            "total_docs_inserted": self.total_docs_inserted,
            "total_duplicates_skipped": self.total_duplicates_skipped,
            "total_claims_extracted": self.total_claims_extracted,
            "thesis_updated": self.thesis_updated,
            "errors": self.errors,
            "sources": [
                {
                    "source": s.source,
                    "docs_fetched": s.docs_fetched,
                    "docs_inserted": s.docs_inserted,
                    "duplicates_skipped": s.duplicates_skipped,
                    "claims_extracted": s.claims_extracted,
                    "prices_upserted": s.prices_upserted,
                    "checkpoints_upserted": s.checkpoints_upserted,
                    "company_fields_updated": s.company_fields_updated,
                    "errors": s.errors,
                }
                for s in self.source_summaries
            ],
        }


# ---------------------------------------------------------------------------
# Connector registry
# ---------------------------------------------------------------------------

def _build_document_connectors(source_filter: Optional[list[str]] = None) -> list[DocumentConnector]:
    """Instantiate enabled document connectors, optionally filtered by source key."""
    all_connectors: list[DocumentConnector] = [
        SECEdgarConnector(),
        GoogleRSSConnector(),
        PRRSSConnector(),
    ]

    # NewsAPI: only if key is available
    newsapi = NewsAPIConnector()
    if newsapi.available:
        all_connectors.append(newsapi)

    # Finnhub news
    from connectors.finnhub_connector import FinnhubNewsConnector
    finnhub = FinnhubNewsConnector()
    if finnhub.available:
        all_connectors.append(finnhub)

    # FMP connectors (transcripts, financials, estimates, news)
    from connectors.fmp_connector import (
        FMPTranscriptConnector, FMPFinancialsConnector, FMPEstimatesConnector,
        FMPNewsConnector,
    )
    for ConnCls in (FMPTranscriptConnector, FMPFinancialsConnector, FMPEstimatesConnector,
                    FMPNewsConnector):
        conn = ConnCls()
        if conn.available:
            all_connectors.append(conn)

    # Alpha Vantage connector (earnings surprises)
    from connectors.alphavantage_connector import AlphaVantageEarningsConnector
    av = AlphaVantageEarningsConnector()
    if av.available:
        all_connectors.append(av)

    # DefeatBeta connector (free earnings transcripts from HuggingFace)
    from connectors.defeatbeta_connector import DefeatBetaTranscriptConnector
    db = DefeatBetaTranscriptConnector()
    if db.available:
        all_connectors.append(db)

    # Macro news RSS (broad market headlines)
    from connectors.macro_rss import MacroNewsRSSConnector
    all_connectors.append(MacroNewsRSSConnector())

    if source_filter:
        return [c for c in all_connectors if c.source_key in source_filter]
    return all_connectors


def _build_non_document_updaters(source_filter: Optional[list[str]] = None) -> list[NonDocumentUpdater]:
    """Instantiate enabled non-document updaters, optionally filtered."""
    from connectors.vix_connector import VIXUpdater, DXYUpdater
    from connectors.fred_connector import FREDMacroUpdater

    all_updaters: list[NonDocumentUpdater] = [
        YFinancePriceUpdater(),
        YFinanceCalendarUpdater(),
        YFinanceTickerInfoUpdater(),
        VIXUpdater(),
        DXYUpdater(),
    ]
    # FRED connector: only if API key available
    fred = FREDMacroUpdater()
    if fred.available:
        all_updaters.append(fred)
    if source_filter:
        return [u for u in all_updaters if u.source_key in source_filter]
    return all_updaters


# ---------------------------------------------------------------------------
# Main pipeline runner
# ---------------------------------------------------------------------------

def run_ticker_pipeline(
    session: Session,
    ticker: str,
    *,
    days: int = 7,
    dry_run: bool = False,
    source_filter: Optional[list[str]] = None,
    use_llm: bool = False,
    documents_only: bool = False,
    non_documents_only: bool = False,
) -> TickerRunSummary:
    """Run the full pipeline for one ticker.

    Steps:
      1. Ensure company exists
      2. Run non-document updaters (prices, calendar, enrichment)
      3. Fetch document payloads from all enabled connectors
      4. Dedupe against existing documents
      5. Insert new documents
      6. Extract claims from new documents
      7. If thesis exists and net new claims, run one thesis update
      8. Return structured summary

    Args:
        session: SQLAlchemy session.
        ticker: Company ticker symbol.
        days: Backfill depth in days.
        dry_run: If True, fetch and dedupe but don't persist.
        source_filter: Optional list of source keys to restrict which connectors run.
        use_llm: Use LLM for claim extraction (default: stub).
        documents_only: Only run document sources.
        non_documents_only: Only run non-document sources.
    """
    summary = TickerRunSummary(ticker=ticker)

    # Ensure company exists
    if not dry_run:
        get_or_create_company(session, ticker)

    # --- Lane 2: Non-document updaters ---
    if not documents_only:
        updaters = _build_non_document_updaters(source_filter)
        for updater in updaters:
            try:
                result = updater.update(session, ticker, days=days, dry_run=dry_run)
                src_summary = SourceRunSummary(source=updater.source_key, ticker=ticker)
                src_summary.prices_upserted = result.rows_upserted if "price" in updater.source_key else 0
                src_summary.checkpoints_upserted = result.rows_upserted if "calendar" in updater.source_key else 0
                src_summary.company_fields_updated = result.rows_upserted if "ticker" in updater.source_key else 0
                src_summary.errors = result.errors
                summary.source_summaries.append(src_summary)
            except Exception as e:
                logger.error("Non-document updater %s failed for %s: %s", updater.source_key, ticker, e)
                summary.errors.append(f"{updater.source_key}: {e}")

    # --- Lane 1: Document sources ---
    all_new_claim_ids: list[int] = []

    if not non_documents_only:
        connectors = _build_document_connectors(source_filter)
        for connector in connectors:
            src_summary = SourceRunSummary(source=connector.source_key, ticker=ticker)

            try:
                payloads = connector.fetch(ticker, days=days)
                src_summary.docs_fetched = len(payloads)
            except Exception as e:
                logger.error("Connector %s failed for %s: %s", connector.source_key, ticker, e)
                src_summary.errors.append(str(e))
                summary.source_summaries.append(src_summary)
                continue

            for payload in payloads:
                if is_duplicate_document(session, payload):
                    src_summary.duplicates_skipped += 1
                    continue

                if dry_run:
                    src_summary.docs_inserted += 1
                    continue

                try:
                    result = ingest_document_payload(session, payload, ticker, use_llm=use_llm)
                    src_summary.docs_inserted += 1
                    src_summary.claims_extracted += len(result.claim_ids)
                    all_new_claim_ids.extend(result.claim_ids)
                except Exception as e:
                    logger.error("Failed to process document from %s for %s: %s", connector.source_key, ticker, e)
                    src_summary.errors.append(str(e))

            summary.source_summaries.append(src_summary)

    # --- Thesis update: one per ticker-run ---
    if not dry_run and all_new_claim_ids and not non_documents_only:
        thesis = session.scalars(
            select(Thesis).where(
                Thesis.company_ticker == ticker,
                Thesis.status_active == True,
            ).order_by(Thesis.updated_at.desc()).limit(1)
        ).first()

        if thesis:
            try:
                from thesis_update_service import update_thesis_from_claims
                result = update_thesis_from_claims(
                    session, thesis.id, all_new_claim_ids, use_llm=use_llm,
                )
                summary.thesis_updated = True
                summary.thesis_update_result = result
                logger.info(
                    "Thesis update for %s: %s -> %s (score: %.1f -> %.1f)",
                    ticker, result["before_state"], result["after_state"],
                    result["before_score"], result["after_score"],
                )
            except Exception as e:
                logger.error("Thesis update failed for %s: %s", ticker, e)
                summary.errors.append(f"thesis_update: {e}")

    summary.finalize()
    return summary


def run_pipeline(
    session: Session,
    tickers: list[str],
    *,
    days: int = 7,
    dry_run: bool = False,
    source_filter: Optional[list[str]] = None,
    use_llm: bool = False,
    documents_only: bool = False,
    non_documents_only: bool = False,
) -> list[TickerRunSummary]:
    """Run the pipeline for multiple tickers sequentially."""
    summaries = []
    for ticker in tickers:
        logger.info("=== Pipeline run: %s (days=%d, dry_run=%s) ===", ticker, days, dry_run)
        try:
            s = run_ticker_pipeline(
                session, ticker,
                days=days, dry_run=dry_run, source_filter=source_filter,
                use_llm=use_llm, documents_only=documents_only,
                non_documents_only=non_documents_only,
            )
            summaries.append(s)
        except Exception as e:
            logger.error("Pipeline failed for %s: %s", ticker, e)
            err_summary = TickerRunSummary(ticker=ticker)
            err_summary.errors.append(str(e))
            err_summary.finalize()
            summaries.append(err_summary)

    return summaries
