"""Shadow portfolio: simulated portfolio driven by replay recommendations.

Maintains cash + positions, applies shadow trades under deterministic
assumptions, tracks portfolio value, holdings history, and PnL over time.

This is an evaluation tool, not an execution system.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ShadowPosition:
    """A position in the shadow portfolio."""
    ticker: str
    shares: float
    avg_cost: float          # volume-weighted average cost per share
    entry_date: date
    weight_pct: float = 0.0  # current weight as % of portfolio
    # Probation tracking (mirrors live engine state for replay coherence)
    probation_flag: bool = False
    probation_start_date: Optional[date] = None
    probation_reviews_count: int = 0
    # Cooldown tracking
    cooldown_until: Optional[date] = None
    # Add count tracking
    add_count: int = 0

    @property
    def cost_basis(self) -> float:
        return self.shares * self.avg_cost

    def market_value(self, price: float) -> float:
        return self.shares * price

    def unrealized_pnl(self, price: float) -> float:
        return (price - self.avg_cost) * self.shares


@dataclass
class ShadowTrade:
    """Record of a shadow trade executed during replay."""
    trade_date: date
    ticker: str
    action: str            # initiate, add, trim, exit
    shares: float
    price: float
    notional: float        # abs(shares * price)
    transaction_cost: float
    funded_by_ticker: Optional[str] = None
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "trade_date": self.trade_date.isoformat(),
            "ticker": self.ticker,
            "action": self.action,
            "shares": round(self.shares, 4),
            "price": round(self.price, 4),
            "notional": round(self.notional, 2),
            "transaction_cost": round(self.transaction_cost, 2),
            "funded_by_ticker": self.funded_by_ticker,
            "reason": self.reason,
        }


@dataclass
class PortfolioSnapshot:
    """Point-in-time snapshot of the shadow portfolio."""
    date: date
    total_value: float
    cash: float
    invested: float
    positions: dict[str, float]   # ticker -> market_value
    weights: dict[str, float]     # ticker -> weight_pct
    num_positions: int = 0
    unrealized_pnl: float = 0.0

    def to_dict(self) -> dict:
        return {
            "date": self.date.isoformat(),
            "total_value": round(self.total_value, 2),
            "cash": round(self.cash, 2),
            "invested": round(self.invested, 2),
            "positions": {k: round(v, 2) for k, v in self.positions.items()},
            "weights": {k: round(v, 2) for k, v in self.weights.items()},
            "num_positions": self.num_positions,
            "unrealized_pnl": round(self.unrealized_pnl, 2),
        }


class ShadowPortfolio:
    """Simulated portfolio that applies shadow trades deterministically.

    Starts from all-cash. Positions are created/modified only through
    explicit apply_trade() calls driven by the execution policy.

    Core-satellite mode: when core_ticker is set, the portfolio starts
    with most capital in the core (e.g. SPY), and individual picks are
    funded by selling the core, not from cash.
    """

    def __init__(
        self,
        initial_cash: float,
        transaction_cost_bps: float = 10.0,
        core_ticker: Optional[str] = None,
        core_allocation_pct: float = 95.0,
    ):
        self.initial_cash = initial_cash
        self.cash = initial_cash
        self.transaction_cost_bps = transaction_cost_bps
        self.positions: dict[str, ShadowPosition] = {}
        self.trades: list[ShadowTrade] = []
        self.snapshots: list[PortfolioSnapshot] = []
        self.realized_pnl: float = 0.0
        # Core-satellite config
        self.core_ticker: Optional[str] = core_ticker
        self.core_allocation_pct = core_allocation_pct

    @property
    def is_core_satellite(self) -> bool:
        return self.core_ticker is not None

    def initialize_core(self, price: float, trade_date: date) -> Optional[ShadowTrade]:
        """Buy the core position (e.g. SPY) at startup.

        Allocates core_allocation_pct of initial cash to the core ticker.
        """
        if not self.core_ticker or price <= 0:
            return None
        notional = self.initial_cash * (self.core_allocation_pct / 100.0)
        shares = notional / price
        return self.apply_trade(
            trade_date=trade_date,
            ticker=self.core_ticker,
            action="initiate",
            shares=shares,
            price=price,
            reason=f"Core position: {self.core_allocation_pct:.0f}% allocation to {self.core_ticker}",
        )

    def sell_core_to_fund(
        self, amount: float, price: float, trade_date: date,
    ) -> Optional[ShadowTrade]:
        """Sell core position to free cash for a satellite buy.

        Returns the trade, or None if core has insufficient shares.
        """
        if not self.core_ticker or self.core_ticker not in self.positions:
            return None
        pos = self.positions[self.core_ticker]
        shares_needed = amount / price
        shares_to_sell = min(shares_needed, pos.shares)
        if shares_to_sell <= 0:
            return None
        return self.apply_trade(
            trade_date=trade_date,
            ticker=self.core_ticker,
            action="trim",
            shares=-shares_to_sell,
            price=price,
            reason=f"Sell core to fund satellite position",
        )

    def reinvest_to_core(
        self, price: float, trade_date: date,
    ) -> Optional[ShadowTrade]:
        """Reinvest excess cash back into the core position after a satellite sell.

        Keeps a small cash buffer (100% - core_allocation_pct).
        """
        if not self.core_ticker or price <= 0:
            return None
        target_cash_pct = 100.0 - self.core_allocation_pct
        # Use current total value to compute target cash
        # For simplicity, use a fixed target based on initial cash
        min_cash = self.initial_cash * (target_cash_pct / 100.0)
        excess = self.cash - min_cash
        if excess <= 0:
            return None
        shares = excess / price
        if self.core_ticker in self.positions:
            return self.apply_trade(
                trade_date=trade_date,
                ticker=self.core_ticker,
                action="add",
                shares=shares,
                price=price,
                reason=f"Reinvest proceeds to core",
            )
        else:
            return self.apply_trade(
                trade_date=trade_date,
                ticker=self.core_ticker,
                action="initiate",
                shares=shares,
                price=price,
                reason=f"Reinvest proceeds to core",
            )

    def total_value(self, prices: dict[str, float]) -> float:
        """Compute total portfolio value at given prices."""
        invested = sum(
            pos.market_value(prices.get(ticker, pos.avg_cost))
            for ticker, pos in self.positions.items()
        )
        return self.cash + invested

    def get_weight(self, ticker: str, prices: dict[str, float]) -> float:
        """Get current weight of a ticker as % of total portfolio."""
        total = self.total_value(prices)
        if total <= 0 or ticker not in self.positions:
            return 0.0
        price = prices.get(ticker, self.positions[ticker].avg_cost)
        return (self.positions[ticker].market_value(price) / total) * 100.0

    def take_snapshot(self, snap_date: date, prices: dict[str, float]) -> PortfolioSnapshot:
        """Record a point-in-time snapshot."""
        total = self.total_value(prices)
        pos_values = {}
        pos_weights = {}
        unrealized = 0.0
        for ticker, pos in self.positions.items():
            price = prices.get(ticker, pos.avg_cost)
            mv = pos.market_value(price)
            pos_values[ticker] = mv
            pos_weights[ticker] = (mv / total * 100.0) if total > 0 else 0.0
            unrealized += pos.unrealized_pnl(price)

        snap = PortfolioSnapshot(
            date=snap_date,
            total_value=total,
            cash=self.cash,
            invested=total - self.cash,
            positions=pos_values,
            weights=pos_weights,
            num_positions=len(self.positions),
            unrealized_pnl=unrealized,
        )
        self.snapshots.append(snap)
        return snap

    def apply_trade(
        self,
        trade_date: date,
        ticker: str,
        action: str,
        shares: float,
        price: float,
        funded_by_ticker: Optional[str] = None,
        reason: str = "",
    ) -> Optional[ShadowTrade]:
        """Apply a shadow trade to the portfolio.

        Args:
            trade_date: Execution date.
            ticker: Ticker symbol.
            action: One of 'initiate', 'add', 'trim', 'exit'.
            shares: Number of shares (positive for buy, negative for sell).
            price: Execution price per share.
            funded_by_ticker: If this trade is funded by another trade.
            reason: Human-readable reason.

        Returns:
            ShadowTrade record, or None if trade is invalid.
        """
        if price <= 0 or shares == 0:
            return None

        notional = abs(shares * price)
        cost = notional * (self.transaction_cost_bps / 10000.0)

        if action in ("initiate", "add"):
            # Buying
            total_cost = notional + cost
            if total_cost > self.cash:
                logger.warning(
                    "Insufficient cash for %s %s: need %.2f, have %.2f",
                    action, ticker, total_cost, self.cash,
                )
                # Buy what we can afford
                affordable_notional = max(0, self.cash - cost)
                if affordable_notional <= 0:
                    return None
                shares = affordable_notional / price
                notional = shares * price
                cost = notional * (self.transaction_cost_bps / 10000.0)
                total_cost = notional + cost

            self.cash -= total_cost

            if ticker in self.positions:
                pos = self.positions[ticker]
                total_shares = pos.shares + shares
                pos.avg_cost = (pos.cost_basis + notional) / total_shares if total_shares > 0 else 0
                pos.shares = total_shares
                if action == "add":
                    pos.add_count += 1
            else:
                self.positions[ticker] = ShadowPosition(
                    ticker=ticker,
                    shares=shares,
                    avg_cost=price,
                    entry_date=trade_date,
                )

        elif action in ("trim", "exit"):
            # Selling
            if ticker not in self.positions:
                logger.warning("Cannot %s %s — no position", action, ticker)
                return None
            pos = self.positions[ticker]
            sell_shares = min(abs(shares), pos.shares)
            sell_notional = sell_shares * price
            cost = sell_notional * (self.transaction_cost_bps / 10000.0)

            # Track realized PnL
            self.realized_pnl += (price - pos.avg_cost) * sell_shares

            self.cash += sell_notional - cost
            pos.shares -= sell_shares
            notional = sell_notional
            shares = -sell_shares

            if pos.shares <= 0.001:
                del self.positions[ticker]
        else:
            return None

        trade = ShadowTrade(
            trade_date=trade_date,
            ticker=ticker,
            action=action,
            shares=shares,
            price=price,
            notional=notional,
            transaction_cost=cost,
            funded_by_ticker=funded_by_ticker,
            reason=reason,
        )
        self.trades.append(trade)
        return trade

    def get_position(self, ticker: str) -> Optional[ShadowPosition]:
        return self.positions.get(ticker)

    def held_tickers(self) -> set[str]:
        return set(self.positions.keys())

    def to_dict(self) -> dict:
        return {
            "initial_cash": self.initial_cash,
            "cash": round(self.cash, 2),
            "realized_pnl": round(self.realized_pnl, 2),
            "num_positions": len(self.positions),
            "num_trades": len(self.trades),
            "positions": {
                t: {"shares": round(p.shares, 4), "avg_cost": round(p.avg_cost, 4)}
                for t, p in self.positions.items()
            },
        }
