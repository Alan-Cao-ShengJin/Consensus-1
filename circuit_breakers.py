"""Circuit breakers: automatic safety limits for live trading.

Each breaker returns (tripped: bool, message: str).
When tripped, the live execution engine should activate the kill switch.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class CircuitBreakerConfig:
    """Configuration for all circuit breakers."""
    max_drawdown_pct: float = 15.0       # Max portfolio drawdown from high-water mark
    daily_loss_limit_pct: float = 3.0    # Max single-day loss as % of portfolio
    max_position_weight_pct: float = 12.0  # Block buys for over-concentrated positions
    enabled: bool = True


DEFAULT_BREAKER_CONFIG = CircuitBreakerConfig()


def check_max_drawdown(
    current_equity: float,
    high_water_mark: float,
    threshold_pct: float = 15.0,
) -> tuple[bool, str]:
    """Trip if portfolio drawdown from high-water mark exceeds threshold.

    Args:
        current_equity: Current portfolio value
        high_water_mark: Highest portfolio value observed
        threshold_pct: Max allowed drawdown percentage

    Returns:
        (tripped, message)
    """
    if high_water_mark <= 0:
        return False, "high_water_mark not set"

    drawdown_pct = ((high_water_mark - current_equity) / high_water_mark) * 100.0

    if drawdown_pct >= threshold_pct:
        msg = (f"MAX DRAWDOWN BREAKER: portfolio down {drawdown_pct:.1f}% "
               f"from high of ${high_water_mark:,.0f} "
               f"(current: ${current_equity:,.0f}, limit: {threshold_pct:.0f}%)")
        logger.critical(msg)
        return True, msg

    return False, f"drawdown {drawdown_pct:.1f}% within limit ({threshold_pct:.0f}%)"


def check_daily_loss(
    today_pnl: float,
    portfolio_value: float,
    threshold_pct: float = 3.0,
) -> tuple[bool, str]:
    """Trip if today's combined P&L loss exceeds threshold.

    Args:
        today_pnl: Today's realized + unrealized P&L (negative = loss)
        portfolio_value: Portfolio value at start of day
        threshold_pct: Max allowed daily loss percentage

    Returns:
        (tripped, message)
    """
    if portfolio_value <= 0:
        return False, "portfolio_value not set"

    loss_pct = abs(today_pnl / portfolio_value) * 100.0 if today_pnl < 0 else 0.0

    if today_pnl < 0 and loss_pct >= threshold_pct:
        msg = (f"DAILY LOSS BREAKER: lost ${abs(today_pnl):,.0f} today "
               f"({loss_pct:.1f}% of ${portfolio_value:,.0f}, limit: {threshold_pct:.0f}%)")
        logger.critical(msg)
        return True, msg

    return False, f"daily P&L ${today_pnl:+,.0f} within limit ({threshold_pct:.0f}%)"


def check_concentration(
    positions: list[dict],
    max_weight_pct: float = 12.0,
) -> tuple[bool, list[str]]:
    """Check if any position exceeds concentration limit.

    Args:
        positions: List of dicts with 'ticker' and 'weight_pct' keys
        max_weight_pct: Maximum allowed position weight

    Returns:
        (any_over_limit, list of over-concentrated tickers)
    """
    over_limit = []
    for pos in positions:
        ticker = pos.get("ticker", "?")
        weight = pos.get("weight_pct", 0.0)
        if weight > max_weight_pct:
            over_limit.append(ticker)
            logger.warning("CONCENTRATION: %s at %.1f%% exceeds %.0f%% limit",
                           ticker, weight, max_weight_pct)

    return len(over_limit) > 0, over_limit


def run_all_checks(
    current_equity: float,
    high_water_mark: float,
    today_pnl: float,
    portfolio_value_sod: float,
    positions: Optional[list[dict]] = None,
    config: Optional[CircuitBreakerConfig] = None,
) -> tuple[bool, list[str]]:
    """Run all circuit breakers. Returns (any_tripped, list of messages).

    Args:
        current_equity: Current portfolio value
        high_water_mark: Highest observed portfolio value
        today_pnl: Today's realized + unrealized P&L
        portfolio_value_sod: Portfolio value at start of day
        positions: List of position dicts with ticker/weight_pct
        config: Circuit breaker configuration
    """
    if config is None:
        config = DEFAULT_BREAKER_CONFIG

    if not config.enabled:
        return False, ["circuit breakers disabled"]

    messages = []
    any_tripped = False

    # Drawdown check
    tripped, msg = check_max_drawdown(
        current_equity, high_water_mark, config.max_drawdown_pct)
    messages.append(msg)
    if tripped:
        any_tripped = True

    # Daily loss check
    tripped, msg = check_daily_loss(
        today_pnl, portfolio_value_sod, config.daily_loss_limit_pct)
    messages.append(msg)
    if tripped:
        any_tripped = True

    # Concentration check
    if positions:
        conc_tripped, over_limit = check_concentration(
            positions, config.max_position_weight_pct)
        if conc_tripped:
            any_tripped = True
            messages.append(f"CONCENTRATION: {', '.join(over_limit)} over limit")
        else:
            messages.append("concentration within limits")

    return any_tripped, messages
