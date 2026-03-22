"""Prior expectation context: enrich thesis updates with what we already knew.

Before the thesis update LLM scores new claims, this module builds a context
block that compares each claim against:
  1. Prior guidance claims (what management previously said)
  2. Consensus estimates (what the Street expected)
  3. Same-type prior claims (last known data point for this metric)
  4. Conviction trajectory (recent thesis momentum)

The output is a formatted string injected into the thesis update LLM prompt
alongside the existing memory context. No DB writes — read-only.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from models import (
    Claim,
    ClaimCompanyLink,
    ClaimType,
    EarningsEstimate,
    ThesisStateHistory,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Retrieval helpers
# ---------------------------------------------------------------------------

_GUIDANCE_LOOKBACK_DAYS = 180
_SAME_TYPE_LOOKBACK_DAYS = 90
_GUIDANCE_LIMIT = 5
_SAME_TYPE_LIMIT = 3
_ESTIMATES_LIMIT = 2
_TRAJECTORY_LIMIT = 5


def _get_recent_guidance(
    session: Session,
    ticker: str,
    exclude_ids: set[int],
    lookback_days: int = _GUIDANCE_LOOKBACK_DAYS,
) -> list[Claim]:
    """Fetch recent guidance claims for this ticker."""
    cutoff = datetime.utcnow() - timedelta(days=lookback_days)
    stmt = (
        select(Claim)
        .join(ClaimCompanyLink, ClaimCompanyLink.claim_id == Claim.id)
        .where(
            ClaimCompanyLink.company_ticker == ticker,
            Claim.claim_type == ClaimType.GUIDANCE,
            Claim.published_at >= cutoff,
        )
    )
    if exclude_ids:
        stmt = stmt.where(Claim.id.notin_(exclude_ids))
    stmt = stmt.order_by(Claim.published_at.desc().nulls_last(), Claim.id.desc()).limit(_GUIDANCE_LIMIT)
    return list(session.scalars(stmt).all())


def _get_consensus_estimates(
    session: Session,
    ticker: str,
    reference_date: datetime,
) -> list[EarningsEstimate]:
    """Fetch the 2 most recent estimate rows for this ticker."""
    stmt = (
        select(EarningsEstimate)
        .where(
            EarningsEstimate.ticker == ticker,
            EarningsEstimate.fiscal_date <= reference_date.date() + timedelta(days=7),
        )
        .order_by(EarningsEstimate.fiscal_date.desc())
        .limit(_ESTIMATES_LIMIT)
    )
    return list(session.scalars(stmt).all())


def _get_same_type_priors(
    session: Session,
    ticker: str,
    claim_types: set[str],
    exclude_ids: set[int],
    lookback_days: int = _SAME_TYPE_LOOKBACK_DAYS,
) -> dict[str, list[Claim]]:
    """For each claim type in the new batch, find recent prior claims of that type."""
    cutoff = datetime.utcnow() - timedelta(days=lookback_days)
    result: dict[str, list[Claim]] = {}

    for ct in claim_types:
        try:
            ct_enum = ClaimType(ct)
        except ValueError:
            continue

        stmt = (
            select(Claim)
            .join(ClaimCompanyLink, ClaimCompanyLink.claim_id == Claim.id)
            .where(
                ClaimCompanyLink.company_ticker == ticker,
                Claim.claim_type == ct_enum,
                Claim.published_at >= cutoff,
            )
        )
        if exclude_ids:
            stmt = stmt.where(Claim.id.notin_(exclude_ids))
        stmt = stmt.order_by(Claim.published_at.desc().nulls_last(), Claim.id.desc()).limit(_SAME_TYPE_LIMIT)
        priors = list(session.scalars(stmt).all())
        if priors:
            result[ct] = priors

    return result


def _get_conviction_trajectory(
    session: Session,
    thesis_id: int,
) -> list[tuple[float, str]]:
    """Return recent (conviction_score, state) pairs, newest first."""
    stmt = (
        select(ThesisStateHistory)
        .where(ThesisStateHistory.thesis_id == thesis_id)
        .order_by(ThesisStateHistory.created_at.desc(), ThesisStateHistory.id.desc())
        .limit(_TRAJECTORY_LIMIT)
    )
    rows = session.scalars(stmt).all()
    return [
        (r.conviction_score if r.conviction_score is not None else 50.0, r.state.value)
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Number extraction from claim text (for quantitative comparison)
# ---------------------------------------------------------------------------

_DOLLAR_PATTERN = re.compile(
    r"\$\s*([\d,]+(?:\.\d+)?)\s*(billion|million|B|M)?",
    re.IGNORECASE,
)

_PCT_PATTERN = re.compile(
    r"([\d]+(?:\.\d+)?)\s*%",
)


def _extract_dollar_amount(text: str) -> Optional[float]:
    """Extract the first dollar amount from claim text, normalized to raw number."""
    m = _DOLLAR_PATTERN.search(text)
    if not m:
        return None
    val = float(m.group(1).replace(",", ""))
    suffix = (m.group(2) or "").lower()
    if suffix in ("billion", "b"):
        val *= 1e9
    elif suffix in ("million", "m"):
        val *= 1e6
    return val


def _extract_percentage(text: str) -> Optional[float]:
    """Extract the first percentage from claim text."""
    m = _PCT_PATTERN.search(text)
    if not m:
        return None
    return float(m.group(1))


def _fmt_dollars(val: float) -> str:
    """Format a dollar amount for display."""
    if abs(val) >= 1e9:
        return f"${val / 1e9:.1f}B"
    if abs(val) >= 1e6:
        return f"${val / 1e6:.0f}M"
    return f"${val:,.0f}"


def _pct_change(new: float, old: float) -> str:
    """Compute and format percentage change."""
    if old == 0:
        return "N/A"
    change = (new - old) / abs(old) * 100
    return f"{change:+.1f}%"


# ---------------------------------------------------------------------------
# Annotation builder
# ---------------------------------------------------------------------------

def _annotate_claim(
    claim: Claim,
    guidance: list[Claim],
    estimates: list[EarningsEstimate],
    same_type_priors: dict[str, list[Claim]],
) -> Optional[str]:
    """Build a 1-line annotation comparing a new claim to prior context."""
    ct = claim.claim_type.value
    text = claim.claim_text_normalized or ""
    short = claim.claim_text_short or text[:50]
    parts: list[str] = []

    new_amount = _extract_dollar_amount(text)
    new_pct = _extract_percentage(text)

    # --- Compare against consensus estimates ---
    if ct in ("demand", "margin", "guidance") and estimates:
        est = estimates[0]  # most recent period
        if ct in ("demand",) and new_amount and est.estimated_revenue:
            surprise = _pct_change(new_amount, est.estimated_revenue)
            parts.append(f"consensus was {_fmt_dollars(est.estimated_revenue)} ({surprise} vs estimate)")
            if est.actual_revenue and est.actual_revenue != new_amount:
                # This is a different period's actual — show as QoQ reference
                parts.append(f"prior Q actual was {_fmt_dollars(est.actual_revenue)}")
        elif ct == "margin" and new_pct and est.estimated_revenue:
            # No direct margin estimate in DB, but note the data point
            pass

    # --- Compare against prior guidance ---
    if ct == "guidance" and guidance:
        for g in guidance[:2]:
            g_amount = _extract_dollar_amount(g.claim_text_normalized or "")
            g_date = g.published_at.strftime("%Y-%m-%d") if g.published_at else "?"
            if g_amount and new_amount:
                change = _pct_change(new_amount, g_amount)
                parts.append(f"prior guidance was {_fmt_dollars(g_amount)} on {g_date} ({change} step)")
                break
            elif g.claim_text_short:
                parts.append(f"prior guidance [{g_date}]: \"{g.claim_text_short}\"")
                break

    # --- Compare against same-type prior claims ---
    priors = same_type_priors.get(ct, [])
    if priors and not parts:
        # Only add if we don't already have a comparison
        p = priors[0]
        p_date = p.published_at.strftime("%Y-%m-%d") if p.published_at else "?"
        p_dir = p.direction.value if hasattr(p.direction, "value") else str(p.direction)

        p_amount = _extract_dollar_amount(p.claim_text_normalized or "")
        p_pct = _extract_percentage(p.claim_text_normalized or "")

        if new_amount and p_amount:
            change = _pct_change(new_amount, p_amount)
            parts.append(f"prior [{p_date}] was {_fmt_dollars(p_amount)} ({change})")
        elif new_pct and p_pct:
            diff = new_pct - p_pct
            parts.append(f"prior [{p_date}] was {p_pct:.1f}% ({diff:+.1f}pp)")
        else:
            parts.append(f"prior [{p_date}]: \"{p.claim_text_short}\" (dir={p_dir})")

    if not parts:
        # No prior context found — flag as genuinely new
        return f"- \"{short}\" -> no prior comparable data (NEW signal)"

    return f"- \"{short}\" -> {'; '.join(parts)}"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_prior_context(
    session: Session,
    claims: list[Claim],
    ticker: str,
    thesis_id: Optional[int] = None,
    reference_date: Optional[datetime] = None,
) -> str:
    """Build a prior-expectation context block for the thesis update LLM.

    Args:
        session: SQLAlchemy session (read-only).
        claims: The new claims being scored.
        ticker: Company ticker.
        thesis_id: Optional thesis ID for conviction trajectory.
        reference_date: Reference time for lookups (default: now).

    Returns:
        Formatted context string, or empty string if nothing useful found.
    """
    if not claims:
        return ""

    ref = reference_date or datetime.utcnow()
    new_ids = {c.id for c in claims if c.id}

    # Retrieve prior data
    guidance = _get_recent_guidance(session, ticker, new_ids)
    estimates = _get_consensus_estimates(session, ticker, ref)
    claim_types = {c.claim_type.value for c in claims}
    same_type_priors = _get_same_type_priors(session, ticker, claim_types, new_ids)

    # Build annotations
    annotations: list[str] = []
    for claim in claims:
        ann = _annotate_claim(claim, guidance, estimates, same_type_priors)
        if ann:
            annotations.append(ann)

    if not annotations:
        return ""

    lines = ["## Prior expectation context"]
    lines.extend(annotations)

    # Add conviction trajectory if available
    if thesis_id:
        try:
            trajectory = _get_conviction_trajectory(session, thesis_id)
            if trajectory:
                scores = " -> ".join(
                    f"{score:.1f} ({state})" for score, state in reversed(trajectory)
                )
                lines.append(f"\nConviction trajectory: {scores}")
        except Exception:
            pass  # non-critical

    # Add estimates summary if available
    if estimates:
        est = estimates[0]
        est_lines = []
        if est.estimated_revenue:
            est_lines.append(f"Revenue est: {_fmt_dollars(est.estimated_revenue)}")
        if est.actual_revenue:
            est_lines.append(f"actual: {_fmt_dollars(est.actual_revenue)}")
        if est.estimated_eps:
            est_lines.append(f"EPS est: ${est.estimated_eps:.2f}")
        if est.actual_eps:
            est_lines.append(f"actual: ${est.actual_eps:.2f}")
        if est_lines:
            period = est.fiscal_period or "recent"
            lines.append(f"\nConsensus snapshot ({period}): {', '.join(est_lines)}")

    return "\n".join(lines)
