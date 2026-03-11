"""Price data service: upsert OHLCV rows into the prices table."""
from __future__ import annotations

import logging
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from models import Price
from crud import get_or_create_company

logger = logging.getLogger(__name__)


def upsert_prices(session: Session, rows: list[dict]) -> tuple[int, int]:
    """Upsert price rows. Returns (upserted_count, skipped_count).

    Each row dict must contain: ticker, date, open, high, low, close, volume.
    Optional: adj_close, source.
    """
    upserted = 0
    skipped = 0

    for row in rows:
        ticker = row["ticker"]
        d = row["date"]

        existing = session.scalars(
            select(Price).where(Price.ticker == ticker, Price.date == d)
        ).first()

        if existing:
            # Update if values changed
            changed = False
            for field in ("open", "high", "low", "close", "adj_close", "volume"):
                new_val = row.get(field)
                if new_val is not None and getattr(existing, field) != new_val:
                    setattr(existing, field, new_val)
                    changed = True
            if changed:
                upserted += 1
            else:
                skipped += 1
        else:
            get_or_create_company(session, ticker)
            session.add(Price(
                ticker=ticker,
                date=d,
                open=row.get("open"),
                high=row.get("high"),
                low=row.get("low"),
                close=row.get("close"),
                adj_close=row.get("adj_close"),
                volume=row.get("volume"),
                source=row.get("source", "yfinance"),
            ))
            upserted += 1

    session.flush()
    return upserted, skipped
