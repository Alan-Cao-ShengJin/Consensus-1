"""Portfolio allocation: conviction gates entry, valuation drives sizing.

Two independent signals:
1. Conviction score (LLM-driven) — gatekeeper for portfolio inclusion
2. NTM Forward P/E z-score — determines position size and profit-taking

GATEKEEPER (Conviction):
  > 60%   → eligible for full allocation
  40-60%  → if already held, trim to ≤1%; no new entry
  < 40%   → full exit

SIZING (Upside-driven, only buy when cheap):
  Raw weight = conviction_pct × upside_score
  Upside score from PE z-score:
    Very Cheap  (z < -1.5)  → 1.0
    Cheap       (z < -0.5)  → 0.7
    Fair Value  (-0.5 to 0.5) → 0.0
    Expensive   (z > 0.5)   → 0.0
    Very Expensive (z > 1.5) → 0.0

  Normalize across eligible tickers → target weight
  Position cap: 10% max per name

PROFIT TAKING (as PE reverts toward mean):
  Hit mean PE     → trim half the position
  Hit mean + 1 SD → trim another half (25% of original)
  Hit mean + 2 SD → full exit (regardless of conviction)

CASH: whatever is left after allocation — no forced minimum.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

logger = logging.getLogger(__name__)

# ── Conviction thresholds ──────────────────────────────────────────
CONVICTION_FULL_ELIGIBLE = 60     # above this: eligible for full allocation
CONVICTION_TRIM_ZONE = 40        # 40-60: trim to ≤1% if held, no new entry
CONVICTION_EXIT = 40             # below this: full exit

# ── Position limits ────────────────────────────────────────────────
MAX_POSITION_PCT = 10.0           # max single-name weight (%)
TRIM_ZONE_MAX_PCT = 1.0          # max weight when conviction is 40-60%

# ── Upside score from PE z-score ───────────────────────────────────
def upside_score(z: float) -> float:
    """Map PE z-score to upside score. Only buy when cheap."""
    if z < -1.5:
        return 1.0    # very cheap
    elif z < -0.5:
        return 0.7    # cheap
    else:
        return 0.0    # fair value or expensive — no new allocation


# ── Profit-taking triggers ─────────────────────────────────────────
@dataclass
class ProfitTarget:
    """Tracks profit-taking levels for a position."""
    mean_pe: float
    std_pe: float
    trimmed_at_mean: bool = False
    trimmed_at_1sd: bool = False

    @property
    def mean_price_target(self) -> float:
        """PE at mean — trim half."""
        return self.mean_pe

    @property
    def plus_1sd_target(self) -> float:
        """PE at mean + 1SD — trim another half."""
        return self.mean_pe + self.std_pe

    @property
    def plus_2sd_target(self) -> float:
        """PE at mean + 2SD — full exit."""
        return self.mean_pe + 2 * self.std_pe

    def check_profit_taking(self, current_pe: float) -> str:
        """Check if profit-taking should trigger.

        Returns:
            'none' — no action
            'trim_half' — hit mean, trim 50%
            'trim_quarter' — hit +1SD, trim to 25% of original
            'full_exit' — hit +2SD, sell everything
        """
        if current_pe >= self.plus_2sd_target:
            return 'full_exit'
        elif current_pe >= self.plus_1sd_target and not self.trimmed_at_1sd:
            self.trimmed_at_1sd = True
            return 'trim_quarter'
        elif current_pe >= self.mean_pe and not self.trimmed_at_mean:
            self.trimmed_at_mean = True
            return 'trim_half'
        return 'none'


# ── Position state ─────────────────────────────────────────────────
@dataclass
class Position:
    """Tracks a single ticker's position in the portfolio."""
    ticker: str
    shares: float = 0.0
    cost_basis: float = 0.0       # average cost per share
    profit_target: Optional[ProfitTarget] = None

    @property
    def is_held(self) -> bool:
        return self.shares > 0


# ── Core allocation logic ──────────────────────────────────────────
@dataclass
class TickerSignal:
    """All signals needed for allocation decision on one ticker."""
    ticker: str
    conviction: float             # 0-100
    current_pe: float
    pe_z_score: float
    pe_mean: float
    pe_std: float
    price: float


