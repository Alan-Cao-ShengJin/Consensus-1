"""Auto-valuation engine: forward PE z-score + peer comparison.

Two-signal approach:
  1. **Historical self-comparison**: Current forward PE vs own 5-year history.
     >1 SD above mean = expensive, >1 SD below mean = cheap.
  2. **Peer comparison**: Current forward PE vs sector/industry peer median.
     Trading at discount to peers = attractive, premium = harder to justify.

Output: valuation_gap_pct that feeds into zone classification
(BUY/HOLD/TRIM/FULL_EXIT in valuation_policy.py).

Positive gap = undervalued (buy signal), negative = overvalued (avoid/trim).
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

from sqlalchemy import select, and_
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

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

    # Forward PE
    pe_forward: Optional[float] = None

    # Historical self-comparison (z-score based)
    pe_forward_mean_5y: Optional[float] = None
    pe_forward_std_5y: Optional[float] = None
    pe_forward_zscore: Optional[float] = None  # >0 = above avg (expensive), <0 = below (cheap)

    # Peer comparison
    peer_median_pe: Optional[float] = None
    peer_premium_pct: Optional[float] = None  # +20 = 20% premium to peers, -10 = 10% discount
    peer_count: int = 0

    # Additional multiples (informational)
    pe_trailing: Optional[float] = None
    peg_ratio: Optional[float] = None
    ev_to_ebitda: Optional[float] = None

    # Composite valuation gap (positive = undervalued, negative = overvalued)
    valuation_gap_pct: Optional[float] = None
    valuation_signal: str = "neutral"  # cheap, fair, expensive, very_expensive
    confidence: float = 0.0  # 0-1, how much data we had
    method: str = "none"


@dataclass(frozen=True)
class ValuationConfig:
    """Configuration for the valuation engine."""
    # Weights for composite gap
    historical_weight: float = 0.6  # own history is primary signal
    peer_weight: float = 0.4        # peer comparison is secondary

    # Z-score thresholds
    zscore_cheap: float = -1.0      # 1 SD below mean = cheap
    zscore_expensive: float = 1.0   # 1 SD above mean = expensive
    zscore_very_expensive: float = 2.0  # 2 SD above = very expensive

    # Peer premium thresholds
    peer_discount_attractive: float = -15.0  # 15%+ discount to peers = attractive
    peer_premium_unattractive: float = 20.0  # 20%+ premium = unattractive

    # Gap scaling: how much to move valuation_gap_pct per unit of signal
    gap_per_zscore: float = 15.0    # each 1 SD = ~15% gap
    gap_per_peer_pct: float = 0.5   # each 1% peer premium/discount = 0.5% gap

    # Minimum data requirements
    min_historical_points: int = 8   # need at least 8 quarterly forward PE data points


DEFAULT_CONFIG = ValuationConfig()


# ---------------------------------------------------------------------------
# Core computation (pure functions, no DB access)
# ---------------------------------------------------------------------------

def compute_forward_pe(price: float, forward_eps: float) -> Optional[float]:
    """Compute forward PE from price and consensus EPS estimate."""
    if price <= 0 or forward_eps <= 0:
        return None
    pe = price / forward_eps
    # Sanity cap: PE > 200 or < 0 is noise
    if pe > 200:
        return None
    return round(pe, 2)


def compute_zscore(current: float, history: list[float]) -> Optional[tuple[float, float, float]]:
    """Compute z-score of current value vs history.

    Returns (zscore, mean, std) or None if insufficient data.
    """
    if len(history) < 4:
        return None

    # Filter outliers: drop values > 3x median (likely data errors)
    median = sorted(history)[len(history) // 2]
    filtered = [x for x in history if 0 < x < median * 3]
    if len(filtered) < 4:
        return None

    mean = sum(filtered) / len(filtered)
    variance = sum((x - mean) ** 2 for x in filtered) / len(filtered)
    std = math.sqrt(variance)

    if std < 0.01:  # near-zero std means all values are identical
        return (0.0, mean, std)

    zscore = (current - mean) / std
    return (round(zscore, 2), round(mean, 2), round(std, 2))


def compute_peer_premium(
    current_pe: float,
    peer_pes: list[float],
) -> Optional[tuple[float, float, int]]:
    """Compute premium/discount vs peer median forward PE.

    Returns (premium_pct, peer_median, peer_count) or None.
    Premium > 0 means trading above peers (expensive relative to peers).
    """
    valid = [p for p in peer_pes if p and 0 < p < 200]
    if len(valid) < 3:
        return None

    valid.sort()
    n = len(valid)
    median = valid[n // 2] if n % 2 else (valid[n // 2 - 1] + valid[n // 2]) / 2

    if median <= 0:
        return None

    premium_pct = ((current_pe - median) / median) * 100
    return (round(premium_pct, 1), round(median, 1), n)


def compute_valuation(
    ticker: str,
    as_of: date,
    current_price: float,
    forward_eps: Optional[float],
    historical_forward_pes: list[float],
    peer_forward_pes: list[float],
    config: ValuationConfig = DEFAULT_CONFIG,
) -> ValuationResult:
    """Compute valuation using historical z-score + peer comparison.

    Args:
        ticker: Stock ticker.
        as_of: Valuation date.
        current_price: Current stock price.
        forward_eps: Consensus forward EPS estimate.
        historical_forward_pes: List of historical forward PE values (5 years).
        peer_forward_pes: List of current forward PEs for sector/industry peers.
        config: Valuation thresholds.
    """
    result = ValuationResult(ticker=ticker, as_of=as_of)

    if current_price <= 0:
        return result

    # Compute current forward PE
    if forward_eps and forward_eps > 0:
        result.pe_forward = compute_forward_pe(current_price, forward_eps)

    if result.pe_forward is None:
        result.method = "insufficient_data"
        return result

    # --- Signal 1: Historical z-score ---
    hist_signal = 0.0
    hist_weight = 0.0

    if len(historical_forward_pes) >= config.min_historical_points:
        zresult = compute_zscore(result.pe_forward, historical_forward_pes)
        if zresult:
            zscore, mean, std = zresult
            result.pe_forward_zscore = zscore
            result.pe_forward_mean_5y = mean
            result.pe_forward_std_5y = std

            # Convert z-score to gap: negative zscore (cheap) → positive gap
            hist_signal = -zscore * config.gap_per_zscore
            hist_weight = config.historical_weight

    # --- Signal 2: Peer comparison ---
    peer_signal = 0.0
    peer_weight = 0.0

    if peer_forward_pes:
        peer_result = compute_peer_premium(result.pe_forward, peer_forward_pes)
        if peer_result:
            premium_pct, peer_median, peer_count = peer_result
            result.peer_premium_pct = premium_pct
            result.peer_median_pe = peer_median
            result.peer_count = peer_count

            # Convert peer premium to gap: premium (expensive) → negative gap
            peer_signal = -premium_pct * config.gap_per_peer_pct
            peer_weight = config.peer_weight

    # --- Composite gap ---
    total_weight = hist_weight + peer_weight
    if total_weight > 0:
        weighted_gap = (hist_signal * hist_weight + peer_signal * peer_weight) / total_weight
        result.valuation_gap_pct = round(weighted_gap, 1)
        result.confidence = min(1.0, total_weight / (config.historical_weight + config.peer_weight))

        # Classify signal
        if result.pe_forward_zscore is not None:
            z = result.pe_forward_zscore
            if z >= config.zscore_very_expensive:
                result.valuation_signal = "very_expensive"
            elif z >= config.zscore_expensive:
                result.valuation_signal = "expensive"
            elif z <= config.zscore_cheap:
                result.valuation_signal = "cheap"
            else:
                result.valuation_signal = "fair"
        else:
            # Fall back to peer signal only
            if result.peer_premium_pct and result.peer_premium_pct > config.peer_premium_unattractive:
                result.valuation_signal = "expensive"
            elif result.peer_premium_pct and result.peer_premium_pct < config.peer_discount_attractive:
                result.valuation_signal = "cheap"
            else:
                result.valuation_signal = "fair"

        methods = []
        if hist_weight > 0:
            methods.append("historical_zscore")
        if peer_weight > 0:
            methods.append("peer_comparison")
        result.method = "+".join(methods)

    return result


# ---------------------------------------------------------------------------
# DB-backed valuation: loads data from our tables
# ---------------------------------------------------------------------------

def run_valuation_for_ticker(
    session: Session,
    ticker: str,
    as_of_date: date,
    config: ValuationConfig = DEFAULT_CONFIG,
) -> Optional[ValuationResult]:
    """Run valuation for a single ticker using DB data.

    Loads forward EPS estimates, historical prices, and peer data from DB.
    Returns ValuationResult or None if insufficient data.
    """
    from models import (
        Company, EarningsEstimate, Price, Thesis,
        CompanyRelationship,
    )

    # 1. Get current price
    price_row = session.execute(
        select(Price.close).where(
            Price.ticker == ticker,
            Price.date <= as_of_date,
        ).order_by(Price.date.desc()).limit(1)
    ).scalar()

    if not price_row:
        return None
    current_price = float(price_row)

    # 2. Get forward EPS estimate (most recent for next fiscal period)
    estimate = session.execute(
        select(EarningsEstimate).where(
            EarningsEstimate.ticker == ticker,
            EarningsEstimate.estimated_eps.isnot(None),
        ).order_by(EarningsEstimate.fiscal_period.desc()).limit(1)
    ).scalars().first()

    forward_eps = estimate.estimated_eps if estimate else None

    # 3. Get historical forward PE data points
    # We reconstruct from historical prices + estimates at those times
    # For now, use a simpler approach: get all historical estimates and pair with prices
    historical_forward_pes = _build_historical_forward_pes(
        session, ticker, as_of_date, lookback_years=5,
    )

    # 4. Get peer forward PEs
    peer_forward_pes = _get_peer_forward_pes(session, ticker, as_of_date)

    # 5. Compute
    result = compute_valuation(
        ticker=ticker,
        as_of=as_of_date,
        current_price=current_price,
        forward_eps=forward_eps,
        historical_forward_pes=historical_forward_pes,
        peer_forward_pes=peer_forward_pes,
        config=config,
    )

    return result


def _build_historical_forward_pes(
    session: Session,
    ticker: str,
    as_of: date,
    lookback_years: int = 5,
) -> list[float]:
    """Build list of historical forward PE values from estimates + prices.

    For each historical estimate period, pair the estimated EPS with the
    stock price at that time to compute what the forward PE was.
    """
    from models import EarningsEstimate, Price
    from datetime import timedelta

    cutoff = date(as_of.year - lookback_years, as_of.month, as_of.day)

    estimates = session.execute(
        select(EarningsEstimate).where(
            EarningsEstimate.ticker == ticker,
            EarningsEstimate.estimated_eps.isnot(None),
            EarningsEstimate.estimated_eps > 0,
        ).order_by(EarningsEstimate.fiscal_period.asc())
    ).scalars().all()

    forward_pes = []
    for est in estimates:
        # Use the fiscal period start as the "when" for this estimate
        # Try to find a price near the estimate date
        est_date = est.fiscal_period  # this is a string like "2024-Q3"
        # Parse to approximate date
        approx_date = _fiscal_period_to_date(est_date)
        if approx_date and approx_date >= cutoff and approx_date <= as_of:
            # Find price closest to this date
            price_row = session.execute(
                select(Price.close).where(
                    Price.ticker == ticker,
                    Price.date <= approx_date,
                ).order_by(Price.date.desc()).limit(1)
            ).scalar()
            if price_row and est.estimated_eps > 0:
                pe = float(price_row) / est.estimated_eps
                if 0 < pe < 200:  # sanity filter
                    forward_pes.append(round(pe, 2))

    return forward_pes


def _fiscal_period_to_date(fiscal_period: str) -> Optional[date]:
    """Convert fiscal period string to approximate date.

    Handles formats like '2024-Q3', '2024Q3', 'FY2024', '2024-12-31'.
    """
    if not fiscal_period:
        return None
    try:
        # Try ISO date first
        return date.fromisoformat(fiscal_period)
    except (ValueError, TypeError):
        pass
    try:
        fp = fiscal_period.upper().replace(" ", "")
        if "Q1" in fp:
            year = int("".join(c for c in fp if c.isdigit())[:4])
            return date(year, 3, 31)
        elif "Q2" in fp:
            year = int("".join(c for c in fp if c.isdigit())[:4])
            return date(year, 6, 30)
        elif "Q3" in fp:
            year = int("".join(c for c in fp if c.isdigit())[:4])
            return date(year, 9, 30)
        elif "Q4" in fp or "FY" in fp:
            year = int("".join(c for c in fp if c.isdigit())[:4])
            return date(year, 12, 31)
    except (ValueError, IndexError):
        pass
    return None


def _get_peer_forward_pes(
    session: Session,
    ticker: str,
    as_of: date,
) -> list[float]:
    """Get forward PEs for sector/industry peers.

    Uses the company's sector + industry to find peers, then computes
    their current forward PE from latest estimate + price.
    """
    from models import Company, EarningsEstimate, Price

    # Get this company's sector/industry
    company = session.execute(
        select(Company).where(Company.ticker == ticker)
    ).scalars().first()

    if not company or (not company.industry and not company.sector):
        return []

    # Find peers in same industry (narrower = better comparison)
    peer_tickers = []
    if company.industry:
        peer_tickers = session.execute(
            select(Company.ticker).where(
                Company.industry == company.industry,
                Company.ticker != ticker,
            )
        ).scalars().all()

    # If too few industry peers, widen to sector
    if len(peer_tickers) < 5 and company.sector:
        peer_tickers = session.execute(
            select(Company.ticker).where(
                Company.sector == company.sector,
                Company.ticker != ticker,
            )
        ).scalars().all()

    peer_pes = []
    for pt in peer_tickers:
        # Get latest forward EPS
        est = session.execute(
            select(EarningsEstimate.estimated_eps).where(
                EarningsEstimate.ticker == pt,
                EarningsEstimate.estimated_eps.isnot(None),
                EarningsEstimate.estimated_eps > 0,
            ).order_by(EarningsEstimate.fiscal_period.desc()).limit(1)
        ).scalar()

        if not est:
            continue

        # Get latest price
        price = session.execute(
            select(Price.close).where(
                Price.ticker == pt,
                Price.date <= as_of,
            ).order_by(Price.date.desc()).limit(1)
        ).scalar()

        if price and est > 0:
            pe = float(price) / est
            if 0 < pe < 200:
                peer_pes.append(round(pe, 2))

    return peer_pes


def update_thesis_valuation(
    session: Session,
    ticker: str,
    as_of_date: date,
) -> Optional[ValuationResult]:
    """Compute valuation and write valuation_gap_pct to the active Thesis.

    Returns the ValuationResult or None.
    """
    from models import Thesis

    result = run_valuation_for_ticker(session, ticker, as_of_date)
    if not result or result.valuation_gap_pct is None:
        return result

    thesis = session.execute(
        select(Thesis).where(
            Thesis.company_ticker == ticker,
            Thesis.status_active == True,
        ).order_by(Thesis.updated_at.desc()).limit(1)
    ).scalars().first()

    if thesis:
        thesis.valuation_gap_pct = result.valuation_gap_pct
        session.flush()
        logger.info(
            "Valuation %s: fwd PE=%.1f, zscore=%.2f, peer_prem=%.1f%%, gap=%.1f%% [%s]",
            ticker,
            result.pe_forward or 0,
            result.pe_forward_zscore or 0,
            result.peer_premium_pct or 0,
            result.valuation_gap_pct,
            result.valuation_signal,
        )

    return result


# ---------------------------------------------------------------------------
# Legacy compatibility
# ---------------------------------------------------------------------------

def financials_from_fmp_metadata(
    metadata_list: list[dict],
) -> list[FinancialSnapshot]:
    """Convert FMP connector metadata dicts into FinancialSnapshot objects."""
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
