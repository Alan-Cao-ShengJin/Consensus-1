"""Alpha Vantage connector: earnings surprises, forward estimates, and company overview.

Requires ALPHAVANTAGE_API_KEY env var. Free tier: 25 requests/day.
"""
from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv()

from models import EarningsEstimate, SourceType, SourceTier
from connectors.base import DocumentConnector, DocumentPayload

logger = logging.getLogger(__name__)

AV_BASE = "https://www.alphavantage.co/query"


def _av_api_key() -> str:
    return os.getenv("ALPHAVANTAGE_API_KEY", "")


def _av_get(function: str, params: dict | None = None, timeout: int = 30) -> dict | None:
    """Make a GET request to Alpha Vantage. Returns parsed JSON or None."""
    api_key = _av_api_key()
    if not api_key:
        return None
    if params is None:
        params = {}
    params["function"] = function
    params["apikey"] = api_key

    try:
        resp = requests.get(AV_BASE, params=params, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        # Check for rate limit / error messages
        if "Information" in data or "Note" in data or "Error Message" in data:
            msg = data.get("Information") or data.get("Note") or data.get("Error Message")
            logger.warning("Alpha Vantage %s: %s", function, msg)
            return None
        return data
    except Exception as e:
        logger.error("Alpha Vantage request failed: %s: %s", function, e)
        return None


class AlphaVantageEarningsConnector(DocumentConnector):
    """Fetches quarterly earnings surprises from Alpha Vantage.

    Provides reportedEPS, estimatedEPS, surprise, and surprisePercentage
    for each quarter — high-value structured data for claim extraction.
    """

    def __init__(self):
        self._api_key = _av_api_key()

    @property
    def source_key(self) -> str:
        return "earnings_alphavantage"

    @property
    def available(self) -> bool:
        return bool(self._api_key)

    def fetch(self, ticker: str, days: int = 365) -> list[DocumentPayload]:
        if not self._api_key:
            return []

        data = _av_get("EARNINGS", {"symbol": ticker})
        if not data:
            logger.info("Alpha Vantage earnings: no data for %s", ticker)
            return []

        quarterly = data.get("quarterlyEarnings", [])
        if not quarterly:
            return []

        cutoff = datetime.utcnow() - timedelta(days=days)
        payloads = []

        for q in quarterly:
            date_str = q.get("reportedDate", "") or q.get("fiscalDateEnding", "")
            try:
                published = datetime.strptime(date_str[:10], "%Y-%m-%d")
            except (ValueError, AttributeError):
                continue

            if published < cutoff:
                continue

            reported_eps = q.get("reportedEPS", "")
            estimated_eps = q.get("estimatedEPS", "")
            surprise = q.get("surprise", "")
            surprise_pct = q.get("surprisePercentage", "")
            fiscal_end = q.get("fiscalDateEnding", "")
            report_time = q.get("reportTime", "")

            # Build readable text
            lines = [f"{ticker} Quarterly Earnings Report — {fiscal_end}"]
            lines.append("=" * 50)
            lines.append(f"Report Date: {date_str} ({report_time})")
            if reported_eps:
                lines.append(f"Reported EPS: ${reported_eps}")
            if estimated_eps and estimated_eps != "None":
                lines.append(f"Estimated EPS (consensus): ${estimated_eps}")
            if surprise and surprise_pct and surprise_pct != "None":
                beat_miss = "beat" if float(surprise) > 0 else "missed"
                lines.append(
                    f"EPS Surprise: ${surprise} ({beat_miss} by {abs(float(surprise_pct)):.1f}%)"
                )

            raw_text = "\n".join(lines)
            external_id = f"{ticker}_earnings_{fiscal_end}"

            payloads.append(DocumentPayload(
                source_key=self.source_key,
                source_type=SourceType.EARNINGS_TRANSCRIPT,  # closest match
                source_tier=SourceTier.TIER_1,
                ticker=ticker,
                title=f"{ticker} Earnings Report — {fiscal_end}",
                url=None,
                published_at=published,
                author="Alpha Vantage",
                external_id=external_id,
                raw_text=raw_text,
                metadata={
                    "reported_eps": float(reported_eps) if reported_eps else None,
                    "estimated_eps": float(estimated_eps) if estimated_eps and estimated_eps != "None" else None,
                    "surprise": float(surprise) if surprise else None,
                    "surprise_pct": float(surprise_pct) if surprise_pct and surprise_pct != "None" else None,
                    "fiscal_date_ending": fiscal_end,
                    "report_time": report_time,
                },
            ))

        logger.info("Alpha Vantage earnings: fetched %d quarters for %s (days=%d)",
                     len(payloads), ticker, days)
        return payloads


def fetch_forward_estimates(ticker: str) -> Optional[dict]:
    """Fetch the next quarter's consensus EPS estimate from AV EARNINGS_CALENDAR.

    Returns dict with {fiscal_date, report_date, estimated_eps, currency} or None.
    This is a lightweight call — only returns the next upcoming earnings.
    """
    import csv
    import io

    api_key = _av_api_key()
    if not api_key:
        return None

    # EARNINGS_CALENDAR returns CSV, not JSON
    params = {
        "function": "EARNINGS_CALENDAR",
        "symbol": ticker,
        "horizon": "3month",
        "apikey": api_key,
    }
    try:
        resp = requests.get(AV_BASE, params=params, timeout=30)
        resp.raise_for_status()
        reader = csv.DictReader(io.StringIO(resp.text))
        rows = list(reader)
    except Exception as e:
        logger.error("AV EARNINGS_CALENDAR failed for %s: %s", ticker, e)
        return None

    if not rows:
        logger.info("No upcoming earnings for %s", ticker)
        return None

    row = rows[0]  # next upcoming quarter
    estimate_str = row.get("estimate", "")
    if not estimate_str:
        logger.info("AV EARNINGS_CALENDAR: no estimate for %s", ticker)
        return None

    try:
        estimated_eps = float(estimate_str)
    except (ValueError, TypeError):
        logger.warning("AV EARNINGS_CALENDAR: bad estimate value '%s' for %s", estimate_str, ticker)
        return None

    result = {
        "ticker": ticker,
        "report_date": row.get("reportDate", ""),
        "fiscal_date": row.get("fiscalDateEnding", ""),
        "estimated_eps": estimated_eps,
        "currency": row.get("currency", "USD"),
    }
    logger.info("AV forward estimate for %s: EPS $%.2f, reporting %s",
                ticker, result["estimated_eps"], result["report_date"])
    return result


def persist_forward_estimate(session, ticker: str) -> Optional[EarningsEstimate]:
    """Fetch forward estimate from AV and upsert into EarningsEstimate table.

    This is the pre-earnings step: store what the Street expects BEFORE
    the actual number drops. When earnings arrive, prior_context.py
    compares actuals against this stored estimate.

    Returns the EarningsEstimate row (new or updated), or None if unavailable.
    """
    from sqlalchemy import select

    data = fetch_forward_estimates(ticker)
    if not data:
        return None

    fiscal_date_str = data["fiscal_date"]
    try:
        fiscal_dt = date.fromisoformat(fiscal_date_str)
    except (ValueError, TypeError):
        logger.warning("Bad fiscal_date from AV: %s", fiscal_date_str)
        return None

    # Upsert: update if exists, insert if not
    existing = session.scalars(
        select(EarningsEstimate).where(
            EarningsEstimate.ticker == ticker,
            EarningsEstimate.fiscal_date == fiscal_dt,
        )
    ).first()

    if existing:
        existing.estimated_eps = data["estimated_eps"]
        if data.get("report_date"):
            try:
                existing.earnings_date = date.fromisoformat(data["report_date"])
            except (ValueError, TypeError):
                pass
        existing.source = "alphavantage"
        existing.fetched_at = datetime.utcnow()
        logger.info("Updated forward estimate for %s Q ending %s: EPS $%.2f",
                     ticker, fiscal_dt, data["estimated_eps"])
        return existing

    est = EarningsEstimate(
        ticker=ticker,
        fiscal_date=fiscal_dt,
        estimated_eps=data["estimated_eps"],
        source="alphavantage",
    )
    if data.get("report_date"):
        try:
            est.earnings_date = date.fromisoformat(data["report_date"])
        except (ValueError, TypeError):
            pass

    session.add(est)
    logger.info("Stored forward estimate for %s Q ending %s: EPS $%.2f, reporting %s",
                ticker, fiscal_dt, data["estimated_eps"], data.get("report_date", "?"))
    return est
