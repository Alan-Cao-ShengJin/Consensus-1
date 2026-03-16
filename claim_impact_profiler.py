"""Claim impact profiler: measures realized market impact of claims.

Inspired by FinMem's event-outcome feedback loop. Instead of treating all
claims equally (just counting them), we measure what actually happened to
the stock price after each claim type, then use those profiles to weight
future claim signals.

Core idea:
  1. For each historical claim, measure forward 5d/20d returns
  2. Group by (claim_type, direction) → average forward returns
  3. When evaluating new claims, weight by historical predictiveness

Anti-leakage: profiles are only built from outcomes where the forward
window has fully elapsed relative to the as-of date.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# Trading days for forward return windows
FORWARD_5D_TRADING_DAYS = 5
FORWARD_20D_TRADING_DAYS = 20

# Minimum samples to consider a profile reliable
MIN_PROFILE_SAMPLES = 3

# Novelty weights for signal computation
NOVELTY_WEIGHTS = {
    "NEW": 1.0,
    "CONFIRMING": 0.5,
    "CONFLICTING": 0.25,
    "REPETITIVE": 0.0,
}


@dataclass
class ClaimImpactProfile:
    """Aggregated forward-return profile for a (claim_type, direction) bucket."""
    claim_type: str
    direction: str
    sample_count: int = 0
    avg_forward_5d_pct: float = 0.0
    avg_forward_20d_pct: float = 0.0
    hit_rate: float = 0.0  # % of claims where direction matched actual move


@dataclass
class ClaimOutcomeRecord:
    """Single claim's realized outcome (computed in-memory, not persisted during replay)."""
    claim_type: str
    direction: str
    novelty_type: str
    strength: float
    published_date: date
    ticker: str
    price_at_claim: float
    forward_5d_pct: Optional[float] = None
    forward_20d_pct: Optional[float] = None


def _find_price_on_date(
    prices: list[tuple[date, float]],
    target_date: date,
) -> Optional[float]:
    """Find the closest price on or before target_date."""
    best = None
    for d, p in prices:
        if d <= target_date:
            best = p
        else:
            break
    return best


def _find_forward_price(
    prices: list[tuple[date, float]],
    base_date: date,
    trading_days_forward: int,
) -> Optional[tuple[date, float]]:
    """Find the price N trading days after base_date.

    Returns (date, price) or None if insufficient data.
    """
    count = 0
    for d, p in prices:
        if d <= base_date:
            continue
        count += 1
        if count == trading_days_forward:
            return (d, p)
    return None


def compute_outcomes_from_prices(
    claims_with_meta: list[dict],
    prices_by_ticker: dict[str, list[tuple[date, float]]],
    as_of: date,
) -> list[ClaimOutcomeRecord]:
    """Compute forward returns for claims using preloaded price data.

    Args:
        claims_with_meta: List of dicts with keys:
            ticker, claim_type, direction, novelty_type, strength, published_date
        prices_by_ticker: Preloaded {ticker: [(date, close), ...]} sorted by date
        as_of: Only include outcomes where forward window is fully elapsed

    Returns:
        List of ClaimOutcomeRecord with forward returns filled in.
    """
    outcomes = []

    for cm in claims_with_meta:
        ticker = cm["ticker"]
        pub_date = cm["published_date"]
        prices = prices_by_ticker.get(ticker, [])
        if not prices:
            continue

        # Find price at claim publication
        price_at = _find_price_on_date(prices, pub_date)
        if price_at is None or price_at <= 0:
            continue

        record = ClaimOutcomeRecord(
            claim_type=cm["claim_type"],
            direction=cm["direction"],
            novelty_type=cm.get("novelty_type", "NEW"),
            strength=cm.get("strength", 0.5),
            published_date=pub_date,
            ticker=ticker,
            price_at_claim=price_at,
        )

        # 5-day forward
        fwd5 = _find_forward_price(prices, pub_date, FORWARD_5D_TRADING_DAYS)
        if fwd5 and fwd5[0] <= as_of:
            record.forward_5d_pct = ((fwd5[1] - price_at) / price_at) * 100.0

        # 20-day forward
        fwd20 = _find_forward_price(prices, pub_date, FORWARD_20D_TRADING_DAYS)
        if fwd20 and fwd20[0] <= as_of:
            record.forward_20d_pct = ((fwd20[1] - price_at) / price_at) * 100.0

        # Only include if at least one forward return is computable
        if record.forward_5d_pct is not None or record.forward_20d_pct is not None:
            outcomes.append(record)

    return outcomes


