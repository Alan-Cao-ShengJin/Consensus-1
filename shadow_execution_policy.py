"""Shadow execution policy: translate replay recommendations into shadow trades.

Deterministic and explicit. Every recommendation-to-trade mapping is defined here.
No silent invention of trade behavior.

Execution assumption (v1):
  - Recommendations generated as-of review date T
  - Shadow trades execute at the next available trading day close AFTER T
  - This ensures the execution price is not the same price used to form the
    recommendation, maintaining causality between signal and fill
  - If no next-day price exists, the trade is skipped and logged as unfillable
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Optional

from models import ActionType
from portfolio_decision_engine import TickerDecision, PortfolioReviewResult
from shadow_portfolio import ShadowPortfolio, ShadowTrade

logger = logging.getLogger(__name__)


@dataclass
class ExecutionResult:
    """Result of applying one review's recommendations to the shadow portfolio."""
    review_date: date
    execution_date: Optional[date]
    trades_applied: list[ShadowTrade]
    trades_skipped: list[dict]  # {ticker, action, reason}
    fallback_count: int = 0     # number of times fallback behavior was used


def get_execution_price(
    prices_by_ticker: dict[str, list[tuple[date, float]]],
    ticker: str,
    review_date: date,
) -> tuple[Optional[date], Optional[float]]:
    """Find the next available trading day close AFTER review_date.

    Args:
        prices_by_ticker: {ticker: [(date, close_price), ...]} sorted ascending.
        ticker: Ticker to look up.
        review_date: The review date (signal date).

    Returns:
        (execution_date, execution_price) or (None, None) if no next-day price.

    Anti-leakage: execution price comes strictly AFTER the review date.
    The recommendation was formed using data as-of review_date; the trade
    fills at the next day's close, which was not available when the
    recommendation was generated.
    """
    ticker_prices = prices_by_ticker.get(ticker, [])
    for d, price in ticker_prices:
        if d > review_date:
            return d, price
    return None, None


def apply_recommendations(
    portfolio: ShadowPortfolio,
    result: PortfolioReviewResult,
    prices_by_ticker: dict[str, list[tuple[date, float]]],
    target_initiation_weight_pct: float = 3.0,
) -> ExecutionResult:
    """Apply one review's recommendations to the shadow portfolio.

    Execution rules (deterministic, explicit):
      INITIATE  -> buy to reach target starter weight
      ADD       -> increase weight per recommendation delta
      TRIM      -> reduce weight per recommendation delta
      EXIT      -> fully exit position
      HOLD / PROBATION / NO_ACTION -> no trade

    Funded pairings are respected: if a funded_by_ticker is present,
    the funding exit/trim is executed first to free capital.

    Args:
        portfolio: The shadow portfolio to modify.
        result: The portfolio review result with recommendations.
        prices_by_ticker: Price history for execution price lookup.
        target_initiation_weight_pct: Default starter weight for initiations.
    """
    exec_result = ExecutionResult(
        review_date=result.review_date,
        execution_date=None,
        trades_applied=[],
        trades_skipped=[],
    )

    # Separate funded exits/trims from main decisions to execute them first
    funded_tickers: set[str] = set()
    for d in result.decisions:
        if d.funded_by_ticker:
            funded_tickers.add(d.funded_by_ticker)

    # Process decisions in priority order (already sorted by engine)
    # First pass: execute funded exits/trims
    # Second pass: execute remaining decisions
    ordered = _order_for_execution(result.decisions, funded_tickers)

    for decision in ordered:
        trades = _execute_decision(
            portfolio, decision, prices_by_ticker, result.review_date,
            target_initiation_weight_pct, exec_result,
        )
        exec_result.trades_applied.extend(trades)

    # Record execution date from first trade
    if exec_result.trades_applied:
        exec_result.execution_date = exec_result.trades_applied[0].trade_date

    return exec_result


def _order_for_execution(
    decisions: list[TickerDecision],
    funded_tickers: set[str],
) -> list[TickerDecision]:
    """Order decisions for execution: funded exits first, then by priority."""
    funded_exits = []
    others = []
    for d in decisions:
        if d.ticker in funded_tickers and d.action in (ActionType.EXIT, ActionType.TRIM):
            funded_exits.append(d)
        else:
            others.append(d)
    return funded_exits + others


