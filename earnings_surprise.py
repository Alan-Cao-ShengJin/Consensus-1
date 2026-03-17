"""Earnings surprise bucketing: compare actuals vs consensus estimates.

The market moves on SURPRISE — not absolute numbers. A company reporting
record revenue can still drop 10% if it missed the consensus estimate.

Surprise buckets:
  BIG_MISS:    actual well below consensus (< -5%)
  SMALL_MISS:  slight miss (-5% to -2%)
  INLINE:      within noise band (-2% to +2%)
  SMALL_BEAT:  modest beat (+2% to +5%)
  BIG_BEAT:    blowout quarter (> +5%)

Thresholds are configurable per metric (EPS surprises tend to be wider
than revenue surprises because EPS has more variance).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Surprise bucket constants
# ---------------------------------------------------------------------------

class SurpriseBucket:
    BIG_MISS = "big_miss"
    SMALL_MISS = "small_miss"
    INLINE = "inline"
    SMALL_BEAT = "small_beat"
    BIG_BEAT = "big_beat"


# Direction mapping: how each bucket affects conviction
BUCKET_DIRECTION = {
    SurpriseBucket.BIG_MISS: "negative",
    SurpriseBucket.SMALL_MISS: "negative",
    SurpriseBucket.INLINE: "neutral",
    SurpriseBucket.SMALL_BEAT: "positive",
    SurpriseBucket.BIG_BEAT: "positive",
}

# Strength mapping: how strongly each bucket should influence conviction
BUCKET_STRENGTH = {
    SurpriseBucket.BIG_MISS: 0.95,
    SurpriseBucket.SMALL_MISS: 0.6,
    SurpriseBucket.INLINE: 0.2,
    SurpriseBucket.SMALL_BEAT: 0.5,
    SurpriseBucket.BIG_BEAT: 0.9,
}


# ---------------------------------------------------------------------------
# Threshold configuration
# ---------------------------------------------------------------------------

@dataclass
class SurpriseThresholds:
    """Configurable thresholds for surprise bucketing.

    Revenue thresholds are tighter than EPS because revenue has less
    variance (large companies rarely miss revenue by >5%).
    """
    # Revenue surprise thresholds (%)
    revenue_big_miss: float = -5.0
    revenue_small_miss: float = -2.0
    revenue_small_beat: float = 2.0
    revenue_big_beat: float = 5.0

    # EPS surprise thresholds (%) — wider because EPS is more volatile
    eps_big_miss: float = -10.0
    eps_small_miss: float = -3.0
    eps_small_beat: float = 3.0
    eps_big_beat: float = 10.0


DEFAULT_THRESHOLDS = SurpriseThresholds()


# ---------------------------------------------------------------------------
# Surprise computation
# ---------------------------------------------------------------------------

@dataclass
class SurpriseResult:
    """Result of comparing actuals vs estimates for one metric."""
    metric: str                   # "revenue" or "eps"
    actual: float
    estimate: float
    surprise_pct: float           # (actual - estimate) / |estimate| * 100
    bucket: str                   # SurpriseBucket value
    direction: str                # positive / negative / neutral
    strength: float               # 0-1 signal strength
    num_analysts: Optional[int] = None


@dataclass
class EarningsSurprise:
    """Full earnings surprise for a quarter: revenue + EPS."""
    ticker: str
    fiscal_period: Optional[str] = None
    revenue: Optional[SurpriseResult] = None
    eps: Optional[SurpriseResult] = None
    composite_bucket: Optional[str] = None
    composite_direction: Optional[str] = None
    composite_strength: Optional[float] = None

    def __post_init__(self):
        """Compute composite from available metrics."""
        results = [r for r in [self.revenue, self.eps] if r is not None]
        if not results:
            return

        # Composite bucket: worst of the two (conservative)
        # If revenue is a big miss but EPS beats, the miss matters more
        bucket_severity = {
            SurpriseBucket.BIG_MISS: 0,
            SurpriseBucket.SMALL_MISS: 1,
            SurpriseBucket.INLINE: 2,
            SurpriseBucket.SMALL_BEAT: 3,
            SurpriseBucket.BIG_BEAT: 4,
        }
        # Revenue miss + EPS beat = use revenue (revenue miss is more damning)
        # Revenue beat + EPS miss = use EPS (earnings quality matters)
        # Both miss = use the worse one
        # Both beat = use the weaker beat (conservative)
        worst = min(results, key=lambda r: bucket_severity.get(r.bucket, 2))
        self.composite_bucket = worst.bucket
        self.composite_direction = BUCKET_DIRECTION[worst.bucket]
        self.composite_strength = worst.strength

    def to_prompt_context(self) -> str:
        """Format as context for the LLM extraction prompt."""
        lines = [f"CONSENSUS ESTIMATES for {self.ticker}"]
        if self.fiscal_period:
            lines[0] += f" ({self.fiscal_period})"
        lines.append("-" * 50)

        if self.revenue:
            r = self.revenue
            est_label = f"${r.estimate / 1e9:.2f}B" if r.estimate > 1e6 else f"${r.estimate:,.0f}"
            act_label = f"${r.actual / 1e9:.2f}B" if r.actual > 1e6 else f"${r.actual:,.0f}"
            analysts = f" ({r.num_analysts} analysts)" if r.num_analysts else ""
            lines.append(f"Revenue estimate: {est_label}{analysts}")
            lines.append(f"Revenue actual:   {act_label}")
            lines.append(f"Revenue surprise: {r.surprise_pct:+.1f}% -> {r.bucket.upper().replace('_', ' ')}")

        if self.eps:
            e = self.eps
            analysts = f" ({e.num_analysts} analysts)" if e.num_analysts else ""
            lines.append(f"EPS estimate: ${e.estimate:.2f}{analysts}")
            lines.append(f"EPS actual:   ${e.actual:.2f}")
            lines.append(f"EPS surprise: {e.surprise_pct:+.1f}% -> {e.bucket.upper().replace('_', ' ')}")

        if self.composite_bucket:
            lines.append(f"Overall: {self.composite_bucket.upper().replace('_', ' ')}")

        lines.append("")
        lines.append("IMPORTANT: Use these estimates to judge direction.")
        lines.append("A result ABOVE estimate = positive, BELOW estimate = negative,")
        lines.append("even if the absolute number grew year-over-year.")
        return "\n".join(lines)


def compute_surprise_pct(actual: float, estimate: float) -> float:
    """Compute surprise as percentage: (actual - estimate) / |estimate| * 100."""
    if estimate == 0:
        return 0.0
    return (actual - estimate) / abs(estimate) * 100.0


def classify_bucket(
    surprise_pct: float,
    big_miss_threshold: float,
    small_miss_threshold: float,
    small_beat_threshold: float,
    big_beat_threshold: float,
) -> str:
    """Map surprise % to a bucket."""
    if surprise_pct <= big_miss_threshold:
        return SurpriseBucket.BIG_MISS
    if surprise_pct <= small_miss_threshold:
        return SurpriseBucket.SMALL_MISS
    if surprise_pct < small_beat_threshold:
        return SurpriseBucket.INLINE
    if surprise_pct < big_beat_threshold:
        return SurpriseBucket.SMALL_BEAT
    return SurpriseBucket.BIG_BEAT


def compute_revenue_surprise(
    actual: float,
    estimate: float,
    thresholds: SurpriseThresholds = DEFAULT_THRESHOLDS,
    num_analysts: Optional[int] = None,
) -> SurpriseResult:
    """Compute revenue surprise result."""
    pct = compute_surprise_pct(actual, estimate)
    bucket = classify_bucket(
        pct,
        thresholds.revenue_big_miss,
        thresholds.revenue_small_miss,
        thresholds.revenue_small_beat,
        thresholds.revenue_big_beat,
    )
    return SurpriseResult(
        metric="revenue",
        actual=actual,
        estimate=estimate,
        surprise_pct=round(pct, 2),
        bucket=bucket,
        direction=BUCKET_DIRECTION[bucket],
        strength=BUCKET_STRENGTH[bucket],
        num_analysts=num_analysts,
    )


def compute_eps_surprise(
    actual: float,
    estimate: float,
    thresholds: SurpriseThresholds = DEFAULT_THRESHOLDS,
    num_analysts: Optional[int] = None,
) -> SurpriseResult:
    """Compute EPS surprise result."""
    pct = compute_surprise_pct(actual, estimate)
    bucket = classify_bucket(
        pct,
        thresholds.eps_big_miss,
        thresholds.eps_small_miss,
        thresholds.eps_small_beat,
        thresholds.eps_big_beat,
    )
    return SurpriseResult(
        metric="eps",
        actual=actual,
        estimate=estimate,
        surprise_pct=round(pct, 2),
        bucket=bucket,
        direction=BUCKET_DIRECTION[bucket],
        strength=BUCKET_STRENGTH[bucket],
        num_analysts=num_analysts,
    )


def compute_earnings_surprise(
    ticker: str,
    *,
    actual_revenue: Optional[float] = None,
    estimated_revenue: Optional[float] = None,
    actual_eps: Optional[float] = None,
    estimated_eps: Optional[float] = None,
    num_analysts: Optional[int] = None,
    fiscal_period: Optional[str] = None,
    thresholds: SurpriseThresholds = DEFAULT_THRESHOLDS,
) -> Optional[EarningsSurprise]:
    """Compute full earnings surprise from actuals and estimates.

    Returns None if no estimates are available to compare against.
    """
    rev_result = None
    eps_result = None

    if actual_revenue is not None and estimated_revenue is not None and estimated_revenue != 0:
        rev_result = compute_revenue_surprise(
            actual_revenue, estimated_revenue, thresholds, num_analysts,
        )

    if actual_eps is not None and estimated_eps is not None and estimated_eps != 0:
        eps_result = compute_eps_surprise(
            actual_eps, estimated_eps, thresholds, num_analysts,
        )

    if rev_result is None and eps_result is None:
        return None

    return EarningsSurprise(
        ticker=ticker,
        fiscal_period=fiscal_period,
        revenue=rev_result,
        eps=eps_result,
    )


# ---------------------------------------------------------------------------
# DB lookup: find estimates for a ticker near an earnings date
# ---------------------------------------------------------------------------

def lookup_estimates(session, ticker: str, earnings_date) -> Optional[EarningsSurprise]:
    """Look up stored estimates for a ticker around an earnings date.

    Searches for the closest estimate row within 90 days of the earnings date.
    Returns an EarningsSurprise if estimates exist, None otherwise.
    """
    from datetime import timedelta
    from sqlalchemy import select
    from models import EarningsEstimate

    window_start = earnings_date - timedelta(days=90)
    window_end = earnings_date + timedelta(days=7)

    estimate = session.scalars(
        select(EarningsEstimate)
        .where(
            EarningsEstimate.ticker == ticker,
            EarningsEstimate.fiscal_date >= window_start,
            EarningsEstimate.fiscal_date <= window_end,
        )
        .order_by(EarningsEstimate.fiscal_date.desc())
        .limit(1)
    ).first()

    if not estimate:
        return None

    return compute_earnings_surprise(
        ticker,
        actual_revenue=estimate.actual_revenue,
        estimated_revenue=estimate.estimated_revenue,
        actual_eps=estimate.actual_eps,
        estimated_eps=estimate.estimated_eps,
        num_analysts=estimate.num_analysts,
        fiscal_period=estimate.fiscal_period,
    )
