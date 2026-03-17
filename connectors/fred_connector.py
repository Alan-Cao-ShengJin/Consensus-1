"""FRED API connector: fetches macroeconomic indicators from the Federal Reserve.

FRED (Federal Reserve Economic Data) provides free access to 800,000+ economic
time series. No API key required for basic access (but rate-limited).
With a free API key, you get 120 requests/minute.

Key series for market sentiment:
  - FEDFUNDS: Federal Funds effective rate
  - CPIAUCSL: Consumer Price Index (headline inflation)
  - T10Y2Y: 10-Year minus 2-Year Treasury spread (yield curve)
  - DGS10: 10-Year Treasury yield
  - DGS2: 2-Year Treasury yield
  - UNRATE: Unemployment rate
  - GDP: Gross domestic product
  - VIXCLS: CBOE VIX (also available via yfinance)
  - DTWEXBGS: Trade-weighted dollar index (similar to DXY)
  - UMCSENT: University of Michigan consumer sentiment
  - ICSA: Initial jobless claims (weekly)

Data flows into the system as non-document updates (macro time-series),
not as documents for claim extraction.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv()

from connectors.base import NonDocumentUpdater, NonDocumentResult

logger = logging.getLogger(__name__)

FRED_BASE = "https://api.stlouisfed.org/fred"


@dataclass
class FREDObservation:
    """A single FRED data observation."""
    series_id: str
    date: date
    value: float


# Key macro indicators to track
MACRO_SERIES = {
    "FEDFUNDS": "Federal Funds Rate",
    "T10Y2Y": "10Y-2Y Yield Curve Spread",
    "DGS10": "10-Year Treasury Yield",
    "DGS2": "2-Year Treasury Yield",
    "CPIAUCSL": "Consumer Price Index",
    "UNRATE": "Unemployment Rate",
    "VIXCLS": "CBOE VIX",
    "DTWEXBGS": "Trade-Weighted Dollar Index",
    "UMCSENT": "Consumer Sentiment (U. Michigan)",
    "ICSA": "Initial Jobless Claims",
}


def _fred_api_key() -> str:
    """Get FRED API key from environment. Optional but recommended."""
    return os.getenv("FRED_API_KEY", "")


def fetch_fred_series(
    series_id: str,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    api_key: Optional[str] = None,
) -> list[FREDObservation]:
    """Fetch a single FRED time series.

    Args:
        series_id: FRED series identifier (e.g., "T10Y2Y").
        start_date: Start of observation range.
        end_date: End of observation range.
        api_key: FRED API key (optional, uses env var if not provided).

    Returns:
        List of FREDObservation objects, sorted by date ascending.
    """
    key = api_key or _fred_api_key()
    if not key:
        logger.warning("No FRED_API_KEY set — FRED API calls will be rate-limited")
        # FRED allows limited access without a key via JSON format
        # but the standard API requires one
        return []

    if start_date is None:
        start_date = date.today() - timedelta(days=365)
    if end_date is None:
        end_date = date.today()

    params = {
        "series_id": series_id,
        "api_key": key,
        "file_type": "json",
        "observation_start": start_date.isoformat(),
        "observation_end": end_date.isoformat(),
        "sort_order": "asc",
    }

    try:
        resp = requests.get(
            f"{FRED_BASE}/series/observations",
            params=params,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.error("FRED fetch failed for %s: %s", series_id, e)
        return []

    observations = []
    for obs in data.get("observations", []):
        try:
            val_str = obs.get("value", ".")
            if val_str == "." or val_str == "":
                continue  # FRED uses "." for missing data
            observations.append(FREDObservation(
                series_id=series_id,
                date=date.fromisoformat(obs["date"]),
                value=float(val_str),
            ))
        except (ValueError, KeyError) as e:
            logger.debug("Skipping FRED observation: %s", e)
            continue

    logger.info("FRED: fetched %d observations for %s", len(observations), series_id)
    return observations


def fetch_all_macro_indicators(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> dict[str, list[FREDObservation]]:
    """Fetch all key macro indicators from FRED.

    Returns dict mapping series_id to list of observations.
    """
    results = {}
    for series_id in MACRO_SERIES:
        observations = fetch_fred_series(series_id, start_date, end_date)
        if observations:
            results[series_id] = observations
    return results


def get_latest_observation(
    observations: list[FREDObservation],
    as_of: Optional[date] = None,
) -> Optional[FREDObservation]:
    """Get the most recent observation on or before as_of."""
    if not observations:
        return None
    if as_of is None:
        return observations[-1]
    for obs in reversed(observations):
        if obs.date <= as_of:
            return obs
    return None


class FREDMacroUpdater(NonDocumentUpdater):
    """Updates macro indicator data from FRED.

    Stores observations in a macro_indicators table (or as metadata on
    a MACRO pseudo-ticker in the prices table).
    """

    @property
    def source_key(self) -> str:
        return "macro_fred"

    @property
    def available(self) -> bool:
        return bool(_fred_api_key())

    def update(
        self, session, ticker: str = "MACRO", days: int = 365,
        dry_run: bool = False,
    ) -> NonDocumentResult:
        """Fetch and store macro indicators.

        Uses the prices table with special ticker names like
        "MACRO:T10Y2Y", "MACRO:VIX", etc.
        """
        from models import Price

        result = NonDocumentResult(source_key=self.source_key, ticker=ticker)

        if not self.available:
            result.errors.append("FRED_API_KEY not set")
            return result

        end_date = date.today()
        start_date = end_date - timedelta(days=days)

        all_data = fetch_all_macro_indicators(start_date, end_date)

        for series_id, observations in all_data.items():
            macro_ticker = f"MACRO:{series_id}"
            for obs in observations:
                if dry_run:
                    result.rows_skipped += 1
                    continue

                # Upsert: check if this date already exists
                from sqlalchemy import select
                existing = session.scalars(
                    select(Price).where(
                        Price.ticker == macro_ticker,
                        Price.date == obs.date,
                    )
                ).first()

                if existing:
                    existing.close = obs.value
                    result.rows_skipped += 1
                else:
                    session.add(Price(
                        ticker=macro_ticker,
                        date=obs.date,
                        open=obs.value,
                        high=obs.value,
                        low=obs.value,
                        close=obs.value,
                        volume=0,
                    ))
                    result.rows_upserted += 1

            session.flush()

        logger.info(
            "FRED: upserted %d rows, skipped %d for %d series",
            result.rows_upserted, result.rows_skipped, len(all_data),
        )
        return result