def build_impact_profiles(
    outcomes: list[ClaimOutcomeRecord],
) -> dict[tuple[str, str], ClaimImpactProfile]:
    """Build aggregated profiles from claim outcomes.

    Groups by (claim_type, direction) and computes average forward returns.
    Only returns profiles with >= MIN_PROFILE_SAMPLES.
    """
    groups: dict[tuple[str, str], list[ClaimOutcomeRecord]] = defaultdict(list)

    for o in outcomes:
        if o.forward_20d_pct is not None:
            key = (o.claim_type, o.direction)
            groups[key].append(o)

    profiles = {}
    for key, records in groups.items():
        if len(records) < MIN_PROFILE_SAMPLES:
            continue

        avg_5d = 0.0
        count_5d = 0
        avg_20d = 0.0
        hits = 0  # direction matched actual move

        for r in records:
            if r.forward_5d_pct is not None:
                avg_5d += r.forward_5d_pct
                count_5d += 1
            avg_20d += r.forward_20d_pct

            # Hit rate: did direction match?
            if r.direction == "POSITIVE" and r.forward_20d_pct > 0:
                hits += 1
            elif r.direction == "NEGATIVE" and r.forward_20d_pct < 0:
                hits += 1

        n = len(records)
        profiles[key] = ClaimImpactProfile(
            claim_type=key[0],
            direction=key[1],
            sample_count=n,
            avg_forward_5d_pct=avg_5d / count_5d if count_5d > 0 else 0.0,
            avg_forward_20d_pct=avg_20d / n,
            hit_rate=hits / n if n > 0 else 0.0,
        )

    return profiles


def get_claim_impact_score(
    profiles: dict[tuple[str, str], ClaimImpactProfile],
    claim_type: str,
    direction: str,
) -> float:
    """Look up historical average 20d forward return for a claim category.

    Returns 0.0 if no profile exists or insufficient samples.
    """
    profile = profiles.get((claim_type, direction))
    if profile is None:
        return 0.0
    return profile.avg_forward_20d_pct


def compute_weighted_claim_signal(
    recent_claims: list[dict],
    profiles: dict[tuple[str, str], ClaimImpactProfile],
) -> float:
    """Compute a weighted expected-impact signal from recent claims.

    Each claim is weighted by:
      impact_score (from profile) * strength * novelty_weight

    Args:
        recent_claims: List of dicts with keys:
            claim_type, direction, strength, novelty_type
        profiles: Output of build_impact_profiles()

    Returns:
        Weighted sum of expected impact (can be positive or negative).
        Normalized by count to prevent signal scaling with claim volume.
    """
    if not recent_claims:
        return 0.0

    total_signal = 0.0
    total_weight = 0.0

    for claim in recent_claims:
        ct = claim.get("claim_type", "")
        direction = claim.get("direction", "NEUTRAL")
        strength = claim.get("strength", 0.5) or 0.5
        novelty = claim.get("novelty_type", "NEW")

        impact_score = get_claim_impact_score(profiles, ct, direction)
        novelty_weight = NOVELTY_WEIGHTS.get(novelty, 0.5)

        w = strength * novelty_weight
        total_signal += impact_score * w
        total_weight += w

    if total_weight <= 0:
        return 0.0

    # Return weighted average, not sum — so it doesn't scale with claim count
    return total_signal / total_weight


