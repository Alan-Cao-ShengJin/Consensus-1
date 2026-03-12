"""Paper execution engine: apply validated order intents to a paper portfolio.

This is forward-operating paper execution, distinct from replay:
  - Replay is historical backtest evaluation
  - Paper execution is current/forward order-intent handling

Key guarantees:
  - Only validated, non-blocked intents are executed
  - Only paper portfolio state is mutated (never live positions)
  - Deterministic fill assumptions (configurable)
  - All fills, blocks, and snapshots are auditable
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

from models import ActionType
from execution_wrapper import OrderIntent, ExecutionBatch
from execution_policy import compute_transaction_cost, ExecutionPolicyConfig, DEFAULT_POLICY

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Paper position and portfolio
# ---------------------------------------------------------------------------

@dataclass
class PaperPosition:
    """A position in the paper portfolio."""
    ticker: str
    shares: float
    avg_cost: float
    entry_date: date

    @property
    def cost_basis(self) -> float:
        return self.shares * self.avg_cost

    def market_value(self, price: float) -> float:
        return self.shares * price


@dataclass
class PaperFill:
    """Record of a paper execution fill."""
    fill_id: str
    ticker: str
    side: str                  # buy / sell
    action_type: str           # initiate / add / trim / exit
    shares: float
    fill_price: float
    notional: float
    transaction_cost: float
    filled_at: datetime
    order_intent_ticker: str   # back-reference
    review_date: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "fill_id": self.fill_id,
            "ticker": self.ticker,
            "side": self.side,
            "action_type": self.action_type,
            "shares": round(self.shares, 4),
            "fill_price": round(self.fill_price, 4),
            "notional": round(self.notional, 2),
            "transaction_cost": round(self.transaction_cost, 2),
            "filled_at": self.filled_at.isoformat(),
            "review_date": self.review_date,
        }


@dataclass
class PaperPortfolioSnapshot:
    """Point-in-time snapshot of the paper portfolio."""
    snapshot_date: date
    total_value: float
    cash: float
    invested: float
    positions: dict[str, float]   # ticker -> market_value
    weights: dict[str, float]     # ticker -> weight %
    num_positions: int = 0
    snapshot_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "snapshot_date": self.snapshot_date.isoformat(),
            "total_value": round(self.total_value, 2),
            "cash": round(self.cash, 2),
            "invested": round(self.invested, 2),
            "positions": {k: round(v, 2) for k, v in self.positions.items()},
            "weights": {k: round(v, 2) for k, v in self.weights.items()},
            "num_positions": self.num_positions,
        }


class PaperPortfolio:
    """Paper portfolio for forward-operating paper execution.

    Distinct from ShadowPortfolio (which is replay-only).
    """

    def __init__(self, initial_cash: float, transaction_cost_bps: float = 10.0):
        self.initial_cash = initial_cash
        self.cash = initial_cash
        self.transaction_cost_bps = transaction_cost_bps
        self.positions: dict[str, PaperPosition] = {}
        self.fills: list[PaperFill] = []
        self.snapshots: list[PaperPortfolioSnapshot] = []
        self.realized_pnl: float = 0.0
        self._fill_counter: int = 0

    def total_value(self, prices: dict[str, float]) -> float:
        invested = sum(
            pos.market_value(prices.get(ticker, pos.avg_cost))
            for ticker, pos in self.positions.items()
        )
        return self.cash + invested

    def get_weight(self, ticker: str, prices: dict[str, float]) -> float:
        total = self.total_value(prices)
        if total <= 0 or ticker not in self.positions:
            return 0.0
        price = prices.get(ticker, self.positions[ticker].avg_cost)
        return (self.positions[ticker].market_value(price) / total) * 100.0

    def get_weights(self, prices: dict[str, float]) -> dict[str, float]:
        total = self.total_value(prices)
        if total <= 0:
            return {}
        result = {}
        for ticker, pos in self.positions.items():
            price = prices.get(ticker, pos.avg_cost)
            result[ticker] = (pos.market_value(price) / total) * 100.0
        return result

    def take_snapshot(self, snap_date: date, prices: dict[str, float]) -> PaperPortfolioSnapshot:
        total = self.total_value(prices)
        pos_values = {}
        pos_weights = {}
        for ticker, pos in self.positions.items():
            price = prices.get(ticker, pos.avg_cost)
            mv = pos.market_value(price)
            pos_values[ticker] = mv
            pos_weights[ticker] = (mv / total * 100.0) if total > 0 else 0.0

        snap = PaperPortfolioSnapshot(
            snapshot_date=snap_date,
            total_value=total,
            cash=self.cash,
            invested=total - self.cash,
            positions=pos_values,
            weights=pos_weights,
            num_positions=len(self.positions),
        )
        self.snapshots.append(snap)
        return snap

    def _next_fill_id(self) -> str:
        self._fill_counter += 1
        return f"PF-{self._fill_counter:06d}"

    def execute_buy(
        self,
        ticker: str,
        shares: float,
        price: float,
        action_type: str,
        trade_date: date,
        review_date: Optional[str] = None,
    ) -> Optional[PaperFill]:
        """Execute a paper buy."""
        if price <= 0 or shares <= 0:
            return None

        notional = shares * price
        cost = compute_transaction_cost(notional, self.transaction_cost_bps)
        total_cost = notional + cost

        if total_cost > self.cash:
            # Buy what we can afford
            affordable = max(0, self.cash - cost)
            if affordable <= 0:
                return None
            shares = affordable / price
            notional = shares * price
            cost = compute_transaction_cost(notional, self.transaction_cost_bps)
            total_cost = notional + cost

        self.cash -= total_cost

        if ticker in self.positions:
            pos = self.positions[ticker]
            total_shares = pos.shares + shares
            pos.avg_cost = (pos.cost_basis + notional) / total_shares if total_shares > 0 else 0
            pos.shares = total_shares
        else:
            self.positions[ticker] = PaperPosition(
                ticker=ticker,
                shares=shares,
                avg_cost=price,
                entry_date=trade_date,
            )

        fill = PaperFill(
            fill_id=self._next_fill_id(),
            ticker=ticker,
            side="buy",
            action_type=action_type,
            shares=shares,
            fill_price=price,
            notional=notional,
            transaction_cost=cost,
            filled_at=datetime.utcnow(),
            order_intent_ticker=ticker,
            review_date=review_date,
        )
        self.fills.append(fill)
        return fill

    def execute_sell(
        self,
        ticker: str,
        shares: float,
        price: float,
        action_type: str,
        trade_date: date,
        review_date: Optional[str] = None,
    ) -> Optional[PaperFill]:
        """Execute a paper sell."""
        if price <= 0 or shares <= 0:
            return None
        if ticker not in self.positions:
            return None

        pos = self.positions[ticker]
        sell_shares = min(shares, pos.shares)
        notional = sell_shares * price
        cost = compute_transaction_cost(notional, self.transaction_cost_bps)

        self.realized_pnl += (price - pos.avg_cost) * sell_shares
        self.cash += notional - cost
        pos.shares -= sell_shares

        if pos.shares <= 0.001:
            del self.positions[ticker]

        fill = PaperFill(
            fill_id=self._next_fill_id(),
            ticker=ticker,
            side="sell",
            action_type=action_type,
            shares=-sell_shares,
            fill_price=price,
            notional=notional,
            transaction_cost=cost,
            filled_at=datetime.utcnow(),
            order_intent_ticker=ticker,
            review_date=review_date,
        )
        self.fills.append(fill)
        return fill

    def to_dict(self) -> dict:
        return {
            "initial_cash": self.initial_cash,
            "cash": round(self.cash, 2),
            "realized_pnl": round(self.realized_pnl, 2),
            "num_positions": len(self.positions),
            "num_fills": len(self.fills),
            "positions": {
                t: {"shares": round(p.shares, 4), "avg_cost": round(p.avg_cost, 4)}
                for t, p in self.positions.items()
            },
        }


# ---------------------------------------------------------------------------
# Execution summary
# ---------------------------------------------------------------------------

@dataclass
class PaperExecutionSummary:
    """Summary of one paper execution run."""
    execution_date: date
    review_date: Optional[str]
    intents_received: int
    intents_approved: int
    intents_blocked: int
    fills_executed: int
    total_buy_notional: float
    total_sell_notional: float
    total_transaction_cost: float
    fills: list[PaperFill] = field(default_factory=list)
    blocked_intents: list[OrderIntent] = field(default_factory=list)
    portfolio_snapshot: Optional[PaperPortfolioSnapshot] = None

    def to_dict(self) -> dict:
        return {
            "execution_date": self.execution_date.isoformat(),
            "review_date": self.review_date,
            "intents_received": self.intents_received,
            "intents_approved": self.intents_approved,
            "intents_blocked": self.intents_blocked,
            "fills_executed": self.fills_executed,
            "total_buy_notional": round(self.total_buy_notional, 2),
            "total_sell_notional": round(self.total_sell_notional, 2),
            "total_transaction_cost": round(self.total_transaction_cost, 2),
            "fills": [f.to_dict() for f in self.fills],
            "blocked_intents": [oi.to_dict() for oi in self.blocked_intents],
            "portfolio_snapshot": self.portfolio_snapshot.to_dict() if self.portfolio_snapshot else None,
        }


# ---------------------------------------------------------------------------
# Paper execution: apply validated intents
# ---------------------------------------------------------------------------

def paper_execute(
    portfolio: PaperPortfolio,
    approved_intents: list[OrderIntent],
    blocked_intents: list[OrderIntent],
    execution_date: date,
    fill_prices: dict[str, float],
    config: ExecutionPolicyConfig = DEFAULT_POLICY,
) -> PaperExecutionSummary:
    """Apply validated order intents to the paper portfolio.

    Args:
        portfolio: The paper portfolio to mutate.
        approved_intents: Intents that passed guardrails.
        blocked_intents: Intents that failed guardrails (recorded only).
        execution_date: Date of paper execution.
        fill_prices: {ticker: price} for fill execution.
        config: Execution policy for transaction costs.

    Fill assumption (Step 9 v1):
        Fill at provided price (typically next-close or current price).
        No slippage model.
    """
    # Order execution: sells first, then buys (to free capital)
    sells = [oi for oi in approved_intents if oi.side == "sell"]
    buys = [oi for oi in approved_intents if oi.side == "buy"]
    ordered = sells + buys

    fills: list[PaperFill] = []
    total_buy = 0.0
    total_sell = 0.0
    total_cost = 0.0

    for intent in ordered:
        price = fill_prices.get(intent.ticker)
        if price is None or price <= 0:
            logger.warning("No fill price for %s — skipping", intent.ticker)
            continue

        if intent.side == "buy":
            shares = abs(intent.estimated_shares) if intent.estimated_shares else (
                abs(intent.notional_delta) / price if price > 0 else 0
            )
            fill = portfolio.execute_buy(
                ticker=intent.ticker,
                shares=shares,
                price=price,
                action_type=intent.action_type.value,
                trade_date=execution_date,
                review_date=intent.review_date,
            )
            if fill:
                fills.append(fill)
                total_buy += fill.notional
                total_cost += fill.transaction_cost

        elif intent.side == "sell":
            if intent.action_type == ActionType.EXIT:
                # Full exit: sell all shares
                pos = portfolio.positions.get(intent.ticker)
                shares = pos.shares if pos else 0
            else:
                shares = abs(intent.estimated_shares) if intent.estimated_shares else (
                    abs(intent.notional_delta) / price if price > 0 else 0
                )
            fill = portfolio.execute_sell(
                ticker=intent.ticker,
                shares=shares,
                price=price,
                action_type=intent.action_type.value,
                trade_date=execution_date,
                review_date=intent.review_date,
            )
            if fill:
                fills.append(fill)
                total_sell += fill.notional
                total_cost += fill.transaction_cost

    # Take snapshot after execution
    snapshot = portfolio.take_snapshot(execution_date, fill_prices)

    review_date = approved_intents[0].review_date if approved_intents else None

    return PaperExecutionSummary(
        execution_date=execution_date,
        review_date=review_date,
        intents_received=len(approved_intents) + len(blocked_intents),
        intents_approved=len(approved_intents),
        intents_blocked=len(blocked_intents),
        fills_executed=len(fills),
        total_buy_notional=total_buy,
        total_sell_notional=total_sell,
        total_transaction_cost=total_cost,
        fills=fills,
        blocked_intents=blocked_intents,
        portfolio_snapshot=snapshot,
    )


# ---------------------------------------------------------------------------
# File-based persistence (Step 9 v1: file output is cleaner than DB)
# ---------------------------------------------------------------------------

def export_execution_artifacts(
    summary: PaperExecutionSummary,
    batch: ExecutionBatch,
    output_dir: str = "execution_outputs",
) -> str:
    """Export execution artifacts to JSON files.

    Creates:
      - {output_dir}/{date}_order_intents.json
      - {output_dir}/{date}_paper_fills.json
      - {output_dir}/{date}_execution_summary.json
      - {output_dir}/{date}_portfolio_snapshot.json

    Returns the output directory path.
    """
    os.makedirs(output_dir, exist_ok=True)
    date_str = summary.execution_date.isoformat()

    # Order intents
    with open(os.path.join(output_dir, f"{date_str}_order_intents.json"), "w") as f:
        json.dump(batch.to_dict(), f, indent=2)

    # Paper fills
    with open(os.path.join(output_dir, f"{date_str}_paper_fills.json"), "w") as f:
        json.dump([fill.to_dict() for fill in summary.fills], f, indent=2)

    # Execution summary
    with open(os.path.join(output_dir, f"{date_str}_execution_summary.json"), "w") as f:
        json.dump(summary.to_dict(), f, indent=2)

    # Portfolio snapshot
    if summary.portfolio_snapshot:
        with open(os.path.join(output_dir, f"{date_str}_portfolio_snapshot.json"), "w") as f:
            json.dump(summary.portfolio_snapshot.to_dict(), f, indent=2)

    return output_dir


def format_execution_text(summary: PaperExecutionSummary) -> str:
    """Format execution summary as human-readable text."""
    lines = []
    lines.append("=" * 60)
    lines.append("PAPER EXECUTION SUMMARY")
    lines.append("=" * 60)
    lines.append(f"  Execution date:    {summary.execution_date}")
    lines.append(f"  Review date:       {summary.review_date}")
    lines.append(f"  Intents received:  {summary.intents_received}")
    lines.append(f"  Intents approved:  {summary.intents_approved}")
    lines.append(f"  Intents blocked:   {summary.intents_blocked}")
    lines.append(f"  Fills executed:    {summary.fills_executed}")
    lines.append(f"  Total buy:         ${summary.total_buy_notional:,.2f}")
    lines.append(f"  Total sell:        ${summary.total_sell_notional:,.2f}")
    lines.append(f"  Transaction cost:  ${summary.total_transaction_cost:,.2f}")
    lines.append("")

    if summary.fills:
        lines.append("FILLS:")
        for fill in summary.fills:
            lines.append(
                f"  {fill.action_type:10s} {fill.ticker:6s} "
                f"{fill.shares:+10.2f} shares @ ${fill.fill_price:,.2f} "
                f"= ${fill.notional:,.2f} (cost: ${fill.transaction_cost:,.2f})"
            )
        lines.append("")

    if summary.blocked_intents:
        lines.append("BLOCKED:")
        for bi in summary.blocked_intents:
            lines.append(f"  {bi.ticker}: {', '.join(bi.block_reasons)}")
        lines.append("")

    if summary.portfolio_snapshot:
        snap = summary.portfolio_snapshot
        lines.append("PORTFOLIO AFTER EXECUTION:")
        lines.append(f"  Total value:  ${snap.total_value:,.2f}")
        lines.append(f"  Cash:         ${snap.cash:,.2f}")
        lines.append(f"  Invested:     ${snap.invested:,.2f}")
        lines.append(f"  Positions:    {snap.num_positions}")
        if snap.weights:
            for ticker, weight in sorted(snap.weights.items(), key=lambda x: -x[1]):
                lines.append(f"    {ticker:8s} {weight:5.1f}%  (${snap.positions.get(ticker, 0):,.2f})")

    return "\n".join(lines)
