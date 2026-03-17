"""Market hours checking for live trading.

Uses Alpaca's clock API when available, falls back to basic US market schedule.
"""
from __future__ import annotations

import logging
from datetime import datetime, time, timezone

logger = logging.getLogger(__name__)

# US Eastern market hours (fallback when broker clock unavailable)
MARKET_OPEN = time(9, 30)   # 9:30 AM ET
MARKET_CLOSE = time(16, 0)  # 4:00 PM ET


def is_market_open(broker=None) -> bool:
    """Check if the US stock market is currently open.

    Uses broker's clock API if available, otherwise falls back to
    basic time-of-day check (no holiday awareness).
    """
    if broker is not None and hasattr(broker, "is_market_open"):
        try:
            return broker.is_market_open()
        except Exception as e:
            logger.warning("Broker clock check failed, using fallback: %s", e)

    return _fallback_market_open()


def next_market_open(broker=None) -> str | None:
    """Get next market open time as ISO string, if available."""
    if broker is not None and hasattr(broker, "get_clock"):
        try:
            clock = broker.get_clock()
            return clock.get("next_open")
        except Exception as e:
            logger.warning("Failed to get next market open: %s", e)
    return None


def _fallback_market_open() -> bool:
    """Basic check: is it a weekday between 9:30-16:00 ET?

    Does NOT account for holidays. Use broker clock for production.
    """
    try:
        from zoneinfo import ZoneInfo
        et = ZoneInfo("America/New_York")
    except ImportError:
        from datetime import timedelta
        # Rough ET offset (doesn't handle DST)
        et = timezone(timedelta(hours=-5))

    now_et = datetime.now(et)

    # Weekday check (Mon=0, Fri=4)
    if now_et.weekday() > 4:
        return False

    current_time = now_et.time()
    return MARKET_OPEN <= current_time <= MARKET_CLOSE
