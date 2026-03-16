"""Priced-in detector: identify when good news is already reflected in stock price.

Problem: The system treats "revenue grew 20%" as bullish even when the stock
already rallied 40% in anticipation. Company management is always optimistic
in transcripts, but the market has already priced in expected growth. When
actual results merely meet expectations, the stock drops — and the system
is caught holding at elevated levels.

Solution: Compare claim sentiment direction with recent price action to detect
divergence. If claims are overwhelmingly positive but the stock has already
run up significantly, the "priced in" flag reduces the effective conviction
boost from those claims.

Signals:
  1. Price-sentiment divergence: positive claims + big price run-up = priced in
  2. Consensus alignment: if everyone (analysts, news, transcripts) is bullish,
     contrarian risk is high
  3. Post-earnings drift: if stock doesn't move on positive earnings, the
     market already knew

All functions are pure: no DB, no side effects.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class PricedInConfig:
    """Configuration for priced-in detection."""
    enabled: bool = True

    # Price run-up thresholds
    # If stock is up >X% over N days and claims are positive, flag as priced-in
    runup_threshold_pct: float = 15.0    # 15% run-up
    runup_lookback_days: int = 60        # over 60 days

    # Post-earnings non-reaction
    # If positive earnings surprise but stock moves <X%, market already knew
    post_earnings_flat_threshold_pct: float = 2.0

    # Claim sentiment ratio
    # If >80% of recent claims are positive, contrarian risk is elevated
    bullish_ratio_threshold: float = 0.80

    # Dampening factors
    priced_in_conviction_dampener: float = 0.5     # reduce conviction boost by 50%
    strong_priced_in_dampener: float = 0.25        # reduce by 75% if multiple signals fire


DISABLED_PRICED_IN_CONFIG = PricedInConfig(enabled=False)
DEFAULT_PRICED_IN_CONFIG = PricedInConfig(enabled=True)


@dataclass
class PricedInSignal:
    """Result of priced-in analysis for a single ticker."""
    ticker: str
    is_priced_in: bool = False
    signal_count: int = 0           # how many priced-in signals fired

    # Individual signals
    price_runup_detected: bool = False
    price_change_pct: Optional[float] = None
    consensus_crowded: bool = False
    bullish_claim_ratio: Optional[float] = None
    post_earnings_flat: bool = False

    # Effective dampener (1.0 = no effect, 0.25 = strong dampening)
    conviction_dampener: float = 1.0
    explanation: str = ""


def detect_priced_in(
    ticker: str,
    price_change_pct_lookback: Optional[float],
    positive_claim_count: int,
    negative_claim_count: int,
    neutral_claim_count: int,
    earnings_surprise_pct: Optional[float] = None,
    post_earnings_price_change_pct: Optional[float] = None,
    config: PricedInConfig = DEFAULT_PRICED_IN_CONFIG,
) -> PricedInSignal:
    """Detect if positive sentiment is already priced into the stock.

    Args:
        ticker: Stock ticker.
        price_change_pct_lookback: Price change over lookback period (e.g., +25.0).
        positive_claim_count: Number of positive claims in recent window.
        negative_claim_count: Number of negative claims.
        neutral_claim_count: Number of neutral/mixed claims.
        earnings_surprise_pct: Earnings surprise % (positive = beat).
        post_earnings_price_change_pct: Price change in days after earnings.
        config: Detection configuration.

    Returns:
        PricedInSignal with detection results and dampener.
    """
    signal = PricedInSignal(ticker=ticker)

    if not config.enabled:
        return signal

    total_claims = positive_claim_count + negative_claim_count + neutral_claim_count
    reasons = []

    # Signal 1: Price run-up with positive sentiment
    if (
        price_change_pct_lookback is not None
        and price_change_pct_lookback > config.runup_threshold_pct
    ):
        signal.price_runup_detected = True
        signal.price_change_pct = price_change_pct_lookback
        signal.signal_count += 1
        reasons.append(
            f"Stock up {price_change_pct_lookback:.1f}% — positive news may be priced in"
        )

    # Signal 2: Consensus crowding (too many bulls)
    if total_claims > 0:
        bullish_ratio = positive_claim_count / total_claims
        signal.bullish_claim_ratio = bullish_ratio
        if bullish_ratio >= config.bullish_ratio_threshold and total_claims >= 3:
            signal.consensus_crowded = True
            signal.signal_count += 1
            reasons.append(
                f"{bullish_ratio:.0%} of claims are positive — contrarian risk"
            )

    # Signal 3: Post-earnings non-reaction
    if (
        earnings_surprise_pct is not None
        and earnings_surprise_pct > 0
        and post_earnings_price_change_pct is not None
        and abs(post_earnings_price_change_pct) < config.post_earnings_flat_threshold_pct
    ):
        signal.post_earnings_flat = True
        signal.signal_count += 1
        reasons.append(
            f"Positive earnings surprise ({earnings_surprise_pct:.1f}%) "
            f"but stock flat ({post_earnings_price_change_pct:+.1f}%)"
        )

    # Determine if priced in and set dampener
    if signal.signal_count >= 2:
        signal.is_priced_in = True
        signal.conviction_dampener = config.strong_priced_in_dampener
    elif signal.signal_count == 1:
        signal.is_priced_in = True
        signal.conviction_dampener = config.priced_in_conviction_dampener

    signal.explanation = "; ".join(reasons) if reasons else "No priced-in signals"
    return signal


def apply_priced_in_dampening(
    raw_conviction_delta: float,
    priced_in_signal: PricedInSignal,
) -> float:
    """Apply priced-in dampening to a conviction delta.

    Only dampens positive deltas (bullish evidence). Negative deltas
    (bearish evidence) are NOT dampened — bad news on a priced-in stock
    should still move conviction down.

    Returns adjusted delta.
    """
    if not priced_in_signal.is_priced_in:
        return raw_conviction_delta

    # Only dampen positive (bullish) deltas
    if raw_conviction_delta <= 0:
        return raw_conviction_delta

    return raw_conviction_delta * priced_in_signal.conviction_dampener
