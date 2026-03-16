"""Market sentiment signal: aggregate macro risk-on/risk-off indicator.

Combines multiple market-level signals into a single sentiment score that
modulates the decision engine's willingness to initiate new positions or
add to existing ones.

Signals:
  1. VIX level (fear gauge): >25 = elevated fear, >35 = extreme
  2. Yield curve slope (10Y - 2Y): inverted = recession risk
  3. Market trend (benchmark SMA): below 50-day SMA = bearish regime
  4. Dollar strength (DXY): strong dollar = headwind for multinationals
  5. Macro news sentiment: ratio of negative vs positive macro headlines

Output: MarketSentimentScore with a composite risk level (RISK_ON, CAUTIOUS,
RISK_OFF, EXTREME_FEAR) that the decision engine uses to:
  - Block new initiations during RISK_OFF/EXTREME_FEAR
  - Reduce position sizing during CAUTIOUS
  - Allow full activity during RISK_ON

All functions are pure: no API calls, operate on preloaded data.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Optional


class MarketRegime(str, Enum):
    """Market regime classification."""
    RISK_ON = "risk_on"           # all signals green
    CAUTIOUS = "cautious"         # some yellow flags
    RISK_OFF = "risk_off"         # multiple warning signals
    EXTREME_FEAR = "extreme_fear"  # VIX spike + inverted curve + bearish trend


@dataclass(frozen=True)
class MarketSentimentConfig:
    """Configuration for market sentiment scoring."""
    enabled: bool = True

    # VIX thresholds
    vix_elevated: float = 25.0
    vix_extreme: float = 35.0

    # Yield curve (10Y - 2Y spread in basis points)
    yield_curve_inversion_threshold: float = 0.0  # below 0 = inverted

    # Position sizing adjustments by regime
    risk_on_sizing_multiplier: float = 1.0
    cautious_sizing_multiplier: float = 0.7
    risk_off_sizing_multiplier: float = 0.3
    extreme_fear_sizing_multiplier: float = 0.0  # block new positions

    # Initiation blocking
    block_initiations_in_risk_off: bool = True
    block_initiations_in_extreme_fear: bool = True


DISABLED_SENTIMENT_CONFIG = MarketSentimentConfig(enabled=False)
DEFAULT_SENTIMENT_CONFIG = MarketSentimentConfig(enabled=True)


@dataclass
class MarketSentimentScore:
    """Computed market sentiment for a given date."""
    as_of: date
    regime: MarketRegime = MarketRegime.RISK_ON

    # Individual signals
    vix_level: Optional[float] = None
    vix_signal: str = "unknown"   # calm, elevated, extreme

    yield_curve_spread: Optional[float] = None
    yield_curve_signal: str = "unknown"  # normal, flat, inverted

    benchmark_above_sma: Optional[bool] = None
    benchmark_signal: str = "unknown"  # bullish, bearish

    dxy_level: Optional[float] = None
    dxy_signal: str = "unknown"  # weak, neutral, strong

    macro_news_sentiment: Optional[float] = None  # -1.0 (bearish) to +1.0 (bullish)

    # Derived
    risk_score: float = 0.0     # 0 (safe) to 100 (extreme risk)
    sizing_multiplier: float = 1.0
    block_initiations: bool = False
    explanation: str = ""


def compute_market_sentiment(
    as_of: date,
    vix_level: Optional[float] = None,
    yield_curve_spread: Optional[float] = None,
    benchmark_above_sma: Optional[bool] = None,
    dxy_level: Optional[float] = None,
    macro_news_positive: int = 0,
    macro_news_negative: int = 0,
    config: MarketSentimentConfig = DEFAULT_SENTIMENT_CONFIG,
) -> MarketSentimentScore:
    """Compute aggregate market sentiment score.

    Args:
        as_of: Date of the assessment.
        vix_level: CBOE VIX index level.
        yield_curve_spread: 10Y - 2Y Treasury spread (percentage points).
        benchmark_above_sma: Whether benchmark (SPY) is above 50-day SMA.
        dxy_level: Dollar index level.
        macro_news_positive: Count of positive macro headlines in lookback.
        macro_news_negative: Count of negative macro headlines in lookback.
        config: Sentiment configuration.

    Returns:
        MarketSentimentScore with regime classification and action guidance.
    """
    score = MarketSentimentScore(as_of=as_of)

    if not config.enabled:
        return score

    risk_points = 0
    max_points = 0
    reasons = []

    # VIX signal (0-30 points)
    if vix_level is not None:
        score.vix_level = vix_level
        max_points += 30
        if vix_level >= config.vix_extreme:
            risk_points += 30
            score.vix_signal = "extreme"
            reasons.append(f"VIX at {vix_level:.1f} (extreme fear)")
        elif vix_level >= config.vix_elevated:
            risk_points += 20
            score.vix_signal = "elevated"
            reasons.append(f"VIX at {vix_level:.1f} (elevated)")
        else:
            score.vix_signal = "calm"

    # Yield curve (0-25 points)
    if yield_curve_spread is not None:
        score.yield_curve_spread = yield_curve_spread
        max_points += 25
        if yield_curve_spread < config.yield_curve_inversion_threshold:
            risk_points += 25
            score.yield_curve_signal = "inverted"
            reasons.append(f"Yield curve inverted ({yield_curve_spread:.2f}%)")
        elif yield_curve_spread < 0.5:
            risk_points += 10
            score.yield_curve_signal = "flat"
            reasons.append(f"Yield curve flat ({yield_curve_spread:.2f}%)")
        else:
            score.yield_curve_signal = "normal"

    # Benchmark trend (0-25 points)
    if benchmark_above_sma is not None:
        max_points += 25
        if not benchmark_above_sma:
            risk_points += 25
            score.benchmark_signal = "bearish"
            reasons.append("Benchmark below 50-day SMA")
        else:
            score.benchmark_signal = "bullish"
        score.benchmark_above_sma = benchmark_above_sma

    # DXY strength (0-10 points)
    if dxy_level is not None:
        score.dxy_level = dxy_level
        max_points += 10
        if dxy_level > 105:
            risk_points += 10
            score.dxy_signal = "strong"
            reasons.append(f"Dollar strong (DXY {dxy_level:.1f})")
        elif dxy_level < 95:
            score.dxy_signal = "weak"
        else:
            score.dxy_signal = "neutral"

    # Macro news sentiment (0-10 points)
    total_news = macro_news_positive + macro_news_negative
    if total_news > 0:
        sentiment_ratio = (macro_news_positive - macro_news_negative) / total_news
        score.macro_news_sentiment = sentiment_ratio
        max_points += 10
        if sentiment_ratio < -0.3:
            risk_points += 10
            reasons.append(f"Macro news bearish ({sentiment_ratio:.2f})")
        elif sentiment_ratio < 0:
            risk_points += 5

    # Compute composite risk score
    if max_points > 0:
        score.risk_score = (risk_points / max_points) * 100.0
    else:
        score.risk_score = 0.0

    # Classify regime
    if score.risk_score >= 75:
        score.regime = MarketRegime.EXTREME_FEAR
        score.sizing_multiplier = config.extreme_fear_sizing_multiplier
        score.block_initiations = config.block_initiations_in_extreme_fear
    elif score.risk_score >= 50:
        score.regime = MarketRegime.RISK_OFF
        score.sizing_multiplier = config.risk_off_sizing_multiplier
        score.block_initiations = config.block_initiations_in_risk_off
    elif score.risk_score >= 25:
        score.regime = MarketRegime.CAUTIOUS
        score.sizing_multiplier = config.cautious_sizing_multiplier
    else:
        score.regime = MarketRegime.RISK_ON
        score.sizing_multiplier = config.risk_on_sizing_multiplier

    score.explanation = "; ".join(reasons) if reasons else "All signals green"
    return score
