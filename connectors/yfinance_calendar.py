"""yfinance earnings calendar updater: creates/updates checkpoint rows for earnings dates."""
from __future__ import annotations

import logging
from datetime import date

from connectors.base import NonDocumentUpdater, NonDocumentResult

logger = logging.getLogger(__name__)


class YFinanceCalendarUpdater(NonDocumentUpdater):
    """Fetches upcoming earnings dates via yfinance and upserts into checkpoints table."""

    @property
    def source_key(self) -> str:
        return "earnings_calendar"

    def update(self, session, ticker: str, days: int = 90, dry_run: bool = False) -> NonDocumentResult:
        result = NonDocumentResult(source_key=self.source_key, ticker=ticker)

        try:
            import yfinance as yf
        except ImportError:
            result.errors.append("yfinance not installed; pip install yfinance")
            return result

        try:
            tk = yf.Ticker(ticker)
            cal = tk.calendar
        except Exception as e:
            result.errors.append(f"yfinance calendar fetch failed: {e}")
            return result

        if cal is None or (hasattr(cal, 'empty') and cal.empty):
            logger.info("yfinance calendar: no data for %s", ticker)
            return result

        from checkpoint_service import upsert_earnings_checkpoint

        # yfinance .calendar returns a dict or DataFrame depending on version
        earnings_dates = []
        if isinstance(cal, dict):
            ed = cal.get("Earnings Date")
            if ed:
                if isinstance(ed, list):
                    earnings_dates = ed
                else:
                    earnings_dates = [ed]
        else:
            # DataFrame format
            try:
                if "Earnings Date" in cal.index:
                    val = cal.loc["Earnings Date"]
                    if hasattr(val, 'tolist'):
                        earnings_dates = val.tolist()
                    else:
                        earnings_dates = [val]
            except Exception:
                pass

        count = 0
        for ed in earnings_dates:
            if ed is None:
                continue
            # Normalize to date
            if hasattr(ed, 'date'):
                d = ed.date()
            elif isinstance(ed, date):
                d = ed
            else:
                try:
                    from datetime import datetime
                    d = datetime.strptime(str(ed)[:10], "%Y-%m-%d").date()
                except Exception:
                    continue

            if dry_run:
                count += 1
                continue

            upsert_earnings_checkpoint(session, ticker, d)
            count += 1

        result.rows_upserted = count
        if dry_run:
            logger.info("yfinance calendar [DRY RUN]: would upsert %d checkpoints for %s", count, ticker)
        else:
            logger.info("yfinance calendar: upserted %d checkpoints for %s", count, ticker)

        return result
