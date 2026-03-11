"""V1 valuation zone policy — deterministic zone classification from thesis + price context.

This is a placeholder until richer valuation modeling exists.
Uses thesis.valuation_gap_pct and position zone thresholds when available,
otherwise falls back to simple percentage-based zones.

Zone definitions:
  BUY:       price offers meaningful upside (valuation_gap_pct > buy_threshold)
  HOLD:      price is near fair value
  TRIM:      price is stretched above fair value
  FULL_EXIT: price far above fair value or thesis broken
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from models import ZoneState


# ---------------------------------------------------------------------------
# V1 thresholds (percentage-based, configurable)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ZoneThresholds:
    """Valuation gap thresholds for zone classification.

    valuation_gap_pct is defined as: (fair_value - current_price) / current_price * 100
    Positive = undervalued, Negative = overvalued.
    """
    buy_floor: float = 10.0       # gap >= 10% → BUY zone
    hold_floor: float = -5.0      # gap >= -5% → HOLD zone
    trim_floor: float = -20.0     # gap >= -20% → TRIM zone
    # Below trim_floor → FULL_EXIT zone


DEFAULT_THRESHOLDS = ZoneThresholds()


# ---------------------------------------------------------------------------
# Zone classification
# ---------------------------------------------------------------------------

def classify_zone(
    valuation_gap_pct: Optional[float],
    thresholds: ZoneThresholds = DEFAULT_THRESHOLDS,
) -> ZoneState:
    """Classify valuation zone from gap percentage.

    Args:
        valuation_gap_pct: (fair_value - price) / price * 100. Positive = cheap.
            If None, defaults to HOLD (insufficient data).
        thresholds: Zone boundary thresholds.

    Returns:
        ZoneState enum value.
    """
    if valuation_gap_pct is None:
        return ZoneState.HOLD

    if valuation_gap_pct >= thresholds.buy_floor:
        return ZoneState.BUY
    elif valuation_gap_pct >= thresholds.hold_floor:
        return ZoneState.HOLD
    elif valuation_gap_pct >= thresholds.trim_floor:
        return ZoneState.TRIM
    else:
        return ZoneState.FULL_EXIT


def compute_valuation_gap(
    current_price: Optional[float],
    fair_value_estimate: Optional[float],
) -> Optional[float]:
    """Compute valuation gap percentage.

    Returns None if either input is missing or invalid.
    """
    if not current_price or not fair_value_estimate or current_price <= 0:
        return None
    return ((fair_value_estimate - current_price) / current_price) * 100.0


def estimate_fair_value_from_thesis(
    base_case_rerating: Optional[float],
    current_price: Optional[float],
) -> Optional[float]:
    """V1 placeholder: estimate fair value from thesis base_case_rerating.

    base_case_rerating is a multiplier (e.g. 1.3 = 30% upside).
    If not set, returns None (no fair value estimate available).
    """
    if base_case_rerating is None or current_price is None or current_price <= 0:
        return None
    return current_price * base_case_rerating


def zone_from_thesis_and_price(
    valuation_gap_pct: Optional[float],
    base_case_rerating: Optional[float],
    current_price: Optional[float],
    thresholds: ZoneThresholds = DEFAULT_THRESHOLDS,
) -> ZoneState:
    """Determine zone using best available valuation data.

    Priority:
    1. Use thesis.valuation_gap_pct if available (already computed externally)
    2. Derive gap from base_case_rerating + current_price
    3. Default to HOLD if no valuation data
    """
    if valuation_gap_pct is not None:
        return classify_zone(valuation_gap_pct, thresholds)

    if base_case_rerating is not None and current_price is not None and current_price > 0:
        fair_value = estimate_fair_value_from_thesis(base_case_rerating, current_price)
        gap = compute_valuation_gap(current_price, fair_value)
        return classify_zone(gap, thresholds)

    return ZoneState.HOLD