def compute_profiles_for_replay(
    session,
    prices_by_ticker: dict[str, list[tuple[date, float]]],
    as_of: date,
) -> dict[tuple[str, str], ClaimImpactProfile]:
    """Build impact profiles from DB claims for a given replay date.

    Fetches all claims published before as_of, computes their forward
    returns using preloaded prices, and builds profiles. Only includes
    outcomes where the 20d forward window has fully elapsed.
    """
    from models import Claim, ClaimCompanyLink
    from sqlalchemy import select

    # Fetch claims with their linked tickers, published before the
    # profile window cutoff (as_of minus 20 trading days ≈ 30 calendar days)
    # to ensure forward returns are available
    cutoff = as_of  # outcomes will self-filter via forward date <= as_of

    stmt = (
        select(
            Claim.id,
            Claim.claim_type,
            Claim.direction,
            Claim.novelty_type,
            Claim.strength,
            Claim.published_at,
            ClaimCompanyLink.company_ticker,
        )
        .join(ClaimCompanyLink, Claim.id == ClaimCompanyLink.claim_id)
        .where(Claim.published_at.isnot(None))
        .where(Claim.published_at <= cutoff)
    )

    rows = session.execute(stmt).all()
    if not rows:
        return {}

    claims_with_meta = []
    for row in rows:
        pub_at = row.published_at
        if hasattr(pub_at, "date"):
            pub_date = pub_at.date()
        elif isinstance(pub_at, date):
            pub_date = pub_at
        else:
            continue

        ct = row.claim_type
        if hasattr(ct, "value"):
            ct = ct.value
        dr = row.direction
        if hasattr(dr, "value"):
            dr = dr.value
        nt = row.novelty_type
        if hasattr(nt, "value"):
            nt = nt.value

        claims_with_meta.append({
            "ticker": row.company_ticker,
            "claim_type": ct,
            "direction": dr,
            "novelty_type": nt,
            "strength": row.strength or 0.5,
            "published_date": pub_date,
        })

    outcomes = compute_outcomes_from_prices(claims_with_meta, prices_by_ticker, as_of)
    profiles = build_impact_profiles(outcomes)

    logger.info(
        "Claim impact profiles: %d outcomes from %d claims, %d profiles built (as_of=%s)",
        len(outcomes), len(claims_with_meta), len(profiles), as_of.isoformat(),
    )

    return profiles


def get_recent_claims_for_ticker(
    session,
    ticker: str,
    as_of: date,
    lookback_days: int = 7,
) -> list[dict]:
    """Fetch recent claims for a ticker within the lookback window.

    Returns list of dicts suitable for compute_weighted_claim_signal().
    """
    from models import Claim, ClaimCompanyLink
    from sqlalchemy import select
    from datetime import datetime

    window_start = datetime.combine(as_of - timedelta(days=lookback_days), datetime.min.time())
    window_end = datetime.combine(as_of, datetime.max.time())

    stmt = (
        select(
            Claim.claim_type,
            Claim.direction,
            Claim.strength,
            Claim.novelty_type,
        )
        .join(ClaimCompanyLink, Claim.id == ClaimCompanyLink.claim_id)
        .where(ClaimCompanyLink.company_ticker == ticker)
        .where(Claim.published_at >= window_start)
        .where(Claim.published_at <= window_end)
    )

    rows = session.execute(stmt).all()
    result = []
    for row in rows:
        ct = row.claim_type
        if hasattr(ct, "value"):
            ct = ct.value
        dr = row.direction
        if hasattr(dr, "value"):
            dr = dr.value
        nt = row.novelty_type
        if hasattr(nt, "value"):
            nt = nt.value

        result.append({
            "claim_type": ct,
            "direction": dr,
            "strength": row.strength or 0.5,
            "novelty_type": nt,
        })

    return result
