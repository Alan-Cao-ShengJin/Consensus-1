"""Pipeline runner: orchestrates one ticker-run across document and non-document sources.

Two lanes:
  1. Document sources: fetch -> dedupe -> insert -> extract claims -> thesis update
  2. Non-document sources: prices, calendar, ticker info -> dedicated storage

One thesis update per ticker-run (not per document).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from models import Base, Claim, Thesis, Document, SourceType
from connectors.base import DocumentPayload, DocumentConnector, NonDocumentUpdater
from connectors.sec_edgar import SECEdgarConnector
from connectors.google_rss import GoogleRSSConnector
from connectors.pr_rss import PRRSSConnector
from connectors.newsapi_connector import NewsAPIConnector
from connectors.yfinance_prices import YFinancePriceUpdater
from connectors.yfinance_calendar import YFinanceCalendarUpdater
from connectors.yfinance_ticker_info import YFinanceTickerInfoUpdater
from dedupe import is_duplicate_document
from document_parser import parse_document
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

    if source_filter:
        return [c for c in all_connectors if c.source_key in source_filter]
    return all_connectors


def _build_non_document_updaters(source_filter: Optional[list[str]] = None) -> list[NonDocumentUpdater]:
    """Instantiate enabled non-document updaters, optionally filtered."""
    all_updaters: list[NonDocumentUpdater] = [
        YFinancePriceUpdater(),
        YFinanceCalendarUpdater(),
        YFinanceTickerInfoUpdater(),
    ]
    if source_filter:
        return [u for u in all_updaters if u.source_key in source_filter]
    return all_updaters


# ---------------------------------------------------------------------------
# Document insertion helper
# ---------------------------------------------------------------------------

def _insert_document(session: Session, payload: DocumentPayload) -> int:
    """Insert a DocumentPayload as a Document row. Returns the new document ID."""
    clean_text = parse_document(payload.raw_text) if payload.raw_text else ""

    doc = Document(
        source_type=payload.source_type,
        source_tier=payload.source_tier,
        title=payload.title,
        url=payload.url,
        published_at=payload.published_at,
        publisher=payload.author,
        primary_company_ticker=payload.ticker,
        raw_text=clean_text,
        hash=payload.content_hash,
        source_key=payload.source_key,
        external_id=payload.external_id,
    )
    session.add(doc)
    session.flush()
    return doc.id


def _extract_claims_for_document(session: Session, doc_id: int, ticker: str, use_llm: bool = False) -> list[int]:
    """Run claim extraction on a document and return claim IDs."""
    from claim_extractor import StubClaimExtractor, LLMClaimExtractor
    from ingest import ingest_document_with_claims
    from schemas import ExtractedClaim

    doc = session.get(Document, doc_id)
    if not doc or not doc.raw_text:
        return []

    extractor = LLMClaimExtractor() if use_llm else StubClaimExtractor()
    metadata = {
        "primary_company_ticker": ticker,
        "title": doc.title or "",
        "source_type": doc.source_type.value,
    }
    claims = extractor.extract_claims(doc.raw_text, metadata)

    # Create Claim rows linked to this document
    from models import Claim as ClaimModel, ClaimCompanyLink, ClaimThemeLink
    from crud import get_or_create_company, get_or_create_theme

    claim_ids = []
    for item in claims:
        claim = ClaimModel(
            document_id=doc_id,
            claim_text_normalized=item.claim_text_normalized,
            claim_text_short=item.claim_text_short,
            claim_type=item.claim_type,
            economic_channel=item.economic_channel,
            direction=item.direction,
            strength=item.strength,
            time_horizon=item.time_horizon,
            novelty_type=item.novelty_type,
            confidence=item.confidence,
            published_at=item.published_at or doc.published_at,
            is_structural=item.is_structural,
            is_ephemeral=item.is_ephemeral,
        )
        session.add(claim)
        session.flush()
        claim_ids.append(claim.id)

        for t in item.affected_tickers:
            get_or_create_company(session, t)
            session.add(ClaimCompanyLink(claim_id=claim.id, company_ticker=t, relation_type="affects"))

        for theme_name in item.themes:
            theme = get_or_create_theme(session, theme_name)
            session.add(ClaimThemeLink(claim_id=claim.id, theme_id=theme.id))

    session.flush()

    # Post-extraction novelty classification
    if claim_ids:
        from novelty_classifier import classify_novelty
        db_claims = session.scalars(
            select(ClaimModel).where(ClaimModel.id.in_(claim_ids))
        ).all()
        if db_claims:
            classify_novelty(session, db_claims, company_ticker=ticker)
            session.flush()

    return claim_ids


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
                    doc_id = _insert_document(session, payload)
                    src_summary.docs_inserted += 1

                    claim_ids = _extract_claims_for_document(session, doc_id, ticker, use_llm=use_llm)
                    src_summary.claims_extracted += len(claim_ids)
                    all_new_claim_ids.extend(claim_ids)
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
