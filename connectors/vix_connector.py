"""VIX connector: fetches CBOE Volatility Index via yfinance.

VIX is the market's "fear gauge" — elevated VIX signals risk-off conditions
that should reduce position sizing and block new initiations.

Uses existing yfinance infrastructure (already a dependency).
Stores data in the prices table with ticker "^VIX".
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

from connectors.base import NonDocumentUpdater, NonDocumentResult

logger = logging.getLogger(__name__)


class VIXUpdater(NonDocumentUpdater):
    """Fetches VIX data from yfinance and stores in prices table."""

    @property
    def source_key(self) -> str:
        return "vix_daily"

    def update(
        self, session, ticker: str = "^VIX", days: int = 365,
        dry_run: bool = False, start_date=None, end_date=None,
    ) -> NonDocumentResult:
        """Fetch VIX data and store in prices table."""
        try:
            import yfinance as yf
        except ImportError:
            return NonDocumentResult(
                source_key=self.source_key, ticker=ticker,
                errors=["yfinance not installed"],
            )

        from models import Price
        from sqlalchemy import select

        result = NonDocumentResult(source_key=self.source_key, ticker=ticker)

        if start_date and end_date:
            start = start_date
            end = end_date
        else:
            end = date.today()
            start = end - timedelta(days=days)

        try:
            vix = yf.Ticker("^VIX")
            hist = vix.history(start=start.isoformat(), end=end.isoformat())
        except Exception as e:
            result.errors.append(f"yfinance VIX fetch failed: {e}")
            return result

        if hist.empty:
            logger.info("VIX: no data returned from yfinance")
            return result

        for idx, row in hist.iterrows():
            trade_date = idx.date() if hasattr(idx, "date") else idx
            close_val = float(row.get("Close", 0))
            if close_val <= 0:
                continue

            if dry_run:
                result.rows_skipped += 1
                continue

            existing = session.scalars(
                select(Price).where(
                    Price.ticker == "^VIX",
                    Price.date == trade_date,
                )
            ).first()

            if existing:
                existing.close = close_val
                result.rows_skipped += 1
            else:
                session.add(Price(
                    ticker="^VIX",
                    date=trade_date,
                    open=float(row.get("Open", close_val)),
                    high=float(row.get("High", close_val)),
                    low=float(row.get("Low", close_val)),
                    close=close_val,
                    volume=int(row.get("Volume", 0)),
                ))
                result.rows_upserted += 1

        session.flush()
        logger.info("VIX: upserted %d, skipped %d", result.rows_upserted, result.rows_skipped)
        return result


class DXYUpdater(NonDocumentUpdater):
    """Fetches Dollar Index (DXY) via yfinance. Ticker: DX-Y.NYB."""

    @property
    def source_key(self) -> str:
        return "dxy_daily"

    def update(
        self, session, ticker: str = "DX-Y.NYB", days: int = 365,
        dry_run: bool = False, start_date=None, end_date=None,
    ) -> NonDocumentResult:
        """Fetch DXY data and store in prices table."""
        try:
            import yfinance as yf
        except ImportError:
            return NonDocumentResult(
                source_key=self.source_key, ticker=ticker,
                errors=["yfinance not installed"],
            )

        from models import Price
        from sqlalchemy import select

        result = NonDocumentResult(source_key=self.source_key, ticker=ticker)

        if start_date and end_date:
            start = start_date
            end = end_date
        else:
            end = date.today()
            start = end - timedelta(days=days)

        try:
            dxy = yf.Ticker("DX-Y.NYB")
            hist = dxy.history(start=start.isoformat(), end=end.isoformat())
        except Exception as e:
            result.errors.append(f"yfinance DXY fetch failed: {e}")
            return result

        if hist.empty:
            logger.info("DXY: no data returned from yfinance")
            return result

        for idx, row in hist.iterrows():
            trade_date = idx.date() if hasattr(idx, "date") else idx
            close_val = float(row.get("Close", 0))
            if close_val <= 0:
                continue

            if dry_run:
                result.rows_skipped += 1
                continue

            existing = session.scalars(
                select(Price).where(
                    Price.ticker == "MACRO:DXY",
                    Price.date == trade_date,
                )
            ).first()

            if existing:
                existing.close = close_val
                result.rows_skipped += 1
            else:
                session.add(Price(
                    ticker="MACRO:DXY",
                    date=trade_date,
                    open=float(row.get("Open", close_val)),
                    high=float(row.get("High", close_val)),
                    low=float(row.get("Low", close_val)),
                    close=close_val,
                    volume=int(row.get("Volume", 0)),
                ))
                result.rows_upserted += 1

        session.flush()
        logger.info("DXY: upserted %d, skipped %d", result.rows_upserted, result.rows_skipped)
        return result
