"""Canonical document ingestion service for connector-sourced documents.

Handles the full path from DocumentPayload to persisted Document + Claims:
  1. Parse/clean raw text
  2. Insert Document row (with source_key, external_id, content hash)
  3. Extract claims (stub or LLM)
  4. Create Claim rows with company/theme links
  5. Run post-extraction novelty classification
  6. Assign event clusters (duplicate-event detection)
  7. Detect and persist contradiction metadata

Steps 6-7 were added in Step 13.1 to make event clustering and contradiction
detection canonical ingestion-time operations rather than thesis-update-time
transient computations.

This is the single ingestion path for Step 6 connector sources.
Manual/file-based ingestion (ingest.py, ingest_runner.py) remains separate.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from connectors.base import DocumentPayload
from document_parser import parse_document
from models import (
    Document, Claim, ClaimCompanyLink, ClaimThemeLink,
)
from crud import get_or_create_company, get_or_create_theme

logger = logging.getLogger(__name__)


@dataclass
class IngestionResult:
    """Result of ingesting a single document payload."""
    document_id: int
    claim_ids: list[int] = field(default_factory=list)


def ingest_document_payload(
    session: Session,
    payload: DocumentPayload,
    ticker: str,
    use_llm: bool = False,
) -> IngestionResult:
    """Insert a document and extract claims from a connector-sourced payload.

    Does NOT call session.commit() — the caller decides when to commit.

    Args:
        session: SQLAlchemy session.
        payload: Normalized document payload from a connector.
        ticker: Company ticker for claim extraction context.
        use_llm: Use LLM extractor (True) or stub extractor (False).

    Returns:
        IngestionResult with the new document ID and list of claim IDs.
    """
    # 1. Parse raw text
    clean_text = parse_document(payload.raw_text) if payload.raw_text else ""

    # 2. Insert Document row
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

    # 3. Extract claims
    claim_ids = _extract_and_link_claims(session, doc, ticker, use_llm)

    return IngestionResult(document_id=doc.id, claim_ids=claim_ids)


def _extract_and_link_claims(
    session: Session,
    doc: Document,
    ticker: str,
    use_llm: bool,
) -> list[int]:
    """Run claim extraction on a document, create linked rows, classify novelty."""
    if not doc.raw_text:
        return []

    from claim_extractor import StubClaimExtractor, LLMClaimExtractor

    extractor = LLMClaimExtractor() if use_llm else StubClaimExtractor()
    metadata = {
        "primary_company_ticker": ticker,
        "title": doc.title or "",
        "source_type": doc.source_type.value,
        "document_date": doc.published_at.strftime("%Y-%m-%d") if doc.published_at else "unknown",
    }
    extracted = extractor.extract_claims(doc.raw_text, metadata)

    # Create Claim rows with company and theme links
    claim_ids: list[int] = []
    for item in extracted:
        claim = Claim(
            document_id=doc.id,
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
            source_excerpt=item.source_excerpt,
        )
        session.add(claim)
        session.flush()
        claim_ids.append(claim.id)

        for t in item.affected_tickers:
            get_or_create_company(session, t)
            session.add(ClaimCompanyLink(
                claim_id=claim.id, company_ticker=t, relation_type="affects",
            ))

        for theme_name in item.themes:
            theme = get_or_create_theme(session, theme_name)
            session.add(ClaimThemeLink(claim_id=claim.id, theme_id=theme.id))

    session.flush()

    # Post-extraction novelty classification + contradiction detection
    if claim_ids:
        from novelty_classifier import classify_novelty
        db_claims = session.scalars(
            select(Claim).where(Claim.id.in_(claim_ids))
        ).all()
        if db_claims:
            novelty_results = classify_novelty(session, db_claims, company_ticker=ticker)
            # Wire contradiction metadata: when novelty_type is CONFLICTING,
            # persist the contradicts_claim_id and is_contradicted flag.
            _apply_contradiction_metadata(session, novelty_results)
            session.flush()

    # Post-extraction event clustering: assign stable event_cluster_id at
    # ingestion time so downstream thesis updates consume persisted cluster
    # state rather than recomputing from scratch.
    if claim_ids:
        _assign_ingestion_event_clusters(session, claim_ids, ticker)
        session.flush()

    return claim_ids


def _apply_contradiction_metadata(
    session: Session,
    novelty_results: list[tuple[int, object, float, int | None]],
) -> None:
    """Persist contradiction flags on claims detected as CONFLICTING.

    Simple bounded contradiction detection:
    - A claim is contradicted if novelty_classifier found it CONFLICTING with
      a prior claim (same company, similar topic, opposite direction).
    - We store the prior claim ID it contradicts for audit/explainability.
    """
    from models import NoveltyType
    for claim_id, novelty_type, _sim, prior_claim_id in novelty_results:
        if novelty_type == NoveltyType.CONFLICTING and prior_claim_id is not None:
            claim = session.get(Claim, claim_id)
            if claim:
                claim.is_contradicted = True
                claim.contradicts_claim_id = prior_claim_id
                logger.info(
                    "Contradiction detected: claim %d contradicts prior claim %d",
                    claim_id, prior_claim_id,
                )


def _assign_ingestion_event_clusters(
    session: Session,
    claim_ids: list[int],
    ticker: str,
) -> None:
    """Assign event clusters at ingestion time.

    This is the canonical cluster assignment step. Claims get a stable
    event_cluster_id that downstream thesis updates can consume directly.
    """
    try:
        from event_clustering import assign_event_clusters
        assign_event_clusters(session, claim_ids, ticker)
    except Exception as e:
        # Graceful degradation: clustering failure should not block ingestion.
        # Claims will still have event_cluster_id=None, and thesis update
        # can fall back to recomputation if needed.
        logger.warning("Ingestion-time event clustering failed (non-fatal): %s", e)
