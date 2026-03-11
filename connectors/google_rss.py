"""Google News RSS connector: fetches news articles via Google News RSS feed."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional
from email.utils import parsedate_to_datetime

from models import SourceType, SourceTier
from connectors.base import DocumentConnector, DocumentPayload

logger = logging.getLogger(__name__)


def _parse_rss_date(date_str: str) -> Optional[datetime]:
    """Parse RSS date string (RFC 2822 format)."""
    try:
        return parsedate_to_datetime(date_str)
    except Exception:
        return None


class GoogleRSSConnector(DocumentConnector):
    """Fetches news via Google News RSS feed for a ticker."""

    @property
    def source_key(self) -> str:
        return "news_google_rss"

    def fetch(self, ticker: str, days: int = 7) -> list[DocumentPayload]:
        try:
            import feedparser
        except ImportError:
            logger.error("feedparser not installed; pip install feedparser")
            return []

        url = f"https://news.google.com/rss/search?q={ticker}+stock&hl=en-US&gl=US&ceid=US:en"
        cutoff = datetime.utcnow() - timedelta(days=days)

        try:
            feed = feedparser.parse(url)
        except Exception as e:
            logger.error("Google RSS fetch failed for %s: %s", ticker, e)
            return []

        payloads = []
        for entry in feed.get("entries", []):
            published = _parse_rss_date(entry.get("published", ""))
            if published and published.replace(tzinfo=None) < cutoff:
                continue

            title = entry.get("title", "")
            link = entry.get("link", "")

            # Google News RSS provides titles + links but not full text
            # The summary field has a brief snippet
            summary = entry.get("summary", "")
            source_name = entry.get("source", {}).get("title", "")

            payloads.append(DocumentPayload(
                source_key=self.source_key,
                source_type=SourceType.NEWS,
                source_tier=SourceTier.TIER_3,
                ticker=ticker,
                title=title,
                url=link,
                published_at=published.replace(tzinfo=None) if published else None,
                author=source_name,
                external_id=None,  # Google RSS has no stable ID; dedupe on URL
                raw_text=f"{title}\n\n{summary}" if summary else title,
                metadata={"source_name": source_name},
            ))

        logger.info("Google RSS: fetched %d articles for %s (days=%d)", len(payloads), ticker, days)
        return payloads
