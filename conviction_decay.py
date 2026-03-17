"""Conviction decay engine: erode stale convictions to fix the one-way ratchet.

Problem: 81% of extracted claims are positive (company-reported sources).
Conviction scores ratchet up to 80+ and stay there even as stocks crash,
because there is no mechanism to reduce conviction without negative evidence.

Solution: Time-based decay that erodes conviction when no fresh confirming
evidence has arrived. This forces the system to require ongoing justification
for high-conviction positions rather than coasting on stale bullish claims.

Rules:
  1. Decay only applies when no NEW or CONFIRMING claims have arrived in
     the lookback window (default 14 days).
  2. Decay rate scales with conviction level: higher conviction decays faster
     (a 90-score position needs stronger ongoing evidence than a 50-score).
  3. Decay is capped per review cycle to prevent cliff-edge drops.
  4. Below a floor score (35), decay stops — the position is already on
     the trim/exit path and decay would be redundant.
  5. Price divergence amplifies decay: if price has fallen >10% while
     conviction is high, decay accelerates (thesis may be wrong).

All functions are pure: no DB access, no side effects.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional


@dataclass(frozen=True)
class ConvictionDecayConfig:
    """Configuration for conviction decay."""
    enabled: bool = True

    # How many days without fresh evidence before decay kicks in
    staleness_window_days: int = 14

    # Base decay rate per review cycle (points)
    base_decay_rate: float = 2.0

    # Decay scales up for high-conviction positions
    # At conviction=50: 1.0x base rate
    # At conviction=80: 1.6x base rate
    # At conviction=95: 2.0x base rate
    high_conviction_multiplier: float = 2.0

    # Max decay per review cycle (prevents cliff-edge drops)
    max_decay_per_cycle: float = 5.0

    # Floor: stop decaying below this score (aligned with trim threshold)
    decay_floor: float = 35.0

    # Price divergence amplifier: if price is down >X% while conviction
    # is above the divergence threshold, decay is amplified
    price_divergence_threshold_pct: float = -10.0
    price_divergence_conviction_floor: float = 60.0
    price_divergence_amplifier: float = 1.5


DISABLED_DECAY_CONFIG = ConvictionDecayConfig(enabled=False)
DEFAULT_DECAY_CONFIG = ConvictionDecayConfig(enabled=True)


def compute_conviction_decay(
    current_score: float,
    days_since_last_evidence: Optional[int],
    price_change_pct: Optional[float],
    config: ConvictionDecayConfig = DEFAULT_DECAY_CONFIG,
) -> float:
    """Compute how much conviction should decay this review cycle.

    Args:
        current_score: Current conviction score (0-100).
        days_since_last_evidence: Days since the most recent NEW or CONFIRMING
            claim. None means no evidence has ever been recorded.
        price_change_pct: Recent price change percentage (e.g., -15.0 for a 15% drop).
            None if unavailable.
        config: Decay configuration.

    Returns:
        Decay amount (always >= 0). Caller should subtract this from score.
    """
    if not config.enabled:
        return 0.0

    # Below floor: no decay needed
    if current_score <= config.decay_floor:
        return 0.0

    # If fresh evidence exists within window, no decay
    if days_since_last_evidence is not None and days_since_last_evidence <= config.staleness_window_days:
        return 0.0

    # Base decay
    decay = config.base_decay_rate

    # Scale by conviction level: higher conviction = faster decay
    # Linear interpolation from 1.0x at score=50 to high_conviction_multiplier at score=100
    conviction_factor = 1.0
    if current_score > 50:
        conviction_factor = 1.0 + (config.high_conviction_multiplier - 1.0) * (
            (current_score - 50) / 50.0
        )
    decay *= conviction_factor

    # Price divergence amplifier: stock is falling but conviction is high
    if (
        price_change_pct is not None
        and price_change_pct < config.price_divergence_threshold_pct
        and current_score > config.price_divergence_conviction_floor
    ):
        decay *= config.price_divergence_amplifier

    # Cap decay per cycle
    decay = min(decay, config.max_decay_per_cycle)

    # Don't decay below floor
    max_decay = current_score - config.decay_floor
    decay = min(decay, max_decay)

    return round(max(0.0, decay), 2)


def apply_conviction_decay(
    current_score: float,
    days_since_last_evidence: Optional[int],
    price_change_pct: Optional[float],
    config: ConvictionDecayConfig = DEFAULT_DECAY_CONFIG,
) -> tuple[float, float]:
    """Apply conviction decay and return (new_score, decay_amount).

    Pure function: takes current state, returns new state.
    """
    decay = compute_conviction_decay(
        current_score, days_since_last_evidence, price_change_pct, config,
    )
    new_score = round(current_score - decay, 2)
    return new_score, decay
