"""Dedupe layer: centralized duplicate detection for documents and non-document data.

Rules for document dedupe (checked in order):
  1. (source_key, external_id) if external_id exists
  2. URL match
  3. Content hash match

For price data: (ticker, date)
For checkpoints: (ticker, checkpoint_type, date_expected)
Ticker enrichment: upsert by ticker identity (handled in company_enrichment_service)
"""
from __future__ import annotations

import logging

from sqlalchemy import select, and_
from sqlalchemy.orm import Session

from models import Document, Price, Checkpoint
from connectors.base import DocumentPayload

logger = logging.getLogger(__name__)


def is_duplicate_document(session: Session, payload: DocumentPayload) -> bool:
    """Check if a document payload is a duplicate of an existing document.

    Checks in order:
      1. (source_key, external_id) if external_id is present
      2. URL if present
      3. Content hash if present

    Returns True if a duplicate is found.
    """
    # 1. Check by (source_key, external_id)
    if payload.external_id and payload.source_key:
        exists = session.scalars(
            select(Document.id).where(
                and_(
                    Document.source_key == payload.source_key,
                    Document.external_id == payload.external_id,
                )
            ).limit(1)
        ).first()
        if exists is not None:
            logger.debug("Dedupe hit: source_key=%s external_id=%s", payload.source_key, payload.external_id)
            return True

    # 2. Check by URL
    if payload.url:
        exists = session.scalars(
            select(Document.id).where(Document.url == payload.url).limit(1)
        ).first()
        if exists is not None:
            logger.debug("Dedupe hit: url=%s", payload.url)
            return True

    # 3. Check by content hash
    if payload.content_hash:
        exists = session.scalars(
            select(Document.id).where(Document.hash == payload.content_hash).limit(1)
        ).first()
        if exists is not None:
            logger.debug("Dedupe hit: hash=%s", payload.content_hash[:16])
            return True

    return False


def is_duplicate_price(session: Session, ticker: str, d) -> bool:
    """Check if a price row already exists for (ticker, date)."""
    exists = session.scalars(
        select(Price.id).where(
            and_(Price.ticker == ticker, Price.date == d)
        ).limit(1)
    ).first()
    return exists is not None


def is_duplicate_checkpoint(session: Session, ticker: str, checkpoint_type: str, date_expected) -> bool:
    """Check if a checkpoint already exists for (ticker, type, date)."""
    exists = session.scalars(
        select(Checkpoint.id).where(
            and_(
                Checkpoint.linked_company_ticker == ticker,
                Checkpoint.checkpoint_type == checkpoint_type,
                Checkpoint.date_expected == date_expected,
            )
        ).limit(1)
    ).first()
    return exists is not None


def filter_new_documents(session: Session, payloads: list[DocumentPayload]) -> list[DocumentPayload]:
    """Filter a list of payloads, returning only those that are not duplicates."""
    new = []
    for p in payloads:
        if not is_duplicate_document(session, p):
            new.append(p)
    return new