def _execute_decision(
    portfolio: ShadowPortfolio,
    decision: TickerDecision,
    prices_by_ticker: dict[str, list[tuple[date, float]]],
    review_date: date,
    target_initiation_weight_pct: float,
    exec_result: ExecutionResult,
) -> list[ShadowTrade]:
    """Execute a single decision against the shadow portfolio."""
    trades: list[ShadowTrade] = []
    ticker = decision.ticker
    action = decision.action

    # No-trade actions
    if action in (ActionType.HOLD, ActionType.PROBATION, ActionType.NO_ACTION):
        # Update probation tracking on shadow positions
        if action == ActionType.PROBATION:
            pos = portfolio.get_position(ticker)
            if pos and not pos.probation_flag:
                pos.probation_flag = True
                pos.probation_start_date = review_date
                pos.probation_reviews_count = 0
            elif pos and pos.probation_flag:
                pos.probation_reviews_count += 1
        return trades

    # Get execution price (next trading day after review)
    exec_date, exec_price = get_execution_price(prices_by_ticker, ticker, review_date)
    if exec_price is None or exec_date is None:
        exec_result.trades_skipped.append({
            "ticker": ticker,
            "action": action.value,
            "reason": f"No execution price available after {review_date.isoformat()}",
        })
        return trades

    if action == ActionType.EXIT:
        pos = portfolio.get_position(ticker)
        if pos is None:
            return trades
        trade = portfolio.apply_trade(
            trade_date=exec_date,
            ticker=ticker,
            action="exit",
            shares=-pos.shares,
            price=exec_price,
            reason=decision.rationale,
        )
        if trade:
            trades.append(trade)
            # Set cooldown on shadow position record (already removed from portfolio)

    elif action == ActionType.TRIM:
        pos = portfolio.get_position(ticker)
        if pos is None:
            return trades
        # Compute shares to trim based on weight change
        total_val = portfolio.total_value(
            {t: _latest_price_as_of(prices_by_ticker, t, exec_date)
             for t in portfolio.held_tickers()}
        )
        if decision.target_weight_change and total_val > 0:
            target_notional = abs(decision.target_weight_change) / 100.0 * total_val
            trim_shares = target_notional / exec_price
        else:
            trim_shares = pos.shares * 0.5  # fallback: trim half
            exec_result.fallback_count += 1
        trade = portfolio.apply_trade(
            trade_date=exec_date,
            ticker=ticker,
            action="trim",
            shares=-trim_shares,
            price=exec_price,
            reason=decision.rationale,
        )
        if trade:
            trades.append(trade)

    elif action == ActionType.INITIATE:
        # Buy to reach target starter weight
        prices_now = {
            t: _latest_price_as_of(prices_by_ticker, t, exec_date)
            for t in portfolio.held_tickers()
        }
        prices_now[ticker] = exec_price
        total_val = portfolio.total_value(prices_now)
        if total_val <= 0:
            total_val = portfolio.cash

        target_weight = decision.suggested_weight or target_initiation_weight_pct
        target_notional = (target_weight / 100.0) * total_val
        buy_shares = target_notional / exec_price

        trade = portfolio.apply_trade(
            trade_date=exec_date,
            ticker=ticker,
            action="initiate",
            shares=buy_shares,
            price=exec_price,
            funded_by_ticker=decision.funded_by_ticker,
            reason=decision.rationale,
        )
        if trade:
            trades.append(trade)

    elif action == ActionType.ADD:
        pos = portfolio.get_position(ticker)
        if pos is None:
            return trades
        prices_now = {
            t: _latest_price_as_of(prices_by_ticker, t, exec_date)
            for t in portfolio.held_tickers()
        }
        total_val = portfolio.total_value(prices_now)
        if decision.target_weight_change and total_val > 0:
            add_notional = (decision.target_weight_change / 100.0) * total_val
            add_shares = add_notional / exec_price
        else:
            add_shares = pos.shares * 0.2  # fallback: add 20%
            exec_result.fallback_count += 1

        trade = portfolio.apply_trade(
            trade_date=exec_date,
            ticker=ticker,
            action="add",
            shares=add_shares,
            price=exec_price,
            reason=decision.rationale,
        )
        if trade:
            trades.append(trade)

    return trades


def _latest_price_as_of(
    prices_by_ticker: dict[str, list[tuple[date, float]]],
    ticker: str,
    as_of: date,
) -> float:
    """Get latest price on or before as_of from preloaded price data."""
    ticker_prices = prices_by_ticker.get(ticker, [])
    best = 0.0
    for d, price in ticker_prices:
        if d <= as_of:
            best = price
        else:
            break
    return best
