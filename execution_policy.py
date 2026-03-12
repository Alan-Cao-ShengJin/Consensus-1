"""Execution policy: deterministic sizing rules for recommendation-to-trade mapping.

Defines how each action type translates into a target weight change.
All sizing is explicit — no hidden heuristics.

This module is used by the execution wrapper to compute notional deltas
and by the paper execution engine to determine fill quantities.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from models import ActionType

logger = logging.getLogger(__name__)


@dataclass
class ExecutionPolicyConfig:
    """Configuration for execution sizing rules.

    All weights are in percentage points of portfolio value.
    """
    # Initiation sizing
    default_initiation_weight_pct: float = 3.0   # starter position size
    min_initiation_weight_pct: float = 2.0        # floor
    max_initiation_weight_pct: float = 5.0        # ceiling

    # Add sizing
    default_add_increment_pct: float = 1.5        # weight added per ADD

    # Trim sizing
    default_trim_decrement_pct: float = 2.0       # weight removed per TRIM
    trim_floor_weight_pct: float = 1.0            # never trim below this

    # Exit
    # EXIT always targets 0.0 weight — no configurable sizing

    # Position limits
    max_single_position_weight_pct: float = 10.0  # hard cap per position
    max_gross_exposure_pct: float = 100.0          # total invested cannot exceed this

    # Turnover
    max_weekly_turnover_pct: float = 20.0          # max % of portfolio that can turn over

    # Transaction cost
    transaction_cost_bps: float = 10.0             # default cost in basis points


DEFAULT_POLICY = ExecutionPolicyConfig()


def compute_target_weight(
    action: ActionType,
    current_weight: float,
    decision_suggested_weight: Optional[float],
    decision_weight_change: Optional[float],
    config: ExecutionPolicyConfig = DEFAULT_POLICY,
) -> float:
    """Compute the target weight after executing an action.

    Priority:
    1. If the decision engine provided a suggested_weight, use it (clamped).
    2. If the decision engine provided a target_weight_change, apply it.
    3. Otherwise, use policy defaults.
    """
    if action == ActionType.EXIT:
        return 0.0

    if action in (ActionType.HOLD, ActionType.PROBATION, ActionType.NO_ACTION):
        return current_weight  # no change

    if action == ActionType.INITIATE:
        if decision_suggested_weight is not None:
            target = decision_suggested_weight
        elif decision_weight_change is not None:
            target = decision_weight_change  # for initiation, weight_change IS the target
        else:
            target = config.default_initiation_weight_pct
        # Clamp to policy bounds
        target = max(config.min_initiation_weight_pct, min(target, config.max_initiation_weight_pct))
        # Also respect max position weight
        target = min(target, config.max_single_position_weight_pct)
        return target

    if action == ActionType.ADD:
        if decision_suggested_weight is not None:
            target = decision_suggested_weight
        elif decision_weight_change is not None:
            target = current_weight + decision_weight_change
        else:
            target = current_weight + config.default_add_increment_pct
        # Clamp to max position weight
        target = min(target, config.max_single_position_weight_pct)
        return target

    if action == ActionType.TRIM:
        if decision_suggested_weight is not None:
            target = decision_suggested_weight
        elif decision_weight_change is not None:
            target = current_weight + decision_weight_change  # change is negative
        else:
            target = current_weight - config.default_trim_decrement_pct
        # Never trim below floor
        target = max(target, config.trim_floor_weight_pct)
        # Never go negative
        target = max(target, 0.0)
        return target

    return current_weight


def compute_notional_delta(
    current_weight: float,
    target_weight: float,
    portfolio_value: float,
) -> float:
    """Compute the dollar amount to trade. Positive = buy, negative = sell."""
    return (target_weight - current_weight) / 100.0 * portfolio_value


def compute_estimated_shares(
    notional_delta: float,
    reference_price: Optional[float],
) -> Optional[float]:
    """Estimate share count from notional delta and price.

    Returns signed shares: positive = buy, negative = sell.
    Returns None if no price available.
    """
    if reference_price is None or reference_price <= 0:
        return None
    return notional_delta / reference_price


def compute_transaction_cost(
    notional: float,
    cost_bps: float = 10.0,
) -> float:
    """Compute transaction cost from notional amount and cost in basis points."""
    return abs(notional) * (cost_bps / 10_000.0)


def validate_funded_pairing(
    buy_ticker: str,
    buy_notional: float,
    sell_ticker: Optional[str],
    sell_notional: float,
) -> tuple[bool, str]:
    """Check that a funded pairing is logically coherent.

    The sell must free enough capital to (approximately) cover the buy.
    We allow a 20% tolerance since execution prices may drift.
    """
    if sell_ticker is None:
        return True, "no funded pairing"

    freed_capital = abs(sell_notional)
    needed_capital = abs(buy_notional)

    if freed_capital <= 0:
        return False, f"funded sell of {sell_ticker} frees no capital"

    ratio = needed_capital / freed_capital
    if ratio > 1.2:
        return False, (
            f"funded pairing imbalanced: need ${needed_capital:,.0f} "
            f"but {sell_ticker} only frees ${freed_capital:,.0f} (ratio={ratio:.2f})"
        )

    return True, "funded pairing coherent"
