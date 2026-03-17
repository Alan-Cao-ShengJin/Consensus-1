"""Source registry: declarative config for all v1 data sources.

Each entry describes a source the system can pull from, including how it maps
into the schema, its pull schedule, and whether it feeds claim extraction.
Connectors read this registry to know what to pull and how to ingest it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import logging

from models import SourceType, SourceTier

logger = logging.getLogger(__name__)


class AutomationLevel(str, Enum):
    AUTOMATIC = "automatic"
    SEMI_AUTOMATIC = "semi_automatic"
    MANUAL = "manual"


class PullFrequency(str, Enum):
    DAILY = "daily"
    EVERY_4H = "every_4h"
    EVERY_6H = "every_6h"
    WEEKLY = "weekly"
    POST_EVENT = "post_event"
    ON_DEMAND = "on_demand"


@dataclass(frozen=True)
class SourceConfig:
    """Declarative configuration for a single data source."""

    key: str                            # unique registry key, e.g. "sec_10k"
    source_type: SourceType             # maps to Document.source_type
    source_tier: SourceTier             # default tier for documents from this source
    provider: str                       # e.g. "sec_edgar", "newsapi", "yfinance"
    pull_frequency: PullFrequency
    automation: AutomationLevel
    feeds_claims: bool                  # whether docs go through claim extraction
    creates_checkpoints: bool           # whether this source creates Checkpoint rows
    backfill_depth_days: int            # how far back to pull on first run (0 = none)
    dedupe_key: str                     # what field(s) prevent duplicates
    enabled: bool = True                # toggle source on/off without removing config

    # Optional overrides
    api_key_env_var: Optional[str] = None       # env var name for API key
    rate_limit_per_second: Optional[float] = None
    notes: str = ""


# ---------------------------------------------------------------------------
# v1 Source Registry
# ---------------------------------------------------------------------------

SOURCES: dict[str, SourceConfig] = {}


def _register(cfg: SourceConfig) -> SourceConfig:
    SOURCES[cfg.key] = cfg
    return cfg


# --- SEC Filings ---

_register(SourceConfig(
    key="sec_10k",
    source_type=SourceType.TEN_K,
    source_tier=SourceTier.TIER_1,
    provider="sec_edgar",
    pull_frequency=PullFrequency.DAILY,
    automation=AutomationLevel.AUTOMATIC,
    feeds_claims=True,
    creates_checkpoints=False,
    backfill_depth_days=1095,  # 3 years
    dedupe_key="url",
    rate_limit_per_second=10.0,
    notes="Parse MD&A section for claim extraction. Full filing stored as raw_text.",
))

_register(SourceConfig(
    key="sec_10q",
    source_type=SourceType.TEN_Q,
    source_tier=SourceTier.TIER_1,
    provider="sec_edgar",
    pull_frequency=PullFrequency.DAILY,
    automation=AutomationLevel.AUTOMATIC,
    feeds_claims=True,
    creates_checkpoints=False,
    backfill_depth_days=365,
    dedupe_key="url",
    rate_limit_per_second=10.0,
    notes="Quarterly report. Shorter than 10-K, same extraction pipeline.",
))

_register(SourceConfig(
    key="sec_8k",
    source_type=SourceType.EIGHT_K,
    source_tier=SourceTier.TIER_1,
    provider="sec_edgar",
    pull_frequency=PullFrequency.DAILY,
    automation=AutomationLevel.AUTOMATIC,
    feeds_claims=True,
    creates_checkpoints=True,
    backfill_depth_days=365,
    dedupe_key="url",
    rate_limit_per_second=10.0,
    notes="Material events. Creates checkpoints for mgmt changes, M&A, guidance.",
))

_register(SourceConfig(
    key="sec_13f",
    source_type=SourceType.THIRTEEN_F,
    source_tier=SourceTier.TIER_2,
    provider="sec_edgar",
    pull_frequency=PullFrequency.WEEKLY,
    automation=AutomationLevel.SEMI_AUTOMATIC,
    feeds_claims=True,
    creates_checkpoints=False,
    backfill_depth_days=365,
    dedupe_key="external_id",
    rate_limit_per_second=10.0,
    notes="13F-HR institutional holdings. Filed quarterly by hedge funds/mutual funds. ~45 day delay.",
))

# --- Earnings Transcripts ---

_register(SourceConfig(
    key="earnings_transcript_manual",
    source_type=SourceType.EARNINGS_TRANSCRIPT,
    source_tier=SourceTier.TIER_1,
    provider="manual_upload",
    pull_frequency=PullFrequency.ON_DEMAND,
    automation=AutomationLevel.MANUAL,
    feeds_claims=True,
    creates_checkpoints=False,
    backfill_depth_days=365,
    dedupe_key="hash",
    notes="User pastes or uploads transcript. Highest-value text source for claims.",
))

# --- FMP Earnings Transcripts (automated) ---

_register(SourceConfig(
    key="earnings_transcript_fmp",
    source_type=SourceType.EARNINGS_TRANSCRIPT,
    source_tier=SourceTier.TIER_1,
    provider="fmp",
    pull_frequency=PullFrequency.DAILY,
    automation=AutomationLevel.AUTOMATIC,
    feeds_claims=True,
    creates_checkpoints=False,
    backfill_depth_days=365,
    dedupe_key="external_id",
    api_key_env_var="FMP_API_KEY",
    rate_limit_per_second=5.0,
    notes="FMP earnings call transcripts. Highest-value automated text source.",
))

# --- FMP Structured Financials ---

_register(SourceConfig(
    key="financials_fmp",
    source_type=SourceType.TEN_Q,
    source_tier=SourceTier.TIER_1,
    provider="fmp",
    pull_frequency=PullFrequency.DAILY,
    automation=AutomationLevel.AUTOMATIC,
    feeds_claims=True,
    creates_checkpoints=False,
    backfill_depth_days=365,
    dedupe_key="external_id",
    api_key_env_var="FMP_API_KEY",
    rate_limit_per_second=5.0,
    notes="FMP structured financials (income, balance sheet, cash flow). JSON->text for claims.",
))

# --- FMP Consensus Estimates ---

_register(SourceConfig(
    key="consensus_estimates_fmp",
    source_type=SourceType.NEWS,
    source_tier=SourceTier.TIER_2,
    provider="fmp",
    pull_frequency=PullFrequency.DAILY,
    automation=AutomationLevel.AUTOMATIC,
    feeds_claims=True,
    creates_checkpoints=False,
    backfill_depth_days=365,
    dedupe_key="external_id",
    api_key_env_var="FMP_API_KEY",
    rate_limit_per_second=5.0,
    notes="FMP analyst consensus estimates. Beat/miss comparison drives conviction.",
))

_register(SourceConfig(
    key="news_fmp",
    source_type=SourceType.NEWS,
    source_tier=SourceTier.TIER_2,
    provider="fmp",
    pull_frequency=PullFrequency.DAILY,
    automation=AutomationLevel.AUTOMATIC,
    feeds_claims=True,
    creates_checkpoints=False,
    backfill_depth_days=30,
    dedupe_key="content_hash",
    api_key_env_var="FMP_API_KEY",
    rate_limit_per_second=5.0,
    notes="FMP stock news feed. May return general feed on starter plan.",
))

# --- Alpha Vantage ---

_register(SourceConfig(
    key="earnings_transcript_defeatbeta",
    source_type=SourceType.EARNINGS_TRANSCRIPT,
    source_tier=SourceTier.TIER_1,
    provider="defeatbeta",
    pull_frequency=PullFrequency.WEEKLY,
    automation=AutomationLevel.AUTOMATIC,
    feeds_claims=True,
    creates_checkpoints=False,
    backfill_depth_days=730,  # 2 years
    dedupe_key="external_id",
    notes="Free earnings call transcripts from HuggingFace parquet. No API key needed.",
))

_register(SourceConfig(
    key="earnings_alphavantage",
    source_type=SourceType.EARNINGS_TRANSCRIPT,
    source_tier=SourceTier.TIER_1,
    provider="alphavantage",
    pull_frequency=PullFrequency.DAILY,
    automation=AutomationLevel.AUTOMATIC,
    feeds_claims=True,
    creates_checkpoints=False,
    backfill_depth_days=365,
    dedupe_key="external_id",
    api_key_env_var="ALPHAVANTAGE_API_KEY",
    rate_limit_per_second=0.2,  # 25 requests/day free tier
    notes="Alpha Vantage quarterly earnings with beat/miss surprise data. Tier 1.",
))

# --- Press Releases ---

_register(SourceConfig(
    key="press_release_rss",
    source_type=SourceType.PRESS_RELEASE,
    source_tier=SourceTier.TIER_1,
    provider="rss_prnewswire",
    pull_frequency=PullFrequency.EVERY_6H,
    automation=AutomationLevel.AUTOMATIC,
    feeds_claims=True,
    creates_checkpoints=True,
    backfill_depth_days=90,
    dedupe_key="url",
    notes="PR Newswire / GlobeNewswire RSS feeds filtered by universe tickers.",
))

# --- News ---

_register(SourceConfig(
    key="news_finnhub",
    source_type=SourceType.NEWS,
    source_tier=SourceTier.TIER_2,
    provider="finnhub",
    pull_frequency=PullFrequency.EVERY_4H,
    automation=AutomationLevel.AUTOMATIC,
    feeds_claims=True,
    creates_checkpoints=False,
    backfill_depth_days=365,
    dedupe_key="url",
    api_key_env_var="FINNHUB_API_KEY",
    rate_limit_per_second=1.0,
    enabled=True,
    notes="Free tier: 60 req/min. /company-news endpoint filters by ticker natively. 1-year archive.",
))

_register(SourceConfig(
    key="news_google_rss",
    source_type=SourceType.NEWS,
    source_tier=SourceTier.TIER_3,
    provider="google_news_rss",
    pull_frequency=PullFrequency.EVERY_4H,
    automation=AutomationLevel.AUTOMATIC,
    feeds_claims=True,
    creates_checkpoints=False,
    backfill_depth_days=7,
    dedupe_key="url",
    notes="Free, no API key. Lower quality, more noise. Supplementary source.",
))

_register(SourceConfig(
    key="news_manual",
    source_type=SourceType.NEWS,
    source_tier=SourceTier.TIER_2,
    provider="manual_upload",
    pull_frequency=PullFrequency.ON_DEMAND,
    automation=AutomationLevel.MANUAL,
    feeds_claims=True,
    creates_checkpoints=False,
    backfill_depth_days=0,
    dedupe_key="url",
    notes="User pastes paywalled articles (FT, WSJ, Bloomberg).",
))

# --- Broker Reports ---

_register(SourceConfig(
    key="broker_report_manual",
    source_type=SourceType.BROKER_REPORT,
    source_tier=SourceTier.TIER_1,
    provider="manual_upload",
    pull_frequency=PullFrequency.ON_DEMAND,
    automation=AutomationLevel.MANUAL,
    feeds_claims=True,
    creates_checkpoints=False,
    backfill_depth_days=0,
    dedupe_key="hash",
    notes="User uploads broker PDF. System extracts text, runs claim extraction.",
))

# --- Investor Presentations ---

_register(SourceConfig(
    key="investor_presentation_manual",
    source_type=SourceType.INVESTOR_PRESENTATION,
    source_tier=SourceTier.TIER_2,
    provider="manual_upload",
    pull_frequency=PullFrequency.ON_DEMAND,
    automation=AutomationLevel.MANUAL,
    feeds_claims=True,
    creates_checkpoints=False,
    backfill_depth_days=0,
    dedupe_key="hash",
    notes="Slide decks from company IR pages. Requires PDF-to-text extraction.",
))

# --- Market Data (non-document sources) ---

_register(SourceConfig(
    key="price_daily",
    source_type=SourceType.NEWS,       # placeholder — not a real document type
    source_tier=SourceTier.TIER_1,
    provider="yfinance",
    pull_frequency=PullFrequency.DAILY,
    automation=AutomationLevel.AUTOMATIC,
    feeds_claims=False,
    creates_checkpoints=False,
    backfill_depth_days=730,  # 2 years
    dedupe_key="ticker_date",
    notes="OHLCV price data. Stored in prices table (Step 6+), not documents.",
))

_register(SourceConfig(
    key="earnings_calendar",
    source_type=SourceType.NEWS,       # placeholder — not a real document type
    source_tier=SourceTier.TIER_1,
    provider="yfinance",
    pull_frequency=PullFrequency.DAILY,
    automation=AutomationLevel.AUTOMATIC,
    feeds_claims=False,
    creates_checkpoints=True,
    backfill_depth_days=0,
    dedupe_key="ticker_checkpoint_type_date",
    notes="Creates checkpoint rows for upcoming earnings dates.",
))

# --- Macro Data Sources ---

_register(SourceConfig(
    key="news_macro_rss",
    source_type=SourceType.NEWS,
    source_tier=SourceTier.TIER_2,
    provider="macro_rss",
    pull_frequency=PullFrequency.EVERY_6H,
    automation=AutomationLevel.AUTOMATIC,
    feeds_claims=True,
    creates_checkpoints=False,
    backfill_depth_days=7,
    dedupe_key="url",
    notes="Macro news headlines from Google News RSS (Fed, inflation, GDP, trade wars). MACRO pseudo-ticker.",
))

_register(SourceConfig(
    key="macro_fred",
    source_type=SourceType.NEWS,       # placeholder — stored as prices, not documents
    source_tier=SourceTier.TIER_1,
    provider="fred",
    pull_frequency=PullFrequency.DAILY,
    automation=AutomationLevel.AUTOMATIC,
    feeds_claims=False,
    creates_checkpoints=False,
    backfill_depth_days=365,
    dedupe_key="ticker_date",
    api_key_env_var="FRED_API_KEY",
    notes="FRED economic indicators: Fed funds rate, yield curve, CPI, unemployment, VIX, DXY, consumer sentiment.",
))

_register(SourceConfig(
    key="vix_daily",
    source_type=SourceType.NEWS,       # placeholder — stored as prices
    source_tier=SourceTier.TIER_1,
    provider="yfinance",
    pull_frequency=PullFrequency.DAILY,
    automation=AutomationLevel.AUTOMATIC,
    feeds_claims=False,
    creates_checkpoints=False,
    backfill_depth_days=730,
    dedupe_key="ticker_date",
    notes="CBOE VIX via yfinance. Market fear gauge for sentiment scoring.",
))

_register(SourceConfig(
    key="dxy_daily",
    source_type=SourceType.NEWS,       # placeholder — stored as prices
    source_tier=SourceTier.TIER_2,
    provider="yfinance",
    pull_frequency=PullFrequency.DAILY,
    automation=AutomationLevel.AUTOMATIC,
    feeds_claims=False,
    creates_checkpoints=False,
    backfill_depth_days=730,
    dedupe_key="ticker_date",
    notes="Dollar Index (DXY) via yfinance. Strong dollar = headwind for multinationals.",
))

_register(SourceConfig(
    key="oil_daily",
    source_type=SourceType.NEWS,       # placeholder — stored as prices
    source_tier=SourceTier.TIER_2,
    provider="yfinance",
    pull_frequency=PullFrequency.DAILY,
    automation=AutomationLevel.AUTOMATIC,
    feeds_claims=False,
    creates_checkpoints=False,
    backfill_depth_days=730,
    dedupe_key="ticker_date",
    notes="Crude oil futures (CL=F) via yfinance. Energy cost signal for industrials and transports.",
))

_register(SourceConfig(
    key="credit_spread_daily",
    source_type=SourceType.NEWS,       # placeholder — stored as prices
    source_tier=SourceTier.TIER_2,
    provider="yfinance",
    pull_frequency=PullFrequency.DAILY,
    automation=AutomationLevel.AUTOMATIC,
    feeds_claims=False,
    creates_checkpoints=False,
    backfill_depth_days=730,
    dedupe_key="ticker_date",
    notes="Credit spread proxy (LQD/HYG ratio) via yfinance. Widening spread = credit stress.",
))

_register(SourceConfig(
    key="ticker_master",
    source_type=SourceType.NEWS,       # placeholder — not a real document type
    source_tier=SourceTier.TIER_1,
    provider="yfinance",
    pull_frequency=PullFrequency.WEEKLY,
    automation=AutomationLevel.SEMI_AUTOMATIC,
    feeds_claims=False,
    creates_checkpoints=False,
    backfill_depth_days=0,
    dedupe_key="ticker",
    notes="Enriches companies table with sector, industry, exchange, market cap.",
))


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def get_source(key: str) -> SourceConfig:
    """Look up a source config by key. Raises KeyError if not found."""
    return SOURCES[key]


def get_automatic_sources() -> list[SourceConfig]:
    """Return all enabled automatic sources (for scheduler)."""
    return [s for s in SOURCES.values() if s.enabled and s.automation == AutomationLevel.AUTOMATIC]


def get_sources_by_provider(provider: str) -> list[SourceConfig]:
    """Return all enabled sources for a given provider."""
    return [s for s in SOURCES.values() if s.enabled and s.provider == provider]


def get_claim_sources() -> list[SourceConfig]:
    """Return all enabled sources that feed claim extraction."""
    return [s for s in SOURCES.values() if s.enabled and s.feeds_claims]


def get_checkpoint_sources() -> list[SourceConfig]:
    """Return all enabled sources that create checkpoint rows."""
    return [s for s in SOURCES.values() if s.enabled and s.creates_checkpoints]


# ---------------------------------------------------------------------------
# Universe definition — S&P 500 constituents, refreshed daily
# ---------------------------------------------------------------------------

# Fallback: hardcoded core tickers in case Wikipedia fetch fails
_FALLBACK_TICKERS: list[str] = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA",
    "AMD", "AVGO", "QCOM", "INTC", "MRVL", "MU",
    "CRM", "SNOW", "PLTR", "NOW", "DDOG", "NET", "MDB",
    "V", "MA", "SQ", "PYPL", "COIN",
    "NFLX", "DIS", "RBLX",
    "LLY", "MRNA", "ISRG",
    "ENPH", "FSLR", "CEG", "VST",
    "LMT", "RTX", "GD",
    "GS", "JPM", "BRK-B",
    "UBER", "ABNB", "CRWD", "ZS",
]

_cached_universe: list[str] | None = None
_cached_at: float = 0


def _fetch_sp500_from_wikipedia() -> list[str]:
    """Fetch current S&P 500 constituents from Wikipedia.

    Returns sorted list of ~503 ticker symbols.
    Wikipedia's list is updated within hours of S&P index changes.
    """
    import io
    import requests
    import pandas as pd

    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    headers = {"User-Agent": "Mozilla/5.0 (Consensus-1 Pipeline)"}
    resp = requests.get(url, headers=headers, timeout=15)
    resp.raise_for_status()

    tables = pd.read_html(io.StringIO(resp.text))
    df = tables[0]
    # Clean tickers: some have dots (BRK.B → BRK-B) for Yahoo compatibility
    tickers = sorted(
        df["Symbol"].str.strip().str.replace(".", "-", regex=False).tolist()
    )
    return tickers


def refresh_universe() -> list[str]:
    """Refresh the investment universe from Wikipedia. Call daily.

    Also upserts any new companies into the DB so they can receive signals.
    Returns the updated ticker list.
    """
    global _cached_universe, _cached_at
    import time

    try:
        tickers = _fetch_sp500_from_wikipedia()
        _cached_universe = tickers
        _cached_at = time.time()
        logger.info("Universe refreshed: %d S&P 500 tickers", len(tickers))
        return tickers
    except Exception as e:
        logger.warning("Universe refresh failed, using cache/fallback: %s", e)
        return _cached_universe or _FALLBACK_TICKERS


def get_universe_tickers() -> list[str]:
    """Get the current investment universe.

    Uses cached list if refreshed within the last 24 hours,
    otherwise refreshes from Wikipedia. Falls back to hardcoded
    list if all else fails.
    """
    global _cached_universe, _cached_at
    import time

    # Use cache if less than 24 hours old
    if _cached_universe and (time.time() - _cached_at) < 86400:
        return _cached_universe

    return refresh_universe()


# For backward compatibility — lazy-loaded on first access
class _UniverseProxy(list):
    """Lazy list that fetches S&P 500 tickers on first access."""
    _loaded = False

    def _ensure_loaded(self):
        if not self._loaded:
            self.clear()
            self.extend(get_universe_tickers())
            self._loaded = True

    def __iter__(self):
        self._ensure_loaded()
        return super().__iter__()

    def __len__(self):
        self._ensure_loaded()
        return super().__len__()

    def __contains__(self, item):
        self._ensure_loaded()
        return super().__contains__(item)

    def __getitem__(self, index):
        self._ensure_loaded()
        return super().__getitem__(index)


UNIVERSE_TICKERS = _UniverseProxy()
