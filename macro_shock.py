"""Macro shock detector and conviction overlay system.

Monitors macro risk indicators for sudden adverse moves (VIX spike, oil shock,
credit spread blow-out, yield curve inversion). When a shock is detected,
computes sector-level conviction adjustments as an OVERLAY — fundamental
conviction scores are never modified.

Design principle: macro shocks are a temporary filter. When VIX normalizes,
the overlay vanishes and tickers return to their fundamental scores without
needing to "earn back" lost conviction. The portfolio decision engine reads
the overlay at decision time and applies it on top of the fundamental score.

Usage:
    from macro_shock import detect_shocks, compute_macro_overlay

    shocks = detect_shocks(session)
    overlay = compute_macro_overlay(session, shocks)
    # overlay = {"NVDA": -8.4, "XOM": 0.0, "CCL": -13.0, ...}
    # At decision time: effective_conviction = fundamental + overlay[ticker]
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import Enum
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from models import Company, Price, Thesis

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shock types and severity
# ---------------------------------------------------------------------------

class ShockType(str, Enum):
    VIX_SPIKE = "vix_spike"
    OIL_SPIKE = "oil_spike"
    OIL_CRASH = "oil_crash"
    CREDIT_STRESS = "credit_stress"
    RATE_SPIKE = "rate_spike"
    DOLLAR_SPIKE = "dollar_spike"
    BROAD_SELLOFF = "broad_selloff"


class ShockSeverity(str, Enum):
    MODERATE = "moderate"   # notable but manageable
    SEVERE = "severe"       # significant market stress
    EXTREME = "extreme"     # crisis-level


@dataclass
class MacroShock:
    """A detected macro shock event."""
    shock_type: ShockType
    severity: ShockSeverity
    indicator: str           # e.g., "^VIX", "MACRO:OIL"
    current_value: float
    prior_value: float       # value N days ago for comparison
    change_pct: float        # percentage change
    description: str
    detected_at: date


# ---------------------------------------------------------------------------
# Detection thresholds
# ---------------------------------------------------------------------------

# VIX thresholds (level-based + spike-based)
VIX_MODERATE = 25.0       # VIX above 25 = elevated fear
VIX_SEVERE = 35.0         # VIX above 35 = significant stress
VIX_EXTREME = 45.0        # VIX above 45 = crisis
VIX_SPIKE_PCT = 30.0      # 30% VIX jump in 5 days = shock regardless of level

# Oil thresholds (% change over 5 trading days)
OIL_SPIKE_MODERATE = 15.0    # +15% in a week
OIL_SPIKE_SEVERE = 25.0      # +25% in a week (geopolitical event)
OIL_CRASH_MODERATE = -15.0   # -15% in a week (demand destruction)
OIL_CRASH_SEVERE = -25.0     # -25% in a week

# Credit spread thresholds (LQD/HYG ratio change — rising = stress)
CREDIT_MODERATE_CHANGE = 2.0    # 2% widening in spread proxy over 10 days
CREDIT_SEVERE_CHANGE = 4.0      # 4% widening

# 10Y yield spike (absolute change in basis points over 5 days)
RATE_MODERATE_BPS = 30         # 30bps move in a week
RATE_SEVERE_BPS = 50           # 50bps move in a week

# Dollar (DXY % change over 5 days)
DXY_MODERATE_PCT = 3.0
DXY_SEVERE_PCT = 5.0

# Benchmark (SPY % change over 5 days)
BROAD_SELLOFF_MODERATE = -5.0   # -5% in a week
BROAD_SELLOFF_SEVERE = -8.0     # -8% in a week
BROAD_SELLOFF_EXTREME = -12.0   # -12% in a week (crash)


# ---------------------------------------------------------------------------
# Sector sensitivity matrix
# ---------------------------------------------------------------------------
# Maps (ShockType → sector → adjustment multiplier)
# Multiplier is applied to the base adjustment for that severity level.
# 0.0 = immune, 1.0 = full impact, >1.0 = amplified impact, <0 = benefits

SECTOR_SENSITIVITY: dict[ShockType, dict[str, float]] = {
    ShockType.VIX_SPIKE: {
        "Information Technology": 1.2,
        "Communication Services": 1.1,
        "Consumer Discretionary": 1.3,
        "Financials": 1.1,
        "Health Care": 0.7,
        "Consumer Staples": 0.5,
        "Utilities": 0.4,
        "Real Estate": 0.9,
        "Industrials": 1.0,
        "Materials": 1.0,
        "Energy": 0.8,
    },
    ShockType.OIL_SPIKE: {
        "Energy": -0.5,
        "Industrials": 1.2,
        "Consumer Discretionary": 1.3,
        "Consumer Staples": 0.8,
        "Materials": 0.9,
        "Information Technology": 0.4,
        "Communication Services": 0.3,
        "Health Care": 0.3,
        "Financials": 0.5,
        "Utilities": 0.7,
        "Real Estate": 0.4,
    },
    ShockType.OIL_CRASH: {
        "Energy": 1.5,
        "Industrials": -0.3,
        "Consumer Discretionary": -0.2,
        "Consumer Staples": 0.0,
        "Materials": 0.8,
        "Information Technology": 0.2,
        "Communication Services": 0.1,
        "Health Care": 0.1,
        "Financials": 0.6,
        "Utilities": -0.2,
        "Real Estate": 0.1,
    },
    ShockType.CREDIT_STRESS: {
        "Financials": 1.5,
        "Real Estate": 1.4,
        "Consumer Discretionary": 1.1,
        "Industrials": 1.0,
        "Information Technology": 0.7,
        "Communication Services": 0.7,
        "Materials": 0.9,
        "Health Care": 0.5,
        "Consumer Staples": 0.4,
        "Utilities": 0.8,
        "Energy": 0.8,
    },
    ShockType.RATE_SPIKE: {
        "Information Technology": 1.3,
        "Communication Services": 1.2,
        "Consumer Discretionary": 1.1,
        "Real Estate": 1.5,
        "Utilities": 1.3,
        "Financials": 0.3,
        "Health Care": 0.6,
        "Consumer Staples": 0.5,
        "Industrials": 0.7,
        "Materials": 0.7,
        "Energy": 0.4,
    },
    ShockType.DOLLAR_SPIKE: {
        "Information Technology": 1.2,
        "Materials": 1.3,
        "Industrials": 1.0,
        "Consumer Staples": 0.8,
        "Health Care": 0.7,
        "Consumer Discretionary": 0.8,
        "Communication Services": 0.9,
        "Energy": 0.6,
        "Financials": 0.5,
        "Utilities": 0.2,
        "Real Estate": 0.2,
    },
    ShockType.BROAD_SELLOFF: {
        "Information Technology": 1.2,
        "Communication Services": 1.1,
        "Consumer Discretionary": 1.3,
        "Financials": 1.1,
        "Industrials": 1.0,
        "Materials": 1.0,
        "Energy": 1.0,
        "Health Care": 0.8,
        "Consumer Staples": 0.6,
        "Utilities": 0.5,
        "Real Estate": 0.9,
    },
}

DEFAULT_SECTOR_SENSITIVITY = 0.7

# Base conviction adjustment per severity level (points on 0-100 scale)
BASE_ADJUSTMENT: dict[ShockSeverity, float] = {
    ShockSeverity.MODERATE: 3.0,
    ShockSeverity.SEVERE: 7.0,
    ShockSeverity.EXTREME: 12.0,
}

# Maximum single-shock adjustment (even with high multiplier)
MAX_SINGLE_SHOCK_ADJUSTMENT = 15.0


# ---------------------------------------------------------------------------
# Shock detection
# ---------------------------------------------------------------------------

def _get_recent_prices(
    session: Session,
    ticker: str,
    lookback_days: int = 15,
) -> list[tuple[date, float]]:
    """Get recent closing prices for a macro indicator, sorted by date."""
    cutoff = date.today() - timedelta(days=lookback_days)
    rows = session.execute(
        select(Price.date, Price.close)
        .where(Price.ticker == ticker, Price.date >= cutoff)
        .order_by(Price.date.asc())
    ).all()
    return [(r[0], r[1]) for r in rows if r[1] is not None]


def _pct_change(current: float, prior: float) -> float:
    if prior == 0:
        return 0.0
    return ((current - prior) / abs(prior)) * 100.0


def detect_shocks(session: Session) -> list[MacroShock]:
    """Scan all macro indicators for shock conditions.

    Returns list of detected shocks (may be empty = all clear).
    """
    today = date.today()
    shocks: list[MacroShock] = []

    # --- VIX ---
    vix_prices = _get_recent_prices(session, "^VIX")
    if vix_prices:
        current_vix = vix_prices[-1][1]
        prior_vix = vix_prices[0][1] if len(vix_prices) > 1 else current_vix
        vix_change = _pct_change(current_vix, prior_vix) if len(vix_prices) > 1 else 0

        if current_vix >= VIX_EXTREME:
            shocks.append(MacroShock(
                ShockType.VIX_SPIKE, ShockSeverity.EXTREME, "^VIX",
                current_vix, prior_vix, vix_change,
                f"VIX at {current_vix:.1f} — extreme fear", today))
        elif current_vix >= VIX_SEVERE:
            shocks.append(MacroShock(
                ShockType.VIX_SPIKE, ShockSeverity.SEVERE, "^VIX",
                current_vix, prior_vix, vix_change,
                f"VIX at {current_vix:.1f} — severe stress", today))
        elif current_vix >= VIX_MODERATE:
            shocks.append(MacroShock(
                ShockType.VIX_SPIKE, ShockSeverity.MODERATE, "^VIX",
                current_vix, prior_vix, vix_change,
                f"VIX at {current_vix:.1f} — elevated fear", today))
        elif len(vix_prices) >= 5:
            p = vix_prices[-5][1]
            ch = _pct_change(current_vix, p)
            if ch >= VIX_SPIKE_PCT:
                shocks.append(MacroShock(
                    ShockType.VIX_SPIKE, ShockSeverity.MODERATE, "^VIX",
                    current_vix, p, ch,
                    f"VIX spiked {ch:.0f}% in 5 days ({p:.1f} → {current_vix:.1f})", today))

    # --- Oil ---
    oil_prices = _get_recent_prices(session, "MACRO:OIL")
    if len(oil_prices) >= 5:
        cur = oil_prices[-1][1]
        pri = oil_prices[-5][1]
        ch = _pct_change(cur, pri)
        if ch >= OIL_SPIKE_SEVERE:
            shocks.append(MacroShock(ShockType.OIL_SPIKE, ShockSeverity.SEVERE,
                "MACRO:OIL", cur, pri, ch,
                f"Oil spiked {ch:.0f}% in 5 days (${pri:.0f} → ${cur:.0f})", today))
        elif ch >= OIL_SPIKE_MODERATE:
            shocks.append(MacroShock(ShockType.OIL_SPIKE, ShockSeverity.MODERATE,
                "MACRO:OIL", cur, pri, ch,
                f"Oil up {ch:.0f}% in 5 days (${pri:.0f} → ${cur:.0f})", today))
        elif ch <= OIL_CRASH_SEVERE:
            shocks.append(MacroShock(ShockType.OIL_CRASH, ShockSeverity.SEVERE,
                "MACRO:OIL", cur, pri, ch,
                f"Oil crashed {ch:.0f}% in 5 days (${pri:.0f} → ${cur:.0f})", today))
        elif ch <= OIL_CRASH_MODERATE:
            shocks.append(MacroShock(ShockType.OIL_CRASH, ShockSeverity.MODERATE,
                "MACRO:OIL", cur, pri, ch,
                f"Oil down {ch:.0f}% in 5 days (${pri:.0f} → ${cur:.0f})", today))

    # --- Credit spread ---
    credit_prices = _get_recent_prices(session, "MACRO:CREDIT_SPREAD", lookback_days=20)
    if len(credit_prices) >= 10:
        cur = credit_prices[-1][1]
        pri = credit_prices[-10][1]
        ch = cur - pri
        if ch >= CREDIT_SEVERE_CHANGE:
            shocks.append(MacroShock(ShockType.CREDIT_STRESS, ShockSeverity.SEVERE,
                "MACRO:CREDIT_SPREAD", cur, pri, ch,
                f"Credit spread widened {ch:.1f}pp in 10 days", today))
        elif ch >= CREDIT_MODERATE_CHANGE:
            shocks.append(MacroShock(ShockType.CREDIT_STRESS, ShockSeverity.MODERATE,
                "MACRO:CREDIT_SPREAD", cur, pri, ch,
                f"Credit spread widened {ch:.1f}pp in 10 days", today))

    # --- 10Y rate ---
    rate_prices = _get_recent_prices(session, "MACRO:DGS10")
    if len(rate_prices) >= 5:
        cur = rate_prices[-1][1]
        pri = rate_prices[-5][1]
        ch_bps = (cur - pri) * 100
        if abs(ch_bps) >= RATE_SEVERE_BPS:
            shocks.append(MacroShock(ShockType.RATE_SPIKE, ShockSeverity.SEVERE,
                "MACRO:DGS10", cur, pri, ch_bps,
                f"10Y yield moved {ch_bps:+.0f}bps in 5 days ({pri:.2f}% → {cur:.2f}%)", today))
        elif abs(ch_bps) >= RATE_MODERATE_BPS:
            shocks.append(MacroShock(ShockType.RATE_SPIKE, ShockSeverity.MODERATE,
                "MACRO:DGS10", cur, pri, ch_bps,
                f"10Y yield moved {ch_bps:+.0f}bps in 5 days ({pri:.2f}% → {cur:.2f}%)", today))

    # --- DXY ---
    dxy_prices = _get_recent_prices(session, "MACRO:DXY")
    if len(dxy_prices) >= 5:
        cur = dxy_prices[-1][1]
        pri = dxy_prices[-5][1]
        ch = _pct_change(cur, pri)
        if abs(ch) >= DXY_SEVERE_PCT:
            shocks.append(MacroShock(ShockType.DOLLAR_SPIKE, ShockSeverity.SEVERE,
                "MACRO:DXY", cur, pri, ch,
                f"Dollar moved {ch:+.1f}% in 5 days (DXY {pri:.1f} → {cur:.1f})", today))
        elif abs(ch) >= DXY_MODERATE_PCT:
            shocks.append(MacroShock(ShockType.DOLLAR_SPIKE, ShockSeverity.MODERATE,
                "MACRO:DXY", cur, pri, ch,
                f"Dollar moved {ch:+.1f}% in 5 days (DXY {pri:.1f} → {cur:.1f})", today))

    # --- Broad selloff (SPY) ---
    spy_prices = _get_recent_prices(session, "SPY")
    if len(spy_prices) >= 5:
        cur = spy_prices[-1][1]
        pri = spy_prices[-5][1]
        ch = _pct_change(cur, pri)
        if ch <= BROAD_SELLOFF_EXTREME:
            shocks.append(MacroShock(ShockType.BROAD_SELLOFF, ShockSeverity.EXTREME,
                "SPY", cur, pri, ch, f"S&P 500 crashed {ch:.1f}% in 5 days", today))
        elif ch <= BROAD_SELLOFF_SEVERE:
            shocks.append(MacroShock(ShockType.BROAD_SELLOFF, ShockSeverity.SEVERE,
                "SPY", cur, pri, ch, f"S&P 500 down {ch:.1f}% in 5 days", today))
        elif ch <= BROAD_SELLOFF_MODERATE:
            shocks.append(MacroShock(ShockType.BROAD_SELLOFF, ShockSeverity.MODERATE,
                "SPY", cur, pri, ch, f"S&P 500 down {ch:.1f}% in 5 days", today))

    if shocks:
        logger.warning("MACRO SHOCK DETECTED: %d shocks — %s",
                       len(shocks), "; ".join(s.description for s in shocks))
    else:
        logger.info("Macro scan: no shocks detected")

    return shocks


# ---------------------------------------------------------------------------
# Macro overlay computation (pure — no DB writes)
# ---------------------------------------------------------------------------

@dataclass
class MacroOverlay:
    """Macro adjustment overlay for portfolio decisions.

    This is a TEMPORARY filter on top of fundamental conviction scores.
    When shocks clear, the overlay resets to zero and scores return
    to their fundamental level — no "earning back" required.
    """
    shocks: list[MacroShock]
    adjustments: dict[str, float] = field(default_factory=dict)  # ticker → negative adjustment
    explanations: dict[str, list[str]] = field(default_factory=dict)

    @property
    def active(self) -> bool:
        return len(self.shocks) > 0

    def effective_conviction(self, ticker: str, fundamental_score: float) -> float:
        """Compute effective conviction = fundamental + macro overlay.

        The result is what the portfolio decision engine should use.
        Fundamental score in the thesis table is never modified.
        """
        adj = self.adjustments.get(ticker, 0.0)
        return max(fundamental_score + adj, 0.0)

    def summary(self) -> str:
        if not self.shocks:
            return "No macro shocks — overlay inactive"
        affected = sum(1 for v in self.adjustments.values() if v < -0.1)
        avg_adj = (sum(self.adjustments.values()) / len(self.adjustments)) if self.adjustments else 0
        return (
            f"{len(self.shocks)} shocks active, {affected} tickers affected, "
            f"avg adjustment: {avg_adj:.1f}pts"
        )


def compute_ticker_adjustment(
    sector: str,
    beta: Optional[float],
    shocks: list[MacroShock],
) -> tuple[float, list[str]]:
    """Compute macro overlay adjustment for one ticker.

    Returns (adjustment_points, [explanation_strings]).
    Adjustment is negative (penalty) or zero. Never positive —
    we don't auto-boost conviction on positive macro signals.
    """
    total_adj = 0.0
    explanations: list[str] = []
    beta_mult = min(max(beta or 1.0, 0.5), 2.0)

    for shock in shocks:
        base = BASE_ADJUSTMENT[shock.severity]
        sector_map = SECTOR_SENSITIVITY.get(shock.shock_type, {})
        sector_mult = sector_map.get(sector, DEFAULT_SECTOR_SENSITIVITY)

        if sector_mult <= 0:
            explanations.append(
                f"{shock.shock_type.value}: {sector} benefits — no penalty"
            )
            continue

        adj = base * sector_mult * beta_mult
        adj = min(adj, MAX_SINGLE_SHOCK_ADJUSTMENT)
        total_adj += adj
        explanations.append(
            f"{shock.shock_type.value} ({shock.severity.value}): "
            f"-{adj:.1f}pts (base={base:.0f} × sector={sector_mult:.1f} × beta={beta_mult:.1f})"
        )

    return -total_adj, explanations  # return as negative


def compute_macro_overlay(
    session: Session,
    shocks: list[MacroShock],
) -> MacroOverlay:
    """Compute the macro overlay for all active tickers.

    This is a pure read — no DB writes, no thesis modifications.
    Call on each pipeline run or portfolio review. When shocks list
    is empty, returns an inactive overlay (all adjustments = 0).

    The overlay is ephemeral: recomputed fresh each time from current
    macro data. When conditions normalize, adjustments disappear.
    """
    overlay = MacroOverlay(shocks=shocks)

    if not shocks:
        return overlay

    # Load all active theses
    theses = session.scalars(
        select(Thesis).where(Thesis.status_active == True)
    ).all()
    if not theses:
        return overlay

    # Build company lookup
    tickers = [t.company_ticker for t in theses]
    companies = session.scalars(
        select(Company).where(Company.ticker.in_(tickers))
    ).all()
    company_map = {c.ticker: c for c in companies}

    for thesis in theses:
        company = company_map.get(thesis.company_ticker)
        sector = (company.sector if company else None) or "Unknown"
        beta = getattr(company, 'beta', None)

        adj, explanations = compute_ticker_adjustment(sector, beta, shocks)

        if adj < -0.1:  # only store meaningful adjustments
            overlay.adjustments[thesis.company_ticker] = adj
            overlay.explanations[thesis.company_ticker] = explanations

    if overlay.adjustments:
        worst = min(overlay.adjustments.values())
        worst_ticker = [t for t, v in overlay.adjustments.items() if v == worst][0]
        logger.warning(
            "Macro overlay: %d tickers penalized, worst=%s (%.1f pts). %s",
            len(overlay.adjustments), worst_ticker, worst, overlay.summary(),
        )

    return overlay


# ---------------------------------------------------------------------------
# Convenience: detect + compute in one call
# ---------------------------------------------------------------------------

def run_macro_shock_scan(session: Session) -> MacroOverlay:
    """Full macro shock pipeline: detect shocks → compute overlay.

    Returns a MacroOverlay object that the decision engine uses
    to adjust conviction scores at decision time. No DB writes.
    """
    shocks = detect_shocks(session)
    return compute_macro_overlay(session, shocks)
