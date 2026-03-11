"""yfinance price data updater: fetches OHLCV data into the prices table."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from connectors.base import NonDocumentUpdater, NonDocumentResult

logger = logging.getLogger(__name__)


class YFinancePriceUpdater(NonDocumentUpdater):
    """Fetches daily OHLCV price data via yfinance and upserts into prices table."""

    @property
    def source_key(self) -> str:
        return "price_daily"

    def update(self, session, ticker: str, days: int = 30, dry_run: bool = False) -> NonDocumentResult:
        result = NonDocumentResult(source_key=self.source_key, ticker=ticker)

        try:
            import yfinance as yf
        except ImportError:
            result.errors.append("yfinance not installed; pip install yfinance")
            return result

        try:
            end = datetime.utcnow()
            start = end - timedelta(days=days)
            tk = yf.Ticker(ticker)
            hist = tk.history(start=start.strftime("%Y-%m-%d"), end=end.strftime("%Y-%m-%d"))
        except Exception as e:
            result.errors.append(f"yfinance fetch failed: {e}")
            return result

        if hist.empty:
            logger.info("yfinance prices: no data for %s (days=%d)", ticker, days)
            return result

        from price_service import upsert_prices

        rows = []
        for idx, row in hist.iterrows():
            rows.append({
                "ticker": ticker,
                "date": idx.date(),
                "open": round(row.get("Open", 0), 4),
                "high": round(row.get("High", 0), 4),
                "low": round(row.get("Low", 0), 4),
                "close": round(row.get("Close", 0), 4),
                "adj_close": round(row.get("Close", 0), 4),
                "volume": int(row.get("Volume", 0)),
                "source": "yfinance",
            })

        if dry_run:
            result.rows_upserted = len(rows)
            logger.info("yfinance prices [DRY RUN]: would upsert %d rows for %s", len(rows), ticker)
            return result

        upserted, skipped = upsert_prices(session, rows)
        result.rows_upserted = upserted
        result.rows_skipped = skipped

        logger.info("yfinance prices: upserted %d, skipped %d for %s", upserted, skipped, ticker)
        return result
