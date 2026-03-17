"""NewsAPI connector: fetches news articles via NewsAPI.org (requires NEWSAPI_KEY)."""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta

import requests
from dotenv import load_dotenv

load_dotenv()

from models import SourceType, SourceTier
from connectors.base import DocumentConnector, DocumentPayload

logger = logging.getLogger(__name__)


class NewsAPIConnector(DocumentConnector):
    """Fetches news via NewsAPI.org. Skips gracefully if NEWSAPI_KEY is not set."""

    def __init__(self):
        self._api_key = os.getenv("NEWSAPI_KEY", "")

    @property
    def source_key(self) -> str:
        return "newsapi"

    @property
    def available(self) -> bool:
        return bool(self._api_key)

    def fetch(self, ticker: str, days: int = 7) -> list[DocumentPayload]:
        if not self._api_key:
            logger.info("NewsAPI: NEWSAPI_KEY not set, skipping")
            return []

        from_date = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
        url = "https://newsapi.org/v2/everything"
        params = {
            "q": f"{ticker} stock",
            "from": from_date,
            "sortBy": "publishedAt",
            "language": "en",
            "pageSize": 50,
            "apiKey": self._api_key,
        }

        try:
            resp = requests.get(url, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.error("NewsAPI fetch failed for %s: %s", ticker, e)
            return []

        articles = data.get("articles", [])
        payloads = []

        for article in articles:
            published_str = article.get("publishedAt", "")
            try:
                published = datetime.fromisoformat(published_str.replace("Z", "+00:00")).replace(tzinfo=None)
            except (ValueError, AttributeError):
                published = None

            title = article.get("title", "")
            content = article.get("content", "") or article.get("description", "") or ""

            payloads.append(DocumentPayload(
                source_key=self.source_key,
                source_type=SourceType.NEWS,
                source_tier=SourceTier.TIER_3,
                ticker=ticker,
                title=title,
                url=article.get("url"),
                published_at=published,
                author=article.get("author", ""),
                external_id=None,  # dedupe on URL
                raw_text=f"{title}\n\n{content}" if content else title,
                metadata={"source_name": article.get("source", {}).get("name", "")},
            ))

        logger.info("NewsAPI: fetched %d articles for %s (days=%d)", len(payloads), ticker, days)
        return payloads
