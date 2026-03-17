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


class OilUpdater(NonDocumentUpdater):
    """Fetches crude oil futures (CL=F) via yfinance. Ticker: MACRO:OIL."""

    @property
    def source_key(self) -> str:
        return "oil_daily"

    def update(
        self, session, ticker: str = "CL=F", days: int = 365,
        dry_run: bool = False, start_date=None, end_date=None,
    ) -> NonDocumentResult:
        """Fetch crude oil futures data and store in prices table."""
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
            oil = yf.Ticker("CL=F")
            hist = oil.history(start=start.isoformat(), end=end.isoformat())
        except Exception as e:
            result.errors.append(f"yfinance OIL fetch failed: {e}")
            return result

        if hist.empty:
            logger.info("OIL: no data returned from yfinance")
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
                    Price.ticker == "MACRO:OIL",
                    Price.date == trade_date,
                )
            ).first()

            if existing:
                existing.close = close_val
                result.rows_skipped += 1
            else:
                session.add(Price(
                    ticker="MACRO:OIL",
                    date=trade_date,
                    open=float(row.get("Open", close_val)),
                    high=float(row.get("High", close_val)),
                    low=float(row.get("Low", close_val)),
                    close=close_val,
                    volume=int(row.get("Volume", 0)),
                ))
                result.rows_upserted += 1

        session.flush()
        logger.info("OIL: upserted %d, skipped %d", result.rows_upserted, result.rows_skipped)
        return result


class CreditSpreadUpdater(NonDocumentUpdater):
    """Fetches HYG and LQD ETFs via yfinance, computes credit spread proxy.

    Stores individual ETF prices as MACRO:HYG and MACRO:LQD, plus a
    computed spread metric as MACRO:CREDIT_SPREAD = (LQD/HYG - 1) * 100.
    When credit stress rises, HYG drops relative to LQD, so the spread widens.
    """

    @property
    def source_key(self) -> str:
        return "credit_spread_daily"

    def update(
        self, session, ticker: str = "HYG", days: int = 365,
        dry_run: bool = False, start_date=None, end_date=None,
    ) -> NonDocumentResult:
        """Fetch HYG/LQD data, compute credit spread, and store in prices table."""
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
            hyg = yf.Ticker("HYG")
            hyg_hist = hyg.history(start=start.isoformat(), end=end.isoformat())
            lqd = yf.Ticker("LQD")
            lqd_hist = lqd.history(start=start.isoformat(), end=end.isoformat())
        except Exception as e:
            result.errors.append(f"yfinance credit spread fetch failed: {e}")
            return result

        if hyg_hist.empty or lqd_hist.empty:
            logger.info("CreditSpread: no data returned from yfinance (HYG empty=%s, LQD empty=%s)",
                        hyg_hist.empty, lqd_hist.empty)
            return result

        def _upsert_price(macro_ticker: str, trade_date, open_val, high_val, low_val, close_val, volume):
            """Upsert a single price row, returning True if new row inserted."""
            existing = session.scalars(
                select(Price).where(
                    Price.ticker == macro_ticker,
                    Price.date == trade_date,
                )
            ).first()
            if existing:
                existing.close = close_val
                return False
            else:
                session.add(Price(
                    ticker=macro_ticker,
                    date=trade_date,
                    open=open_val,
                    high=high_val,
                    low=low_val,
                    close=close_val,
                    volume=volume,
                ))
                return True

        # Build a date-aligned dict for LQD so we can pair with HYG
        lqd_by_date = {}
        for idx, row in lqd_hist.iterrows():
            td = idx.date() if hasattr(idx, "date") else idx
            lqd_by_date[td] = row

        for idx, hyg_row in hyg_hist.iterrows():
            trade_date = idx.date() if hasattr(idx, "date") else idx
            hyg_close = float(hyg_row.get("Close", 0))
            if hyg_close <= 0:
                continue

            lqd_row = lqd_by_date.get(trade_date)
            if lqd_row is None:
                continue
            lqd_close = float(lqd_row.get("Close", 0))
            if lqd_close <= 0:
                continue

            if dry_run:
                result.rows_skipped += 1
                continue

            # Store MACRO:HYG
            _upsert_price(
                "MACRO:HYG", trade_date,
                float(hyg_row.get("Open", hyg_close)),
                float(hyg_row.get("High", hyg_close)),
                float(hyg_row.get("Low", hyg_close)),
                hyg_close,
                int(hyg_row.get("Volume", 0)),
            )

            # Store MACRO:LQD
            _upsert_price(
                "MACRO:LQD", trade_date,
                float(lqd_row.get("Open", lqd_close)),
                float(lqd_row.get("High", lqd_close)),
                float(lqd_row.get("Low", lqd_close)),
                lqd_close,
                int(lqd_row.get("Volume", 0)),
            )

            # Compute and store MACRO:CREDIT_SPREAD = (LQD/HYG - 1) * 100
            spread_val = (lqd_close / hyg_close - 1) * 100
            inserted = _upsert_price(
                "MACRO:CREDIT_SPREAD", trade_date,
                spread_val, spread_val, spread_val, spread_val, 0,
            )
            if inserted:
                result.rows_upserted += 1
            else:
                result.rows_skipped += 1

        session.flush()
        logger.info("CreditSpread: upserted %d, skipped %d", result.rows_upserted, result.rows_skipped)
        return result
