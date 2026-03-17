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
    # Note: PRRSSConnector is handled as a broadcast source in run_pipeline()
    # (fetched once, matched against all tickers) — not per-ticker here.
    all_connectors: list[DocumentConnector] = [
        SECEdgarConnector(),
        GoogleRSSConnector(),
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
    from connectors.vix_connector import VIXUpdater, DXYUpdater, OilUpdater, CreditSpreadUpdater
    from connectors.fred_connector import FREDMacroUpdater

    all_updaters: list[NonDocumentUpdater] = [
        YFinancePriceUpdater(),
        YFinanceCalendarUpdater(),
        YFinanceTickerInfoUpdater(),
        VIXUpdater(),
        DXYUpdater(),
        OilUpdater(),
        CreditSpreadUpdater(),
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
    use_llm: bool = True,
    documents_only: bool = False,
    non_documents_only: bool = False,
    broadcast_payloads: Optional[list] = None,
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
        use_llm: Use LLM for claim extraction.
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

    # --- Forward estimates: refresh consensus EPS before earnings season ---
    if not dry_run and not documents_only:
        try:
            from connectors.alphavantage_connector import persist_forward_estimate
            est = persist_forward_estimate(session, ticker)
            if est:
                logger.info("Forward estimate for %s: EPS $%.2f (reporting %s)",
                            ticker, est.estimated_eps, est.earnings_date)
        except Exception as e:
            logger.debug("Forward estimate refresh skipped for %s: %s", ticker, e)

    # --- Lane 1: Document sources ---
    all_new_claim_ids: list[int] = []

    if not non_documents_only:
        # Ingest broadcast payloads (PR RSS scanned at pipeline level)
        if broadcast_payloads:
            src_summary = SourceRunSummary(source="press_release_rss", ticker=ticker)
            src_summary.docs_fetched = len(broadcast_payloads)
            for payload in broadcast_payloads:
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
                    logger.error("Failed to ingest broadcast PR for %s: %s", ticker, e)
                    src_summary.errors.append(str(e))
            summary.source_summaries.append(src_summary)

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
    use_llm: bool = True,
    documents_only: bool = False,
    non_documents_only: bool = False,
) -> list[TickerRunSummary]:
    """Run the pipeline for multiple tickers sequentially.

    Broadcast sources (PR RSS) are scanned once upfront against the full
    ticker universe, then results are injected into per-ticker runs.
    """
    # --- Broadcast sources: scan once, match all tickers ---
    broadcast_docs: dict[str, list] = {}
    if not non_documents_only and (not source_filter or "press_release_rss" in source_filter):
        try:
            from models import Company
            pr_scanner = PRRSSConnector()
            ticker_set = set(tickers)
            # Build company name → ticker map for matching "NVIDIA" → NVDA
            name_map: dict[str, str] = {}
            companies = session.scalars(
                select(Company).where(Company.ticker.in_(tickers))
            ).all()
            for co in companies:
                if co.name and len(co.name) >= 4:  # skip very short names
                    # Use the key part of the name (first word, or full if short)
                    name_upper = co.name.upper()
                    name_map[name_upper] = co.ticker
                    # Also add first word for multi-word names (e.g., "NVIDIA CORPORATION" → "NVIDIA")
                    first_word = name_upper.split()[0] if " " in name_upper else ""
                    if first_word and len(first_word) >= 5:
                        name_map[first_word] = co.ticker
            broadcast_docs = pr_scanner.scan_all(ticker_set, days=days, name_to_ticker=name_map)
            total = sum(len(v) for v in broadcast_docs.values())
            if total:
                logger.info("Broadcast PR scan: %d press releases for %d tickers", total, len(broadcast_docs))
        except Exception as e:
            logger.warning("Broadcast PR scan failed (continuing): %s", e)

    # --- Macro shock scan: detect shocks and compute overlay ---
    macro_overlay = None
    if not dry_run:
        try:
            from macro_shock import run_macro_shock_scan
            macro_overlay = run_macro_shock_scan(session)
            if macro_overlay.active:
                logger.warning("Macro shock scan: %s", macro_overlay.summary())
        except Exception as e:
            logger.warning("Macro shock scan failed (continuing): %s", e)

    summaries = []
    tickers_with_new_claims = []
    for ticker in tickers:
        logger.info("=== Pipeline run: %s (days=%d, dry_run=%s) ===", ticker, days, dry_run)
        try:
            s = run_ticker_pipeline(
                session, ticker,
                days=days, dry_run=dry_run, source_filter=source_filter,
                use_llm=use_llm, documents_only=documents_only,
                non_documents_only=non_documents_only,
                broadcast_payloads=broadcast_docs.get(ticker),
            )
            summaries.append(s)
            if s.total_claims_extracted > 0:
                tickers_with_new_claims.append(ticker)
        except Exception as e:
            logger.error("Pipeline failed for %s: %s", ticker, e)
            err_summary = TickerRunSummary(ticker=ticker)
            err_summary.errors.append(str(e))
            err_summary.finalize()
            summaries.append(err_summary)

    # --- Cascade: propagate derived signals to target tickers ---
    # After all per-ticker runs complete, derived signals have been written.
    # Now consume them: update conviction scores on tickers that received
    # cross-ticker signals (e.g., NVDA earnings → AMD/TSMC/META get adjusted).
    if not dry_run and tickers_with_new_claims and not non_documents_only:
        try:
            from knowledge_state import run_cascade_updates
            total_cascaded = 0
            for source_ticker in tickers_with_new_claims:
                cascade_results = run_cascade_updates(session, source_ticker, use_llm=use_llm)
                for r in cascade_results:
                    if r.get("status") == "updated":
                        total_cascaded += 1
            if total_cascaded:
                logger.info(
                    "Cross-ticker cascade: %d thesis scores updated from %d source tickers",
                    total_cascaded, len(tickers_with_new_claims),
                )
                session.flush()
        except Exception as e:
            logger.warning("Cross-ticker cascade failed (continuing): %s", e)

    return summaries
