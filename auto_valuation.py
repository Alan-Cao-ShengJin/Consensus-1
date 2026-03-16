"""Auto-valuation engine: compute valuation metrics from financial data.

Problem: valuation_gap_pct is NULL for every thesis — the system has zero
concept of whether a stock is cheap or expensive. It buys at all-time highs
and holds through crashes because the zone is always HOLD.

Solution: Compute PE, PEG, EV/Revenue, and price-to-FCF from FMP financial
data (already ingested). Compare current multiples against historical ranges
and sector medians to estimate relative valuation.

Output: a valuation_gap_pct that feeds into the existing zone classification
(BUY/HOLD/TRIM/FULL_EXIT zones in valuation_policy.py).

All functions are pure: operate on preloaded data, no DB or API access.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional


@dataclass
class FinancialSnapshot:
    """Key financial metrics for one period (quarter or annual)."""
    period_end: date
    revenue: Optional[float] = None
    net_income: Optional[float] = None
    eps_diluted: Optional[float] = None
    free_cash_flow: Optional[float] = None
    ebitda: Optional[float] = None
    total_debt: Optional[float] = None
    cash_and_equivalents: Optional[float] = None
    shares_outstanding: Optional[float] = None
    revenue_growth_pct: Optional[float] = None  # YoY


@dataclass
class ValuationResult:
    """Computed valuation metrics for a stock."""
    ticker: str
    as_of: date

    # Absolute multiples
    pe_ratio: Optional[float] = None
    pe_forward: Optional[float] = None  # using estimated EPS
    peg_ratio: Optional[float] = None   # PE / earnings growth
    ev_to_revenue: Optional[float] = None
    price_to_fcf: Optional[float] = None
    ev_to_ebitda: Optional[float] = None

    # Historical comparison
    pe_percentile: Optional[float] = None      # 0-100, where current PE sits in 2yr range
    ev_rev_percentile: Optional[float] = None

    # Composite valuation gap (positive = undervalued, negative = overvalued)
    valuation_gap_pct: Optional[float] = None
    valuation_method: str = "none"  # which method drove the gap
    confidence: float = 0.0        # 0-1, how much data we had


@dataclass(frozen=True)
class ValuationConfig:
    """Thresholds for valuation classification."""
    enabled: bool = True

    # PE-based valuation
    pe_fair_multiple: float = 25.0      # fair PE for growth tech stocks
    pe_cheap_discount: float = 0.7      # below 70% of fair = cheap
    pe_expensive_premium: float = 1.5   # above 150% of fair = expensive

    # Revenue multiple thresholds (EV/Revenue)
    ev_rev_fair: float = 8.0
    ev_rev_cheap: float = 5.0
    ev_rev_expensive: float = 15.0

    # PEG ratio thresholds
    peg_fair: float = 1.5
    peg_cheap: float = 1.0
    peg_expensive: float = 2.5

    # How much to weight each signal in composite
    pe_weight: float = 0.4
    peg_weight: float = 0.3
    ev_rev_weight: float = 0.2
    historical_weight: float = 0.1


DISABLED_VALUATION_CONFIG = ValuationConfig(enabled=False)
DEFAULT_VALUATION_CONFIG = ValuationConfig(enabled=True)


def compute_pe_ratio(
    current_price: float,
    ttm_eps: float,
) -> Optional[float]:
    """Compute trailing PE ratio."""
    if current_price <= 0 or ttm_eps <= 0:
        return None
    return current_price / ttm_eps


def compute_ev_to_revenue(
    market_cap: float,
    total_debt: float,
    cash: float,
    ttm_revenue: float,
) -> Optional[float]:
    """Compute enterprise value to revenue."""
    if ttm_revenue <= 0:
        return None
    ev = market_cap + total_debt - cash
    if ev <= 0:
        return None
    return ev / ttm_revenue


def compute_peg_ratio(
    pe_ratio: float,
    earnings_growth_pct: float,
) -> Optional[float]:
    """Compute PEG ratio (PE / earnings growth rate)."""
    if pe_ratio <= 0 or earnings_growth_pct <= 0:
        return None
    return pe_ratio / earnings_growth_pct


def compute_price_to_fcf(
    market_cap: float,
    ttm_fcf: float,
) -> Optional[float]:
    """Compute price to free cash flow."""
    if market_cap <= 0 or ttm_fcf <= 0:
        return None
    return market_cap / ttm_fcf


def _compute_percentile(current: float, history: list[float]) -> Optional[float]:
    """Where does current value sit in historical range? 0=cheapest, 100=most expensive."""
    if not history or len(history) < 4:
        return None
    sorted_hist = sorted(history)
    count_below = sum(1 for h in sorted_hist if h < current)
    return (count_below / len(sorted_hist)) * 100.0


def _signal_to_gap(
    current: float,
    fair: float,
    cheap: float,
    expensive: float,
) -> float:
    """Convert a valuation multiple into a gap percentage.

    Returns positive for undervalued, negative for overvalued.
    """
    if current <= 0 or fair <= 0:
        return 0.0

    if current <= cheap:
        # Very cheap: large positive gap
        return ((fair - current) / fair) * 100.0
    elif current >= expensive:
        # Very expensive: large negative gap
        return ((fair - current) / fair) * 100.0
    else:
        # Linear interpolation between cheap and expensive
        return ((fair - current) / fair) * 100.0


def compute_valuation(
    ticker: str,
    as_of: date,
    current_price: float,
    financials: list[FinancialSnapshot],
    estimated_eps: Optional[float] = None,
    shares_outstanding: Optional[float] = None,
    historical_pe_ratios: Optional[list[float]] = None,
    config: ValuationConfig = DEFAULT_VALUATION_CONFIG,
) -> ValuationResult:
    """Compute composite valuation for a stock.

    Args:
        ticker: Stock ticker.
        as_of: Valuation date.
        current_price: Current stock price.
        financials: List of FinancialSnapshot objects (most recent first).
        estimated_eps: Forward EPS estimate (from analyst consensus).
        shares_outstanding: Diluted shares outstanding.
        historical_pe_ratios: Historical PE values for percentile ranking.
        config: Valuation thresholds.

    Returns:
        ValuationResult with computed metrics and composite gap.
    """
    result = ValuationResult(ticker=ticker, as_of=as_of)

    if not config.enabled or not financials or current_price <= 0:
        return result

    # Compute TTM metrics from most recent 4 quarters
    recent = financials[:4]
    ttm_eps = sum(f.eps_diluted or 0 for f in recent)
    ttm_revenue = sum(f.revenue or 0 for f in recent)
    ttm_fcf = sum(f.free_cash_flow or 0 for f in recent)
    ttm_ebitda = sum(f.ebitda or 0 for f in recent)

    # Use shares from most recent financial or parameter
    shares = shares_outstanding
    if not shares and recent[0].shares_outstanding:
        shares = recent[0].shares_outstanding
    if not shares:
        shares = 1e9  # rough fallback for mega-cap

    market_cap = current_price * shares

    # Get debt/cash from most recent quarter
    total_debt = recent[0].total_debt or 0
    cash = recent[0].cash_and_equivalents or 0

    # --- Compute individual multiples ---
    signals_used = 0
    gap_components: list[tuple[float, float]] = []  # (gap, weight)

    # PE ratio
    result.pe_ratio = compute_pe_ratio(current_price, ttm_eps)
    if result.pe_ratio is not None:
        gap = _signal_to_gap(
            result.pe_ratio, config.pe_fair_multiple,
            config.pe_fair_multiple * config.pe_cheap_discount,
            config.pe_fair_multiple * config.pe_expensive_premium,
        )
        gap_components.append((gap, config.pe_weight))
        signals_used += 1

    # Forward PE
    if estimated_eps and estimated_eps > 0:
        result.pe_forward = current_price / estimated_eps

    # PEG ratio
    earnings_growth = None
    if len(financials) >= 8:
        # Compare TTM EPS to prior-year TTM EPS
        prior_ttm_eps = sum(f.eps_diluted or 0 for f in financials[4:8])
        if prior_ttm_eps > 0 and ttm_eps > 0:
            earnings_growth = ((ttm_eps - prior_ttm_eps) / prior_ttm_eps) * 100
    # Fallback: use revenue growth as proxy
    if earnings_growth is None and recent[0].revenue_growth_pct is not None:
        earnings_growth = recent[0].revenue_growth_pct

    if result.pe_ratio and earnings_growth and earnings_growth > 0:
        result.peg_ratio = compute_peg_ratio(result.pe_ratio, earnings_growth)
        if result.peg_ratio is not None:
            gap = _signal_to_gap(
                result.peg_ratio, config.peg_fair,
                config.peg_cheap, config.peg_expensive,
            )
            gap_components.append((gap, config.peg_weight))
            signals_used += 1

    # EV/Revenue
    if ttm_revenue > 0:
        result.ev_to_revenue = compute_ev_to_revenue(
            market_cap, total_debt, cash, ttm_revenue,
        )
        if result.ev_to_revenue is not None:
            gap = _signal_to_gap(
                result.ev_to_revenue, config.ev_rev_fair,
                config.ev_rev_cheap, config.ev_rev_expensive,
            )
            gap_components.append((gap, config.ev_rev_weight))
            signals_used += 1

    # Price/FCF
    if ttm_fcf > 0:
        result.price_to_fcf = compute_price_to_fcf(market_cap, ttm_fcf)

    # EV/EBITDA
    if ttm_ebitda > 0:
        ev = market_cap + total_debt - cash
        if ev > 0:
            result.ev_to_ebitda = ev / ttm_ebitda

    # Historical PE percentile
    if historical_pe_ratios and result.pe_ratio:
        result.pe_percentile = _compute_percentile(result.pe_ratio, historical_pe_ratios)
        if result.pe_percentile is not None:
            # Percentile-based gap: 50th percentile = fair, below = cheap, above = expensive
            hist_gap = (50.0 - result.pe_percentile) * 0.6  # scale factor
            gap_components.append((hist_gap, config.historical_weight))
            signals_used += 1

    # --- Composite gap ---
    if gap_components:
        total_weight = sum(w for _, w in gap_components)
        if total_weight > 0:
            weighted_gap = sum(g * w for g, w in gap_components) / total_weight
            result.valuation_gap_pct = round(weighted_gap, 2)
            result.confidence = min(1.0, signals_used / 4.0)
            result.valuation_method = "composite"

    return result


def financials_from_fmp_metadata(
    metadata_list: list[dict],
) -> list[FinancialSnapshot]:
    """Convert FMP connector metadata dicts into FinancialSnapshot objects.

    The FMP financials connector stores key metrics in DocumentPayload.metadata.
    This function extracts them for valuation computation.
    """
    snapshots = []
    for meta in metadata_list:
        if not meta:
            continue
        try:
            period_end = date.fromisoformat(meta["period_end"]) if "period_end" in meta else date(2024, 1, 1)
        except (ValueError, TypeError):
            period_end = date(2024, 1, 1)

        snapshots.append(FinancialSnapshot(
            period_end=period_end,
            revenue=meta.get("revenue"),
            net_income=meta.get("net_income"),
            eps_diluted=meta.get("eps"),
            free_cash_flow=meta.get("free_cash_flow"),
            ebitda=meta.get("ebitda"),
            total_debt=meta.get("total_debt"),
            cash_and_equivalents=meta.get("cash_and_equivalents"),
            shares_outstanding=meta.get("shares_outstanding"),
            revenue_growth_pct=meta.get("revenue_growth_pct"),
        ))
    return snapshots
