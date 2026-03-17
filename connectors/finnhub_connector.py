"""Finnhub news connector: fetches company news via Finnhub API."""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timedelta

import requests
from dotenv import load_dotenv

load_dotenv()

from models import SourceType, SourceTier
from connectors.base import DocumentConnector, DocumentPayload

logger = logging.getLogger(__name__)

FINNHUB_BASE_URL = "https://finnhub.io/api/v1"


class FinnhubNewsConnector(DocumentConnector):
    """Fetches company news from Finnhub. Requires FINNHUB_API_KEY."""

    def __init__(self):
        self._api_key = os.getenv("FINNHUB_API_KEY", "")
        self._last_request_time = 0.0

    @property
    def source_key(self) -> str:
        return "news_finnhub"

    @property
    def available(self) -> bool:
        return bool(self._api_key)

    def _rate_limit(self):
        """Enforce 1 request per second."""
        elapsed = time.time() - self._last_request_time
        if elapsed < 1.0:
            time.sleep(1.0 - elapsed)
        self._last_request_time = time.time()

    def fetch(self, ticker: str, days: int = 7, start_date=None, end_date=None) -> list[DocumentPayload]:
        if not self._api_key:
            logger.info("Finnhub: FINNHUB_API_KEY not set, skipping")
            return []

        if start_date and end_date:
            from_date = start_date.strftime("%Y-%m-%d") if hasattr(start_date, 'strftime') else str(start_date)
            to_date = end_date.strftime("%Y-%m-%d") if hasattr(end_date, 'strftime') else str(end_date)
        else:
            to_date = datetime.utcnow().strftime("%Y-%m-%d")
            from_date = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")

        self._rate_limit()

        try:
            resp = requests.get(
                f"{FINNHUB_BASE_URL}/company-news",
                params={
                    "symbol": ticker,
                    "from": from_date,
                    "to": to_date,
                    "token": self._api_key,
                },
                timeout=30,
            )
            resp.raise_for_status()
            articles = resp.json()
        except Exception as e:
            logger.error("Finnhub fetch failed for %s: %s", ticker, e)
            return []

        if not isinstance(articles, list):
            logger.warning("Finnhub: unexpected response type for %s: %s", ticker, type(articles))
            return []

        payloads = []
        for article in articles:
            # Parse unix timestamp
            ts = article.get("datetime", 0)
            try:
                published = datetime.utcfromtimestamp(ts) if ts else None
            except (ValueError, OSError):
                published = None

            headline = article.get("headline", "")
            summary = article.get("summary", "")
            url = article.get("url", "")
            article_id = article.get("id")
            source_name = article.get("source", "")

            if not headline:
                continue

            raw_text = f"{headline}\n\n{summary}" if summary else headline

            payloads.append(DocumentPayload(
                source_key=self.source_key,
                source_type=SourceType.NEWS,
                source_tier=SourceTier.TIER_2,
                ticker=ticker,
                title=headline,
                url=url or None,
                published_at=published,
                author=source_name,
                external_id=str(article_id) if article_id else None,
                raw_text=raw_text,
                metadata={
                    "source_name": source_name,
                    "category": article.get("category", ""),
                    "related": article.get("related", ""),
                },
            ))

        logger.info("Finnhub: fetched %d articles for %s (days=%d)", len(payloads), ticker, days)
        return payloads