def compute_target_weights(
    signals: list[TickerSignal],
    held_tickers: set[str],
) -> dict[str, float]:
    """Compute target portfolio weights for all tickers.

    Args:
        signals: list of TickerSignal for each candidate ticker
        held_tickers: set of tickers currently in portfolio

    Returns:
        dict of {ticker: target_weight_pct} (0-100 scale)
        Tickers not in the dict should have 0% weight.
    """
    weights: dict[str, float] = {}

    for s in signals:
        # Gate 1: Conviction
        if s.conviction < CONVICTION_EXIT:
            # Below 40 — full exit
            weights[s.ticker] = 0.0
            continue
        elif s.conviction < CONVICTION_FULL_ELIGIBLE:
            # 40-60 — trim to ≤1% if held, otherwise 0
            if s.ticker in held_tickers:
                weights[s.ticker] = TRIM_ZONE_MAX_PCT
            else:
                weights[s.ticker] = 0.0
            continue

        # Gate 2: Conviction ≥ 60, compute upside-based weight
        u_score = upside_score(s.pe_z_score)
        raw = (s.conviction / 100.0) * u_score
        weights[s.ticker] = raw

    # Normalize eligible weights (those with raw > 0)
    eligible = {t: w for t, w in weights.items() if w > TRIM_ZONE_MAX_PCT}
    total_raw = sum(eligible.values())

    if total_raw > 0:
        for t in eligible:
            normalized = (eligible[t] / total_raw) * 100.0
            # Apply position cap
            weights[t] = min(normalized, MAX_POSITION_PCT)

    return weights


def decide_actions(
    signals: list[TickerSignal],
    positions: dict[str, Position],
    portfolio_value: float,
    tx_cost_bps: float = 10.0,
    rebalance_threshold_pct: float = 1.0,
) -> list[dict]:
    """Decide buy/sell/trim actions for the portfolio.

    Args:
        signals: current signals for all tickers
        positions: current positions {ticker: Position}
        portfolio_value: total portfolio value (cash + holdings)
        tx_cost_bps: transaction cost in basis points
        rebalance_threshold_pct: min weight drift to trigger trade

    Returns:
        list of action dicts: {ticker, action, shares, reason}
    """
    held = {t for t, p in positions.items() if p.is_held}
    target_weights = compute_target_weights(signals, held)

    actions = []
    signal_map = {s.ticker: s for s in signals}

    for s in signals:
        pos = positions.get(s.ticker, Position(ticker=s.ticker))
        target_pct = target_weights.get(s.ticker, 0.0)
        current_value = pos.shares * s.price
        current_pct = (current_value / portfolio_value * 100) if portfolio_value > 0 else 0

        # Check profit-taking first (overrides target weight)
        if pos.is_held and pos.profit_target:
            pt_action = pos.profit_target.check_profit_taking(s.current_pe)
            if pt_action == 'full_exit':
                actions.append({
                    'ticker': s.ticker,
                    'action': 'SELL_ALL',
                    'shares': pos.shares,
                    'reason': f'Profit take: PE {s.current_pe:.1f}x hit +2SD ({pos.profit_target.plus_2sd_target:.1f}x)',
                })
                continue
            elif pt_action == 'trim_half':
                trim_shares = pos.shares * 0.5
                actions.append({
                    'ticker': s.ticker,
                    'action': 'SELL',
                    'shares': trim_shares,
                    'reason': f'Profit take: PE {s.current_pe:.1f}x hit mean ({pos.profit_target.mean_pe:.1f}x), trim half',
                })
                continue
            elif pt_action == 'trim_quarter':
                trim_shares = pos.shares * 0.5
                actions.append({
                    'ticker': s.ticker,
                    'action': 'SELL',
                    'shares': trim_shares,
                    'reason': f'Profit take: PE {s.current_pe:.1f}x hit +1SD ({pos.profit_target.plus_1sd_target:.1f}x), trim half again',
                })
                continue

        # Conviction-based exit
        if s.conviction < CONVICTION_EXIT and pos.is_held:
            actions.append({
                'ticker': s.ticker,
                'action': 'SELL_ALL',
                'shares': pos.shares,
                'reason': f'Conviction {s.conviction:.0f} < {CONVICTION_EXIT} — full exit',
            })
            continue

        # Normal rebalancing
        delta_pct = target_pct - current_pct
        if abs(delta_pct) < rebalance_threshold_pct:
            continue  # drift too small

        delta_value = portfolio_value * delta_pct / 100.0

        if delta_value > 0 and s.price > 0:
            # Buy
            shares_to_buy = delta_value / s.price
            actions.append({
                'ticker': s.ticker,
                'action': 'BUY',
                'shares': shares_to_buy,
                'reason': f'Target {target_pct:.1f}% vs current {current_pct:.1f}% (conv={s.conviction:.0f}, z={s.pe_z_score:.2f})',
            })
        elif delta_value < 0 and pos.is_held:
            # Sell
            shares_to_sell = min(abs(delta_value) / s.price, pos.shares)
            actions.append({
                'ticker': s.ticker,
                'action': 'SELL',
                'shares': shares_to_sell,
                'reason': f'Target {target_pct:.1f}% vs current {current_pct:.1f}% (conv={s.conviction:.0f}, z={s.pe_z_score:.2f})',
            })

    return actions
