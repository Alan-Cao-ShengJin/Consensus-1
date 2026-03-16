"""Macro news RSS connector: fetches broad market headlines for risk-on/risk-off sentiment.

Fetches from Google News RSS using macro-economic search queries rather than
ticker-specific queries. This captures headlines about:
  - Federal Reserve / interest rate decisions
  - Inflation / CPI / PCE data
  - GDP reports
  - Trade wars / tariffs
  - Geopolitical events (wars, sanctions)
  - Recession indicators
  - Market crashes / rallies

These headlines are ingested as documents and processed through claim extraction
to generate macro-level sentiment signals that the decision engine uses to
modulate position sizing and entry decisions.

The connector uses a MACRO pseudo-ticker to avoid polluting company-specific
document feeds.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional
from email.utils import parsedate_to_datetime

from models import SourceType, SourceTier
from connectors.base import DocumentConnector, DocumentPayload

logger = logging.getLogger(__name__)


# Macro search queries for Google News RSS
MACRO_QUERIES = [
    # Fed and monetary policy
    "Federal+Reserve+interest+rate+decision",
    "Fed+rate+cut+hike+inflation",
    # Inflation
    "CPI+inflation+report+US",
    "PCE+inflation+data",
    # Economy
    "US+GDP+growth+report",
    "US+recession+economy",
    "unemployment+jobs+report+nonfarm",
    # Trade and geopolitics
    "trade+war+tariffs+sanctions",
    "geopolitical+risk+market+impact",
    # Market sentiment
    "stock+market+crash+correction+rally",
    "market+volatility+VIX+fear",
    # Treasury and yields
    "Treasury+yields+bond+market",
    "yield+curve+inversion+recession",
]


def _parse_rss_date(date_str: str) -> Optional[datetime]:
    """Parse RSS date string (RFC 2822 format)."""
    try:
        return parsedate_to_datetime(date_str)
    except Exception:
        return None


class MacroNewsRSSConnector(DocumentConnector):
    """Fetches macro-economic news via Google News RSS.

    Unlike the ticker-specific GoogleRSSConnector, this connector searches
    for broad market/economic headlines and tags them with a special MACRO
    pseudo-ticker.
    """

    @property
    def source_key(self) -> str:
        return "news_macro_rss"

    def fetch(self, ticker: str = "MACRO", days: int = 7) -> list[DocumentPayload]:
        """Fetch macro news headlines.

        The ticker parameter is ignored — this connector always fetches
        macro headlines tagged with the MACRO pseudo-ticker.
        """
        try:
            import feedparser
        except ImportError:
            logger.error("feedparser not installed; pip install feedparser")
            return []

        cutoff = datetime.utcnow() - timedelta(days=days)
        seen_urls: set[str] = set()
        payloads: list[DocumentPayload] = []

        for query in MACRO_QUERIES:
            url = f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"

            try:
                feed = feedparser.parse(url)
            except Exception as e:
                logger.error("Macro RSS fetch failed for query '%s': %s", query, e)
                continue

            for entry in feed.get("entries", []):
                published = _parse_rss_date(entry.get("published", ""))
                if published and published.replace(tzinfo=None) < cutoff:
                    continue

                link = entry.get("link", "")
                if link in seen_urls:
                    continue
                seen_urls.add(link)

                title = entry.get("title", "")
                summary = entry.get("summary", "")
                source_name = entry.get("source", {}).get("title", "")

                # Classify headline sentiment (simple keyword heuristic)
                sentiment = _classify_macro_sentiment(title)

                payloads.append(DocumentPayload(
                    source_key=self.source_key,
                    source_type=SourceType.NEWS,
                    source_tier=SourceTier.TIER_2,
                    ticker="MACRO",
                    title=title,
                    url=link,
                    published_at=published.replace(tzinfo=None) if published else None,
                    author=source_name,
                    external_id=None,
                    raw_text=f"{title}\n\n{summary}" if summary else title,
                    metadata={
                        "source_name": source_name,
                        "macro_query": query,
                        "headline_sentiment": sentiment,
                    },
                ))

        logger.info("Macro RSS: fetched %d macro headlines (days=%d)", len(payloads), days)
        return payloads


def _classify_macro_sentiment(headline: str) -> str:
    """Simple keyword-based sentiment classification for macro headlines.

    Returns 'positive', 'negative', or 'neutral'.
    """
    hl = headline.lower()

    negative_keywords = [
        "crash", "recession", "decline", "plunge", "fear", "sell-off", "selloff",
        "downturn", "collapse", "crisis", "war", "tariff", "sanction",
        "inflation surges", "inflation spikes", "rate hike", "hawkish",
        "layoffs", "unemployment rises", "bear market", "correction",
        "deficit", "debt ceiling", "shutdown", "default", "inverted",
    ]
    positive_keywords = [
        "rally", "surge", "boom", "growth", "recovery", "bull",
        "rate cut", "dovish", "easing", "stimulus", "jobs growth",
        "unemployment falls", "inflation cools", "inflation falls",
        "record high", "all-time high", "strong economy",
        "trade deal", "peace", "ceasefire",
    ]

    neg_count = sum(1 for kw in negative_keywords if kw in hl)
    pos_count = sum(1 for kw in positive_keywords if kw in hl)

    if neg_count > pos_count:
        return "negative"
    elif pos_count > neg_count:
        return "positive"
    return "neutral"
