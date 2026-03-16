"""Price momentum guards: pure functions for trend/drawdown/regime checks.

These guards add price-awareness to the fundamentals-driven decision engine.
All functions are pure (no DB access, no side effects) and operate on
preloaded price series.

Features:
  1. SMA guard: block ADDs when price is below N-day SMA
  2. Stop-loss: TRIM at -20%, EXIT at -35% from cost basis
  3. Trailing stop: EXIT at -25% from 90-day peak
  4. Underwater add blocking: no ADDs when position is >20% underwater
  5. Market regime filter: block INITIATEs when benchmark below 50-day SMA
  6. Overbought guard: block ADDs/INITIATEs when price within 5% of 90-day high

All thresholds are configurable via MomentumGuardConfig.
Guards are disabled by default (enabled=False) for backward compatibility.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional


@dataclass(frozen=True)
class MomentumGuardConfig:
    """Configuration for all momentum guards.

    enabled=False means all guards are bypassed (backward compatible).
    """
    enabled: bool = False

    # SMA guard: block ADDs when price < SMA
    sma_period: int = 20
    sma_guard_enabled: bool = True

    # Stop-loss from cost basis (widened to avoid premature exits)
    stop_loss_trim_pct: float = -20.0    # TRIM threshold (% from cost)
    stop_loss_exit_pct: float = -35.0    # EXIT threshold (% from cost)
    stop_loss_enabled: bool = True

    # Trailing stop from N-day peak (widened to avoid selling at bottoms)
    trailing_stop_pct: float = -30.0     # EXIT threshold (% from peak) — widened for volatile tech
    trailing_stop_lookback: int = 90     # days to look back for peak
    trailing_stop_enabled: bool = True

    # Underwater add blocking
    underwater_block_pct: float = -20.0  # block ADDs below this drawdown
    underwater_add_scale: float = 0.5    # scale ADD size when underwater
    underwater_guard_enabled: bool = True

    # Market regime filter (benchmark SMA)
    regime_sma_period: int = 50
    regime_guard_enabled: bool = True

    # Overbought guard: block ADDs/INITIATEs near recent highs
    overbought_guard_enabled: bool = True
    overbought_threshold_pct: float = 5.0   # within X% of N-day high = overbought
    overbought_lookback: int = 90            # days to look back for high


# Pre-built configs
DISABLED_MOMENTUM_CONFIG = MomentumGuardConfig(enabled=False)

ENABLED_MOMENTUM_CONFIG = MomentumGuardConfig(
    enabled=True,
    sma_period=20,
    stop_loss_trim_pct=-20.0,
    stop_loss_exit_pct=-35.0,
    trailing_stop_pct=-30.0,
    trailing_stop_lookback=90,
    underwater_block_pct=-20.0,
    underwater_add_scale=0.5,
    regime_sma_period=50,
    overbought_guard_enabled=True,
    overbought_threshold_pct=5.0,
    overbought_lookback=90,
)


# ---------------------------------------------------------------------------
# Pure computation functions
# ---------------------------------------------------------------------------

def compute_sma(
    prices: list[tuple[date, float]],
    as_of: date,
    period: int,
) -> Optional[float]:
    """Compute simple moving average of closing prices ending on or before as_of.

    Args:
        prices: Sorted ascending list of (date, close_price).
        as_of: Only use prices on or before this date.
        period: Number of data points to average.

    Returns:
        SMA value, or None if insufficient data.
    """
    relevant = [p for d, p in prices if d <= as_of]
    if len(relevant) < period:
        return None
    return sum(relevant[-period:]) / period


def is_above_sma(
    prices: list[tuple[date, float]],
    as_of: date,
    period: int,
) -> Optional[bool]:
    """Check if the latest price is above the N-day SMA.

    Returns None if insufficient data.
    """
    sma = compute_sma(prices, as_of, period)
    if sma is None:
        return None
    relevant = [p for d, p in prices if d <= as_of]
    if not relevant:
        return None
    return relevant[-1] > sma


def compute_drawdown_from_cost(
    current_price: Optional[float],
    avg_cost: float,
) -> Optional[float]:
    """Compute drawdown percentage from cost basis.

    Returns negative value when underwater (e.g., -15.0 means 15% below cost).
    Returns positive when above cost.
    Returns None if inputs are invalid.
    """
    if current_price is None or avg_cost <= 0:
        return None
    return ((current_price - avg_cost) / avg_cost) * 100.0


def compute_drawdown_from_peak(
    prices: list[tuple[date, float]],
    as_of: date,
    lookback_days: int,
) -> Optional[float]:
    """Compute drawdown from peak price within lookback window.

    Returns negative value (e.g., -20.0 means 20% below peak).
    Returns 0.0 if current price IS the peak.
    Returns None if insufficient data.
    """
    from datetime import timedelta
    cutoff = as_of - timedelta(days=lookback_days)
    window_prices = [p for d, p in prices if cutoff <= d <= as_of]
    if not window_prices:
        return None
    peak = max(window_prices)
    current = window_prices[-1]
    if peak <= 0:
        return None
    return ((current - peak) / peak) * 100.0


def compute_distance_from_high(
    prices: list[tuple[date, float]],
    as_of: date,
    lookback_days: int,
) -> Optional[float]:
    """Compute how close current price is to the N-day high.

    Returns a percentage: 0.0 means at the high, -10.0 means 10% below high.
    Used to detect overbought conditions (close to high = risky entry).
    """
    from datetime import timedelta
    cutoff = as_of - timedelta(days=lookback_days)
    window_prices = [p for d, p in prices if cutoff <= d <= as_of]
    if not window_prices:
        return None
    high = max(window_prices)
    current = window_prices[-1]
    if high <= 0:
        return None
    return ((current - high) / high) * 100.0


def compute_market_regime(
    benchmark_prices: list[tuple[date, float]],
    as_of: date,
    sma_period: int,
) -> Optional[bool]:
    """Determine if market is in bullish regime.

    Returns True if benchmark is above its SMA (bullish).
    Returns False if below (bearish).
    Returns None if insufficient data.
    """
    return is_above_sma(benchmark_prices, as_of, sma_period)


# ---------------------------------------------------------------------------
# Aggregated momentum signals
# ---------------------------------------------------------------------------

@dataclass
class MomentumSignals:
    """Computed momentum signals for a single holding or candidate.

    Populated by the review service / replay engine, consumed by the
    decision engine.
    """
    # SMA
    price_above_sma: Optional[bool] = None
    sma_value: Optional[float] = None

    # Cost-basis drawdown
    drawdown_from_cost_pct: Optional[float] = None

    # Peak drawdown
    drawdown_from_peak_pct: Optional[float] = None
    peak_price: Optional[float] = None

    # Market regime (set at portfolio level, copied to each snapshot)
    market_regime_bullish: Optional[bool] = None

    # Overbought detection
    distance_from_high_pct: Optional[float] = None
    is_overbought: Optional[bool] = None


def compute_holding_signals(
    prices: list[tuple[date, float]],
    as_of: date,
    current_price: Optional[float],
    avg_cost: float,
    config: MomentumGuardConfig,
) -> MomentumSignals:
    """Compute all momentum signals for a holding.

    Pure function: takes price series + config, returns signals.
    """
    signals = MomentumSignals()

    if not config.enabled:
        return signals

    # SMA
    if config.sma_guard_enabled:
        signals.sma_value = compute_sma(prices, as_of, config.sma_period)
        signals.price_above_sma = is_above_sma(prices, as_of, config.sma_period)

    # Cost-basis drawdown
    if config.stop_loss_enabled or config.underwater_guard_enabled:
        signals.drawdown_from_cost_pct = compute_drawdown_from_cost(current_price, avg_cost)

    # Peak drawdown
    if config.trailing_stop_enabled:
        signals.drawdown_from_peak_pct = compute_drawdown_from_peak(
            prices, as_of, config.trailing_stop_lookback,
        )
        # Also store peak for audit trail
        from datetime import timedelta
        cutoff = as_of - timedelta(days=config.trailing_stop_lookback)
        window_prices = [p for d, p in prices if cutoff <= d <= as_of]
        signals.peak_price = max(window_prices) if window_prices else None

    # Overbought detection
    if config.overbought_guard_enabled:
        dist = compute_distance_from_high(prices, as_of, config.overbought_lookback)
        signals.distance_from_high_pct = dist
        if dist is not None:
            signals.is_overbought = dist >= -config.overbought_threshold_pct

    return signals


def compute_candidate_signals(
    prices: list[tuple[date, float]],
    as_of: date,
    config: MomentumGuardConfig,
) -> MomentumSignals:
    """Compute momentum signals for a candidate (no cost basis).

    Only SMA and market regime are relevant for candidates.
    """
    signals = MomentumSignals()

    if not config.enabled:
        return signals

    if config.sma_guard_enabled:
        signals.sma_value = compute_sma(prices, as_of, config.sma_period)
        signals.price_above_sma = is_above_sma(prices, as_of, config.sma_period)

    # Overbought detection for candidates
    if config.overbought_guard_enabled:
        dist = compute_distance_from_high(prices, as_of, config.overbought_lookback)
        signals.distance_from_high_pct = dist
        if dist is not None:
            signals.is_overbought = dist >= -config.overbought_threshold_pct

    return signals
