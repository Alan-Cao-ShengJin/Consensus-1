"""Narrow proof universe for bounded historical usefulness testing.

Rationale:
- 15 liquid US large-cap names concentrated in semis + hyperscalers + software
- These sectors have the densest public information flow (SEC filings,
  press releases, analyst coverage, news) — exactly where the system
  should add the most value
- Small enough to inspect every decision manually
- Broad enough to expose cross-name differences in thesis evolution
- All names have reliable yfinance price data going back 2+ years

Sector allocation:
- Semiconductors (5): NVDA, AMD, AVGO, QCOM, INTC
  High capex, clear earnings cycles, frequent guidance updates
- Hyperscalers (4): MSFT, GOOGL, AMZN, META
  Dense filing flow, quarterly earnings, strategic pivots
- Enterprise software (4): CRM, PLTR, NOW, CRWD
  SaaS metrics in filings, subscription revenue visibility
- Adjacent tech (2): AAPL, TSLA
  Mega-cap with high news flow, hardware cycles

Override: pass --tickers to use a custom universe.
"""
from __future__ import annotations

PROOF_UNIVERSE_TICKERS: list[str] = [
    # Semiconductors (5)
    "NVDA",
    "AMD",
    "AVGO",
    "QCOM",
    "INTC",
    # Hyperscalers (4)
    "MSFT",
    "GOOGL",
    "AMZN",
    "META",
    # Enterprise software (4)
    "CRM",
    "PLTR",
    "NOW",
    "CRWD",
    # Adjacent tech (2)
    "AAPL",
    "TSLA",
]

PROOF_UNIVERSE_RATIONALE = (
    "15 liquid US large-cap tech names (semis + hyperscalers + enterprise SW + adjacent). "
    "Chosen for dense public information flow and inspectable decision count. "
    "All have reliable price data and SEC filing coverage."
)


def get_proof_universe() -> list[str]:
    """Return the default narrow proof universe."""
    return list(PROOF_UNIVERSE_TICKERS)


def get_proof_universe_rationale() -> str:
    """Return human-readable rationale for the proof universe selection."""
    return PROOF_UNIVERSE_RATIONALE
