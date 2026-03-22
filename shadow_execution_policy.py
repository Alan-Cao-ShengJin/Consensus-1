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


# ---------------------------------------------------------------------------
# Conviction-based position sizing
# ---------------------------------------------------------------------------

def conviction_based_weight(conviction: float) -> float:
    """Map conviction score to target initiation weight on a smooth curve.

    Linear interpolation between anchor points:
      conviction 40 (floor) -> 1.0%
      conviction 80 (ceiling) -> 7.0%

    Clamped at both ends. Every point of conviction earns proportional sizing.
    Examples: 50 -> 2.5%, 60 -> 4.0%, 65 -> 4.75%, 70 -> 5.5%, 75 -> 6.25%
    """
    floor_conv, floor_wt = 40.0, 1.0
    ceil_conv, ceil_wt = 80.0, 7.0

    if conviction <= floor_conv:
        return floor_wt
    if conviction >= ceil_conv:
        return ceil_wt

    t = (conviction - floor_conv) / (ceil_conv - floor_conv)
    return round(floor_wt + t * (ceil_wt - floor_wt), 2)


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
    cash_reserve_pct: float = 5.0,
) -> ExecutionResult:
    """Apply one review's recommendations to the shadow portfolio.

    Execution rules (deterministic, explicit):
      INITIATE  -> buy to reach target starter weight
      ADD       -> increase weight per recommendation delta
      TRIM      -> reduce weight per recommendation delta
      EXIT      -> fully exit position
      HOLD / PROBATION / NO_ACTION -> no trade

    Core-satellite mode: when portfolio.core_ticker is set, buys are
    funded by selling the core (e.g. SPY), and sell proceeds are
    reinvested back into the core.

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
        # Skip decisions for the core ticker itself — it's passive
        if portfolio.is_core_satellite and decision.ticker == portfolio.core_ticker:
            continue

        trades = _execute_decision(
            portfolio, decision, prices_by_ticker, result.review_date,
            target_initiation_weight_pct, exec_result, cash_reserve_pct,
        )
        exec_result.trades_applied.extend(trades)

    # Core-satellite: reinvest any excess cash back to core after all sells
    if portfolio.is_core_satellite and portfolio.cash > 0:
        core_exec_date, core_exec_price = get_execution_price(
            prices_by_ticker, portfolio.core_ticker, result.review_date,
        )
        if core_exec_price and core_exec_date:
            reinvest_trade = portfolio.reinvest_to_core(core_exec_price, core_exec_date)
            if reinvest_trade:
                exec_result.trades_applied.append(reinvest_trade)

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
    cash_reserve_pct: float = 5.0,
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
        # Buy to reach target starter weight — sized by conviction
        prices_now = {
            t: _latest_price_as_of(prices_by_ticker, t, exec_date)
            for t in portfolio.held_tickers()
        }
        prices_now[ticker] = exec_price
        total_val = portfolio.total_value(prices_now)
        if total_val <= 0:
            total_val = portfolio.cash

        # Conviction-based sizing: higher conviction = larger position
        conviction = decision.thesis_conviction or 50.0
        target_weight = decision.suggested_weight or conviction_based_weight(conviction)
        target_notional = (target_weight / 100.0) * total_val

        # Enforce cash reserve: cap buy notional so cash stays above reserve floor
        cash_reserve_amount = (cash_reserve_pct / 100.0) * total_val
        max_spend = max(0.0, portfolio.cash - cash_reserve_amount)
        if not portfolio.is_core_satellite and target_notional > max_spend:
            if max_spend < exec_price:
                # Can't even buy 1 share while maintaining reserve
                exec_result.trades_skipped.append({
                    "ticker": ticker,
                    "action": "initiate",
                    "reason": f"Cash reserve: need ${cash_reserve_amount:,.0f} reserve, only ${portfolio.cash:,.0f} cash",
                })
                return trades
            target_notional = max_spend
            target_weight = (target_notional / total_val) * 100.0

        logger.info(
            "Initiate sizing: %s conviction=%.1f -> target_weight=%.1f%%",
            ticker, conviction, target_weight,
        )
        buy_shares = target_notional / exec_price

        # Core-satellite: sell core to fund the buy if cash is insufficient
        if portfolio.is_core_satellite and portfolio.cash < target_notional:
            # Buffer accounts for transaction costs on both sell-core and buy-satellite sides
            tx_buffer = target_notional * (portfolio.transaction_cost_bps / 10000.0) * 2.5 + 200
            shortfall = target_notional - portfolio.cash + tx_buffer
            core_price = _latest_price_as_of(prices_by_ticker, portfolio.core_ticker, exec_date)
            if core_price > 0:
                core_trade = portfolio.sell_core_to_fund(shortfall, core_price, exec_date)
                if core_trade:
                    trades.append(core_trade)

        trade = portfolio.apply_trade(
            trade_date=exec_date,
            ticker=ticker,
            action="initiate",
            shares=buy_shares,
            price=exec_price,
            funded_by_ticker=decision.funded_by_ticker or portfolio.core_ticker,
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

        add_cost = abs(add_shares * exec_price)

        # Enforce cash reserve for ADD actions
        if not portfolio.is_core_satellite:
            cash_reserve_amount = (cash_reserve_pct / 100.0) * total_val
            max_spend = max(0.0, portfolio.cash - cash_reserve_amount)
            if add_cost > max_spend:
                if max_spend < exec_price:
                    exec_result.trades_skipped.append({
                        "ticker": ticker,
                        "action": "add",
                        "reason": f"Cash reserve: insufficient cash after reserve",
                    })
                    return trades
                add_shares = max_spend / exec_price
                add_cost = max_spend

        # Core-satellite: sell core to fund the add if cash is insufficient
        if portfolio.is_core_satellite and portfolio.cash < add_cost:
            tx_buffer = add_cost * (portfolio.transaction_cost_bps / 10000.0) * 2.5 + 200
            shortfall = add_cost - portfolio.cash + tx_buffer
            core_price = _latest_price_as_of(prices_by_ticker, portfolio.core_ticker, exec_date)
            if core_price > 0:
                core_trade = portfolio.sell_core_to_fund(shortfall, core_price, exec_date)
                if core_trade:
                    trades.append(core_trade)

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
