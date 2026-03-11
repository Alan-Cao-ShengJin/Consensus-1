"""Press Release RSS connector: fetches from PR Newswire / GlobeNewswire RSS feeds."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional
from email.utils import parsedate_to_datetime

from models import SourceType, SourceTier
from connectors.base import DocumentConnector, DocumentPayload

logger = logging.getLogger(__name__)


# PR Newswire search feed URL
_PRNEWSWIRE_RSS = "https://www.prnewswire.com/rss/news-releases-list.rss"
_GLOBENEWSWIRE_RSS = "https://www.globenewswire.com/RssFeed/subjectcode/01-Debt%20Financing/feedTitle/GlobeNewswire%20-%20Debt%20Financing"


def _parse_rss_date(date_str: str) -> Optional[datetime]:
    try:
        return parsedate_to_datetime(date_str)
    except Exception:
        return None


class PRRSSConnector(DocumentConnector):
    """Fetches press releases via RSS feeds, filtered by ticker mention in title."""

    def __init__(self, feed_urls: Optional[list[str]] = None):
        self._feed_urls = feed_urls or [_PRNEWSWIRE_RSS]

    @property
    def source_key(self) -> str:
        return "press_release_rss"

    def fetch(self, ticker: str, days: int = 7) -> list[DocumentPayload]:
        try:
            import feedparser
        except ImportError:
            logger.error("feedparser not installed; pip install feedparser")
            return []

        cutoff = datetime.utcnow() - timedelta(days=days)
        payloads = []

        for feed_url in self._feed_urls:
            try:
                feed = feedparser.parse(feed_url)
            except Exception as e:
                logger.warning("PR RSS fetch failed for %s: %s", feed_url, e)
                continue

            for entry in feed.get("entries", []):
                title = entry.get("title", "")
                # Filter: only include entries that mention the ticker
                if ticker.upper() not in title.upper():
                    continue

                published = _parse_rss_date(entry.get("published", ""))
                if published and published.replace(tzinfo=None) < cutoff:
                    continue

                link = entry.get("link", "")
                summary = entry.get("summary", "")

                payloads.append(DocumentPayload(
                    source_key=self.source_key,
                    source_type=SourceType.PRESS_RELEASE,
                    source_tier=SourceTier.TIER_1,
                    ticker=ticker,
                    title=title,
                    url=link,
                    published_at=published.replace(tzinfo=None) if published else None,
                    author=entry.get("author", ""),
                    external_id=None,  # dedupe on URL
                    raw_text=f"{title}\n\n{summary}" if summary else title,
                    metadata={"feed_url": feed_url},
                ))

        logger.info("PR RSS: fetched %d press releases for %s (days=%d)", len(payloads), ticker, days)
        return payloads
