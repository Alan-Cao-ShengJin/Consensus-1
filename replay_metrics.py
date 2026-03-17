"""Replay metrics: compute performance and discipline metrics from replay results.

All metrics are deterministic and honest. No fake sophistication.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from replay_engine import ReplayRunResult
from shadow_portfolio import ShadowPortfolio, PortfolioSnapshot


@dataclass
class ReplayMetrics:
    """Computed metrics from a replay run."""
    # --- Performance ---
    total_return_pct: float = 0.0
    annualized_return_pct: Optional[float] = None
    max_drawdown_pct: float = 0.0
    max_drawdown_peak_date: Optional[date] = None
    max_drawdown_trough_date: Optional[date] = None

    # --- Risk-adjusted returns ---
    sharpe_ratio: Optional[float] = None           # annualized Sharpe (rf=0, weekly returns)
    sortino_ratio: Optional[float] = None          # annualized Sortino (downside deviation only)
    calmar_ratio: Optional[float] = None           # annualized return / max drawdown
    win_rate_pct: Optional[float] = None           # % of periods with positive return
    profit_factor: Optional[float] = None          # sum of gains / sum of losses

    # --- Activity ---
    total_initiations: int = 0
    total_adds: int = 0
    total_trims: int = 0
    total_exits: int = 0
    total_holds: int = 0
    total_no_actions: int = 0
    total_probations: int = 0
    total_blocked: int = 0
    hit_rate_pct: Optional[float] = None  # % of exits with positive realized PnL

    # --- Turnover ---
    total_turnover_pct: float = 0.0
    avg_turnover_per_review_pct: float = 0.0
    avg_holding_period_days: Optional[float] = None

    # --- Cash exposure ---
    avg_cash_pct: float = 0.0
    min_cash_pct: float = 0.0
    max_cash_pct: float = 0.0

    # --- Discipline ---
    probation_to_exit_count: int = 0    # times probation eventually led to exit
    funded_pairing_count: int = 0       # times funded pairing was used
    turnover_cap_blocked_count: int = 0 # times turnover cap blocked action
    candidate_beat_weakest_count: int = 0

    # --- Action distribution by month ---
    actions_by_month: dict[str, dict[str, int]] = field(default_factory=dict)

    # --- Conviction at initiation ---
    initiation_convictions: list[float] = field(default_factory=list)
    avg_initiation_conviction: Optional[float] = None

    # --- Replay integrity ---
    total_review_dates: int = 0
    total_recommendations: int = 0
    total_trades_applied: int = 0
    total_trades_skipped: int = 0
    total_fallback_count: int = 0
    dates_skipped_no_data: int = 0
    missing_price_events: int = 0

    # --- Purity (Step 8.1) ---
    purity_level: str = "unknown"
    impure_candidate_fallbacks: int = 0
    impure_valuation_fallbacks: int = 0
    impure_checkpoint_fallbacks: int = 0
    skipped_impure_total: int = 0
    strict_replay: bool = False

    def to_dict(self) -> dict:
        return {
            "performance": {
                "total_return_pct": round(self.total_return_pct, 2),
                "annualized_return_pct": round(self.annualized_return_pct, 2) if self.annualized_return_pct is not None else None,
                "max_drawdown_pct": round(self.max_drawdown_pct, 2),
                "max_drawdown_peak_date": self.max_drawdown_peak_date.isoformat() if self.max_drawdown_peak_date else None,
                "max_drawdown_trough_date": self.max_drawdown_trough_date.isoformat() if self.max_drawdown_trough_date else None,
                "sharpe_ratio": round(self.sharpe_ratio, 2) if self.sharpe_ratio is not None else None,
                "sortino_ratio": round(self.sortino_ratio, 2) if self.sortino_ratio is not None else None,
                "calmar_ratio": round(self.calmar_ratio, 2) if self.calmar_ratio is not None else None,
                "win_rate_pct": round(self.win_rate_pct, 1) if self.win_rate_pct is not None else None,
                "profit_factor": round(self.profit_factor, 2) if self.profit_factor is not None else None,
            },
            "activity": {
                "initiations": self.total_initiations,
                "adds": self.total_adds,
                "trims": self.total_trims,
                "exits": self.total_exits,
                "holds": self.total_holds,
                "no_actions": self.total_no_actions,
                "probations": self.total_probations,
                "blocked": self.total_blocked,
                "hit_rate_pct": round(self.hit_rate_pct, 1) if self.hit_rate_pct is not None else None,
            },
            "turnover": {
                "total_turnover_pct": round(self.total_turnover_pct, 2),
                "avg_per_review_pct": round(self.avg_turnover_per_review_pct, 2),
                "avg_holding_period_days": round(self.avg_holding_period_days, 1) if self.avg_holding_period_days is not None else None,
            },
            "cash_exposure": {
                "avg_pct": round(self.avg_cash_pct, 1),
                "min_pct": round(self.min_cash_pct, 1),
                "max_pct": round(self.max_cash_pct, 1),
            },
            "discipline": {
                "probation_to_exit": self.probation_to_exit_count,
                "funded_pairings": self.funded_pairing_count,
                "turnover_cap_blocked": self.turnover_cap_blocked_count,
                "candidate_beat_weakest": self.candidate_beat_weakest_count,
            },
            "conviction_at_initiation": {
                "values": [round(c, 1) for c in self.initiation_convictions],
                "average": round(self.avg_initiation_conviction, 1) if self.avg_initiation_conviction is not None else None,
            },
            "actions_by_month": self.actions_by_month,
            "replay_integrity": {
                "total_review_dates": self.total_review_dates,
                "total_recommendations": self.total_recommendations,
                "total_trades_applied": self.total_trades_applied,
                "total_trades_skipped": self.total_trades_skipped,
                "total_fallback_count": self.total_fallback_count,
                "dates_skipped_no_data": self.dates_skipped_no_data,
                "missing_price_events": self.missing_price_events,
            },
            "purity": {
                "purity_level": self.purity_level,
                "strict_replay": self.strict_replay,
                "impure_candidate_fallbacks": self.impure_candidate_fallbacks,
                "impure_valuation_fallbacks": self.impure_valuation_fallbacks,
                "impure_checkpoint_fallbacks": self.impure_checkpoint_fallbacks,
                "skipped_impure_total": self.skipped_impure_total,
            },
        }


def compute_metrics(
    run_result: ReplayRunResult,
    portfolio: ShadowPortfolio,
) -> ReplayMetrics:
    """Compute all replay metrics from the run result and final portfolio state."""
    m = ReplayMetrics()

    # --- Replay integrity ---
    m.total_review_dates = run_result.total_reviews
    m.total_recommendations = run_result.total_recommendations
    m.total_trades_applied = run_result.total_trades_applied
    m.total_trades_skipped = run_result.total_trades_skipped
    m.total_fallback_count = run_result.total_fallback_count
    m.dates_skipped_no_data = len(run_result.dates_skipped_no_data)

    for rec in run_result.review_records:
        m.missing_price_events += len(rec.missing_prices)

    # --- Performance from snapshots ---
    snapshots = portfolio.snapshots
    if snapshots and portfolio.initial_cash > 0:
        final_value = snapshots[-1].total_value
        m.total_return_pct = ((final_value - portfolio.initial_cash) / portfolio.initial_cash) * 100.0

        # Annualized return
        if len(snapshots) >= 2:
            days = (snapshots[-1].date - snapshots[0].date).days
            if days > 0:
                total_return_factor = final_value / portfolio.initial_cash
                if total_return_factor > 0:
                    m.annualized_return_pct = (total_return_factor ** (365.0 / days) - 1) * 100.0

        # Risk-adjusted returns (from periodic returns)
        m.sharpe_ratio, m.sortino_ratio, m.win_rate_pct, m.profit_factor = (
            _compute_risk_metrics(snapshots)
        )

        # Max drawdown
        m.max_drawdown_pct, m.max_drawdown_peak_date, m.max_drawdown_trough_date = (
            _compute_max_drawdown(snapshots)
        )

        # Calmar ratio: annualized return / max drawdown
        if m.annualized_return_pct is not None and m.max_drawdown_pct > 0:
            m.calmar_ratio = m.annualized_return_pct / m.max_drawdown_pct

    # --- Cash exposure ---
    if snapshots:
        cash_pcts = []
        for s in snapshots:
            if s.total_value > 0:
                cash_pcts.append((s.cash / s.total_value) * 100.0)
        if cash_pcts:
            m.avg_cash_pct = sum(cash_pcts) / len(cash_pcts)
            m.min_cash_pct = min(cash_pcts)
            m.max_cash_pct = max(cash_pcts)

    # --- Activity counts ---
    action_counter = Counter()
    probation_tickers: set[str] = set()
    exit_tickers: set[str] = set()
    monthly_actions: dict[str, Counter] = {}

    for rec in run_result.review_records:
        month_key = rec.review_date.strftime("%Y-%m")
        if month_key not in monthly_actions:
            monthly_actions[month_key] = Counter()

        for d in rec.result.decisions:
            action_counter[d.action.value] += 1
            monthly_actions[month_key][d.action.value] += 1

            if d.action.value == "probation":
                probation_tickers.add(d.ticker)
            if d.action.value == "exit":
                exit_tickers.add(d.ticker)
            if d.funded_by_ticker:
                m.funded_pairing_count += 1
            if d.decision_stage == "blocked" and any(
                "turnover" in b.lower() for b in d.blocking_conditions
            ):
                m.turnover_cap_blocked_count += 1

            # Initiation conviction tracking
            if d.action.value == "initiate":
                m.initiation_convictions.append(d.action_score)

        if rec.result.blocked_actions:
            m.total_blocked += len(rec.result.blocked_actions)

    m.total_initiations = action_counter.get("initiate", 0)
    m.total_adds = action_counter.get("add", 0)
    m.total_trims = action_counter.get("trim", 0)
    m.total_exits = action_counter.get("exit", 0)
    m.total_holds = action_counter.get("hold", 0)
    m.total_no_actions = action_counter.get("no_action", 0)
    m.total_probations = action_counter.get("probation", 0)

    # Probation → exit discipline
    m.probation_to_exit_count = len(probation_tickers & exit_tickers)

    # Initiation conviction stats
    if m.initiation_convictions:
        m.avg_initiation_conviction = sum(m.initiation_convictions) / len(m.initiation_convictions)

    # Actions by month
    m.actions_by_month = {k: dict(v) for k, v in monthly_actions.items()}

    # --- Turnover ---
    for rec in run_result.review_records:
        m.total_turnover_pct += rec.result.turnover_pct_planned
    if run_result.total_reviews > 0:
        m.avg_turnover_per_review_pct = m.total_turnover_pct / run_result.total_reviews

    # --- Hit rate (from shadow trades) ---
    exit_trades = [t for t in portfolio.trades if t.action == "exit"]
    if exit_trades:
        # Hit = exit where we sold above avg cost (positive realized PnL contribution)
        # We approximate: trade.price > avg_cost would need tracking per position
        # For v1: use realized_pnl > 0 at portfolio level as a rough proxy
        # More precise: count exit trades with positive PnL
        profitable_exits = 0
        for t in exit_trades:
            if t.notional > 0:  # all exits have notional
                profitable_exits += 1  # placeholder — true hit rate needs per-exit PnL
        # Actually, we can't determine per-exit PnL without tracking avg_cost at exit time
        # For now, report None and document as v1 limitation
        m.hit_rate_pct = None

    # --- Average holding period ---
    holding_periods = _compute_holding_periods(portfolio)
    if holding_periods:
        m.avg_holding_period_days = sum(holding_periods) / len(holding_periods)

    # --- Purity (Step 8.1) ---
    m.strict_replay = run_result.strict_replay
    m.purity_level = run_result.purity_level
    m.impure_candidate_fallbacks = run_result.total_impure_candidates
    m.impure_valuation_fallbacks = run_result.total_impure_valuations
    m.impure_checkpoint_fallbacks = run_result.total_impure_checkpoints
    m.skipped_impure_total = run_result.total_skipped_impure

    return m


def _compute_max_drawdown(
    snapshots: list[PortfolioSnapshot],
) -> tuple[float, Optional[date], Optional[date]]:
    """Compute maximum drawdown from portfolio snapshots."""
    if not snapshots:
        return 0.0, None, None

    peak_value = snapshots[0].total_value
    peak_date = snapshots[0].date
    max_dd = 0.0
    dd_peak_date = None
    dd_trough_date = None

    for s in snapshots:
        if s.total_value >= peak_value:
            peak_value = s.total_value
            peak_date = s.date
        else:
            dd = ((peak_value - s.total_value) / peak_value) * 100.0
            if dd > max_dd:
                max_dd = dd
                dd_peak_date = peak_date
                dd_trough_date = s.date

    return max_dd, dd_peak_date, dd_trough_date


def _compute_holding_periods(portfolio: ShadowPortfolio) -> list[float]:
    """Compute holding periods in days for exited positions."""
    # Build entry/exit date pairs from trades
    entry_dates: dict[str, date] = {}
    periods: list[float] = []

    for trade in portfolio.trades:
        if trade.action == "initiate":
            entry_dates[trade.ticker] = trade.trade_date
        elif trade.action == "exit" and trade.ticker in entry_dates:
            days = (trade.trade_date - entry_dates[trade.ticker]).days
            periods.append(float(days))
            del entry_dates[trade.ticker]

    return periods


def _compute_risk_metrics(
    snapshots: list[PortfolioSnapshot],
) -> tuple[Optional[float], Optional[float], Optional[float], Optional[float]]:
    """Compute Sharpe, Sortino, win rate, and profit factor from portfolio snapshots.

    Uses periodic returns between consecutive snapshots (typically weekly).
    Assumes risk-free rate = 0 (standard for strategy backtests).

    Returns:
        (sharpe_ratio, sortino_ratio, win_rate_pct, profit_factor)
    """
    if len(snapshots) < 3:
        return None, None, None, None

    # Compute periodic returns
    returns: list[float] = []
    for i in range(1, len(snapshots)):
        prev_val = snapshots[i - 1].total_value
        if prev_val > 0:
            ret = (snapshots[i].total_value - prev_val) / prev_val
            returns.append(ret)

    if len(returns) < 2:
        return None, None, None, None

    # Mean and std of returns
    mean_ret = sum(returns) / len(returns)
    variance = sum((r - mean_ret) ** 2 for r in returns) / (len(returns) - 1)
    std_ret = variance ** 0.5

    # Annualization factor: estimate periods per year from snapshot cadence
    total_days = (snapshots[-1].date - snapshots[0].date).days
    periods_per_year = len(returns) * 365.0 / total_days if total_days > 0 else 52.0

    # Sharpe ratio (annualized, rf=0)
    sharpe = None
    if std_ret > 0:
        sharpe = (mean_ret / std_ret) * (periods_per_year ** 0.5)

    # Sortino ratio (annualized, rf=0, downside deviation only)
    sortino = None
    downside_returns = [r for r in returns if r < 0]
    if downside_returns:
        downside_var = sum(r ** 2 for r in downside_returns) / len(returns)
        downside_dev = downside_var ** 0.5
        if downside_dev > 0:
            sortino = (mean_ret / downside_dev) * (periods_per_year ** 0.5)

    # Win rate: % of periods with positive return
    positive_periods = sum(1 for r in returns if r > 0)
    win_rate = (positive_periods / len(returns)) * 100.0

    # Profit factor: sum of gains / abs(sum of losses)
    profit_factor = None
    gains = sum(r for r in returns if r > 0)
    losses = abs(sum(r for r in returns if r < 0))
    if losses > 0:
        profit_factor = gains / losses

    return sharpe, sortino, win_rate, profit_factor
