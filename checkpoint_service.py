"""Checkpoint service: upsert earnings and event checkpoints."""
from __future__ import annotations

import logging
from datetime import date

from sqlalchemy import select, and_
from sqlalchemy.orm import Session

from models import Checkpoint
from crud import get_or_create_company

logger = logging.getLogger(__name__)


def upsert_earnings_checkpoint(
    session: Session,
    ticker: str,
    earnings_date: date,
    importance: float = 0.9,
) -> Checkpoint:
    """Create or update an earnings checkpoint for a ticker + date.

    Dedupe key: (ticker, 'earnings_release', date).
    """
    get_or_create_company(session, ticker)

    existing = session.scalars(
        select(Checkpoint).where(
            and_(
                Checkpoint.linked_company_ticker == ticker,
                Checkpoint.checkpoint_type == "earnings_release",
                Checkpoint.date_expected == earnings_date,
            )
        )
    ).first()

    if existing:
        existing.importance = importance
        existing.status = "upcoming"
        session.flush()
        return existing

    cp = Checkpoint(
        checkpoint_type="earnings_release",
        name=f"{ticker} Earnings Release",
        date_expected=earnings_date,
        importance=importance,
        linked_company_ticker=ticker,
        status="upcoming",
    )
    session.add(cp)
    session.flush()
    return cp
