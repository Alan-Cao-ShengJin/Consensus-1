"""Press Release RSS connector: broadcast scanner for PR Newswire / GlobeNewswire.

Fetches the full RSS feed once, then matches headlines against our entire
universe of ~500 tickers. Any press release mentioning a tracked company
gets ingested — no per-ticker search needed.

Two modes:
  - fetch(ticker, days)     — per-ticker (uses cached feed, for pipeline_runner compatibility)
  - scan_all(tickers, days) — broadcast scan (fetch once, match all tickers)
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Optional
from email.utils import parsedate_to_datetime

from models import SourceType, SourceTier
from connectors.base import DocumentConnector, DocumentPayload

logger = logging.getLogger(__name__)


# RSS feed URLs — firehose feeds covering all companies
_FEED_URLS = [
    "https://www.prnewswire.com/rss/news-releases-list.rss",
    "https://www.globenewswire.com/RssFeed/orgClass/1/feedTitle/GlobeNewswire%20-%20All%20News",
]

# Common words that happen to be tickers — skip to avoid false matches.
# All single-letter and most two-letter tickers are too ambiguous for
# headline matching without NLP — better to miss a rare press release
# than to flood the system with false positives.
_TICKER_STOPWORDS = {
    # Single letter tickers (A, C, D, F, etc.)
    "A", "B", "C", "D", "E", "F", "G", "J", "K", "L", "M", "O", "R",
    "S", "T", "U", "V", "W", "X", "Y", "Z",
    # Two-letter tickers that are common words/abbreviations
    "AI", "AM", "AN", "AR", "AS", "AT", "BE", "BR", "BY", "CF", "CI",
    "CL", "CO", "CP", "DD", "DE", "DG", "DO", "ED", "EL", "ES", "FE",
    "GE", "GL", "GO", "GS", "HD", "HE", "HP", "HR", "IF", "II", "IN",
    "IP", "IR", "IS", "IT", "KO", "LB", "LW", "MA", "MO", "MS",
    "NI", "NO", "ON", "OR", "OS", "OX", "PH", "PG", "PM", "RE", "RL",
    "RO", "SE", "SO", "SQ", "SW", "TT", "TV", "UP", "US", "WM",
    # Short words that are tickers
    "ALL", "AMP", "ARE", "BIG", "CAN", "CAR", "CEO", "DAY", "DOW",
    "FOR", "HAS", "HIS", "HOW", "ICE", "ITS", "KEY", "LOW", "MAN",
    "MAY", "NET", "NEW", "NOW", "NRG", "OLD", "ONE", "OUR", "OUT",
    "PAY", "RUN", "SEE", "SHE", "THE", "TIP", "TOP", "TSN", "TWO",
    "VIA", "WAS", "WAR", "WHO", "WHY", "YOU",
}


def _parse_rss_date(date_str: str) -> Optional[datetime]:
    try:
        return parsedate_to_datetime(date_str)
    except Exception:
        return None


def _find_tickers_in_text(text: str, universe: set[str]) -> list[str]:
    """Find which tickers from the universe are mentioned in text.

    Uses word boundary matching to avoid false positives like
    "AMD" matching inside "DAMAGE".
    """
    text_upper = text.upper()
    found = []
    for ticker in universe:
        if ticker in _TICKER_STOPWORDS:
            continue
        # Word boundary match: ticker must be a standalone word or
        # surrounded by non-alpha chars (handles "$NVDA", "(NVDA)", "NVDA:")
        pattern = r'(?<![A-Z])' + re.escape(ticker) + r'(?![A-Z])'
        if re.search(pattern, text_upper):
            found.append(ticker)
    return found


class PRRSSConnector(DocumentConnector):
    """Broadcast press release scanner.

    Fetches RSS feeds once, caches entries, matches against universe tickers.
    """

    def __init__(self, feed_urls: Optional[list[str]] = None):
        self._feed_urls = feed_urls or _FEED_URLS
        self._cached_entries: Optional[list[dict]] = None

    @property
    def source_key(self) -> str:
        return "press_release_rss"

    def _fetch_feeds(self, days: int = 7) -> list[dict]:
        """Fetch and cache all RSS entries from all feeds."""
        if self._cached_entries is not None:
            return self._cached_entries

        try:
            import feedparser
        except ImportError:
            logger.error("feedparser not installed; pip install feedparser")
            return []

        cutoff = datetime.utcnow() - timedelta(days=days)
        entries = []

        for feed_url in self._feed_urls:
            try:
                feed = feedparser.parse(feed_url)
                for entry in feed.get("entries", []):
                    published = _parse_rss_date(entry.get("published", ""))
                    if published and published.replace(tzinfo=None) < cutoff:
                        continue
                    entries.append({
                        "title": entry.get("title", ""),
                        "link": entry.get("link", ""),
                        "summary": entry.get("summary", ""),
                        "published": published.replace(tzinfo=None) if published else None,
                        "author": entry.get("author", ""),
                        "feed_url": feed_url,
                    })
                logger.info("PR RSS: %d entries from %s", len(feed.get("entries", [])), feed_url)
            except Exception as e:
                logger.warning("PR RSS fetch failed for %s: %s", feed_url, e)

        self._cached_entries = entries
        logger.info("PR RSS: %d total entries cached (days=%d)", len(entries), days)
        return entries

    def fetch(self, ticker: str, days: int = 7) -> list[DocumentPayload]:
        """Per-ticker fetch (pipeline_runner compatibility). Uses cached feed."""
        entries = self._fetch_feeds(days)
        return self._match_entries(entries, {ticker}).get(ticker, [])

    def scan_all(
        self,
        tickers: set[str],
        days: int = 7,
        name_to_ticker: Optional[dict[str, str]] = None,
    ) -> dict[str, list[DocumentPayload]]:
        """Broadcast scan: fetch feeds once, match against entire ticker universe.

        Args:
            tickers: Set of ticker symbols to match.
            days: Lookback period for RSS entries.
            name_to_ticker: Optional {company_name_upper: ticker} map for
                matching full company names (e.g., "NVIDIA" → "NVDA").

        Returns {ticker: [DocumentPayload, ...]} for all tickers with matches.
        """
        self._cached_entries = None  # force fresh fetch
        entries = self._fetch_feeds(days)
        result = self._match_entries(entries, tickers, name_to_ticker)
        total = sum(len(v) for v in result.values())
        logger.info("PR RSS broadcast: %d press releases matched %d tickers",
                     total, len(result))
        return result

    def _match_entries(
        self,
        entries: list[dict],
        universe: set[str],
        name_to_ticker: Optional[dict[str, str]] = None,
    ) -> dict[str, list[DocumentPayload]]:
        """Match RSS entries against tickers and optional company names."""
        result: dict[str, list[DocumentPayload]] = {}

        for entry in entries:
            title = entry["title"]
            summary = entry.get("summary", "")
            search_text = f"{title} {summary}"

            matched_tickers = _find_tickers_in_text(search_text, universe)

            # Also match company names (e.g., "NVIDIA" → NVDA)
            if name_to_ticker:
                text_upper = search_text.upper()
                for name, ticker in name_to_ticker.items():
                    if ticker not in matched_tickers and name in text_upper:
                        matched_tickers.append(ticker)
            if not matched_tickers:
                continue

            for ticker in matched_tickers:
                payload = DocumentPayload(
                    source_key=self.source_key,
                    source_type=SourceType.PRESS_RELEASE,
                    source_tier=SourceTier.TIER_1,
                    ticker=ticker,
                    title=title,
                    url=entry["link"],
                    published_at=entry["published"],
                    author=entry["author"],
                    external_id=None,  # dedupe on URL
                    raw_text=f"{title}\n\n{summary}" if summary else title,
                    metadata={
                        "feed_url": entry["feed_url"],
                        "matched_tickers": matched_tickers,
                    },
                )
                result.setdefault(ticker, []).append(payload)

        return result
