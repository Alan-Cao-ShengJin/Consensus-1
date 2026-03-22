"""Generate real investment theses from existing claims and fundamentals.

Each ticker gets one LLM call that synthesizes:
- Top claims (by strength, source tier, novelty)
- Company fundamentals (sector, industry)
- Valuation data (forward PE, peer comparison, gap)
- Earnings estimates (consensus, surprises)

Into a specific, falsifiable investment thesis with calibrated conviction.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime
from typing import Optional

from sqlalchemy import text, select
from sqlalchemy.orm import Session

from models import Thesis, ThesisState, ThesisStateHistory, Company
from prompts import build_thesis_generation_messages
from llm_client import call_openai_json_object

logger = logging.getLogger(__name__)


def _get_top_claims(session: Session, ticker: str, limit: int = 20) -> list[dict]:
    """Get top claims for a ticker, prioritizing TIER_1 and high strength."""
    rows = session.execute(text("""
        SELECT cl.claim_text_short, cl.claim_type, cl.direction, cl.strength,
               cl.novelty_type, d.source_tier, cl.claim_text_normalized
        FROM claims cl
        JOIN claim_company_links ccl ON ccl.claim_id = cl.id
        JOIN documents d ON d.id = cl.document_id
        WHERE ccl.company_ticker = :ticker
        AND cl.novelty_type IN ('NEW', 'CONFIRMING', 'CONFLICTING')
        ORDER BY
            CASE d.source_tier WHEN 'TIER_1' THEN 1 WHEN 'TIER_2' THEN 2 ELSE 3 END,
            cl.strength DESC
        LIMIT :limit
    """), {"ticker": ticker, "limit": limit}).fetchall()

    claims = []
    for r in rows:
        claims.append({
            "short": r[0],
            "type": r[1],
            "direction": r[2],
            "strength": r[3],
            "novelty": r[4],
            "source_tier": r[5],
            "full_text": r[6],
        })
    return claims


def _get_themes(session: Session, ticker: str, limit: int = 8) -> list[str]:
    """Get top themes for a ticker."""
    rows = session.execute(text("""
        SELECT t.theme_name, COUNT(*) as cnt
        FROM claim_theme_links ctl
        JOIN themes t ON t.id = ctl.theme_id
        JOIN claim_company_links ccl ON ccl.claim_id = ctl.claim_id
        WHERE ccl.company_ticker = :ticker
        GROUP BY t.theme_name
        ORDER BY cnt DESC
        LIMIT :limit
    """), {"ticker": ticker, "limit": limit}).scalars().all()
    return list(rows)


def _build_valuation_context(session: Session, ticker: str) -> str:
    """Build valuation context string from thesis and price data."""
    thesis = session.execute(text("""
        SELECT valuation_gap_pct FROM theses
        WHERE company_ticker = :ticker AND status_active = 1
    """), {"ticker": ticker}).fetchone()

    price = session.execute(text("""
        SELECT close, date FROM prices
        WHERE ticker = :ticker ORDER BY date DESC LIMIT 1
    """), {"ticker": ticker}).fetchone()

    lines = []
    if price:
        lines.append(f"- Current price: ${price[0]:.2f} (as of {price[1]})")
    if thesis and thesis[0] is not None:
        gap = thesis[0]
        zone = "BUY" if gap >= 10 else "HOLD" if gap >= -5 else "TRIM" if gap >= -20 else "FULL_EXIT"
        lines.append(f"- Valuation gap: {gap:+.1f}% (zone: {zone})")
    return "\n".join(lines) if lines else "(No valuation data)"


def _build_estimates_context(session: Session, ticker: str) -> str:
    """Build earnings estimates context string."""
    rows = session.execute(text("""
        SELECT fiscal_period, estimated_revenue, estimated_eps,
               actual_revenue, actual_eps, revenue_surprise_pct,
               eps_surprise_pct, surprise_bucket
        FROM earnings_estimates
        WHERE ticker = :ticker
        ORDER BY fiscal_date DESC
        LIMIT 4
    """), {"ticker": ticker}).fetchall()

    if not rows:
        return "(No estimates available)"

    lines = []
    for r in rows:
        period = r[0] or "?"
        parts = [f"{period}:"]
        if r[1]:
            parts.append(f"rev_est=${r[1]/1e9:.1f}B" if r[1] > 1e8 else f"rev_est=${r[1]/1e6:.0f}M")
        if r[2]:
            parts.append(f"eps_est=${r[2]:.2f}")
        if r[3]:
            parts.append(f"rev_act=${r[3]/1e9:.1f}B" if r[3] > 1e8 else f"rev_act=${r[3]/1e6:.0f}M")
        if r[4]:
            parts.append(f"eps_act=${r[4]:.2f}")
        if r[7]:
            parts.append(f"[{r[7]}]")
        lines.append("- " + " | ".join(parts))
    return "\n".join(lines)


def _format_claims_summary(claims: list[dict]) -> str:
    """Format claims into a concise summary for the prompt."""
    if not claims:
        return "(No claims available)"

    lines = []
    for c in claims:
        tier = c["source_tier"]
        lines.append(
            f"- [{tier}] {c['direction'].upper()} {c['type']}: "
            f"{c['short']} (strength={c['strength']:.1f})"
        )
    return "\n".join(lines)


def generate_thesis(
    session: Session,
    ticker: str,
    use_llm: bool = True,
) -> Optional[Thesis]:
    """Generate a real investment thesis for a ticker.

    Loads claims, fundamentals, valuation, and estimates, then calls LLM
    to produce a specific thesis with calibrated conviction.

    Updates the existing active thesis in-place (title, summary, conviction, etc.)
    and records a ThesisStateHistory entry.
    """
    # Find existing thesis
    thesis = session.scalars(
        select(Thesis).where(
            Thesis.company_ticker == ticker,
            Thesis.status_active == True,
        ).order_by(Thesis.updated_at.desc()).limit(1)
    ).first()

    if not thesis:
        logger.warning("No active thesis for %s — skipping", ticker)
        return None

    # Load company info
    company = session.scalars(
        select(Company).where(Company.ticker == ticker)
    ).first()

    company_name = company.name if company else ticker
    sector = company.sector if company else "Unknown"
    industry = company.industry if company else "Unknown"

    # Gather data
    claims = _get_top_claims(session, ticker)
    themes = _get_themes(session, ticker)
    valuation_ctx = _build_valuation_context(session, ticker)
    estimates_ctx = _build_estimates_context(session, ticker)
    claims_summary = _format_claims_summary(claims)

    if not claims:
        logger.info("No claims for %s — skipping thesis generation", ticker)
        return None

    if not use_llm:
        # Stub mode: derive from claim statistics
        return _stub_generate(session, thesis, claims, sector)

    # Build LLM messages
    messages = build_thesis_generation_messages(
        ticker=ticker,
        company_name=company_name,
        sector=sector,
        industry=industry,
        valuation_context=valuation_ctx,
        estimates_context=estimates_ctx,
        claims_summary=claims_summary,
        themes=", ".join(themes) if themes else "(none)",
    )

    # Call LLM
    try:
        result = call_openai_json_object(messages, temperature=0.3)
    except Exception as e:
        logger.error("LLM thesis generation failed for %s: %s", ticker, e)
        return _stub_generate(session, thesis, claims, sector)

    # Update thesis with LLM output
    thesis.title = result.get("title", thesis.title)
    thesis.summary = result.get("summary", thesis.summary)
    thesis.thesis_type = result.get("thesis_type")

    new_conviction = result.get("initial_conviction", 50.0)
    new_conviction = max(20.0, min(90.0, float(new_conviction)))  # clamp
    thesis.conviction_score = new_conviction

    thesis.base_case_rerating = result.get("base_case_rerating")
    thesis.bull_case_rerating = result.get("bull_case_rerating")
    thesis.bear_case_rerating = result.get("bear_case_rerating")

    # Resolve state from conviction
    if new_conviction >= 65:
        thesis.state = ThesisState.STRENGTHENING
    elif new_conviction >= 45:
        thesis.state = ThesisState.FORMING
    elif new_conviction >= 35:
        thesis.state = ThesisState.WEAKENING
    else:
        thesis.state = ThesisState.WEAKENING

    thesis.updated_at = datetime.utcnow()

    # Record history
    key_drivers = result.get("key_drivers", [])
    key_risks = result.get("key_risks", [])
    note_parts = [f"Generated thesis: {thesis.title}"]
    if key_drivers:
        note_parts.append(f"Drivers: {'; '.join(key_drivers[:3])}")
    if key_risks:
        note_parts.append(f"Risks: {'; '.join(key_risks[:2])}")

    session.add(ThesisStateHistory(
        thesis_id=thesis.id,
        state=thesis.state,
        conviction_score=thesis.conviction_score,
        valuation_gap_pct=thesis.valuation_gap_pct,
        base_case_rerating=thesis.base_case_rerating,
        note=". ".join(note_parts),
        created_at=datetime.utcnow(),
    ))

    logger.info(
        "Generated thesis for %s: conv=%.0f, type=%s, title='%s'",
        ticker, new_conviction, thesis.thesis_type, thesis.title[:60],
    )
    return thesis


def _stub_generate(
    session: Session,
    thesis: Thesis,
    claims: list[dict],
    sector: str,
) -> Thesis:
    """Fallback thesis generation without LLM — derive from claim statistics."""
    positive = sum(1 for c in claims if c["direction"] == "positive")
    negative = sum(1 for c in claims if c["direction"] == "negative")
    total = len(claims)

    # Conviction from sentiment ratio
    if total > 0:
        ratio = (positive - negative) / total
        conviction = 50.0 + ratio * 25.0  # range: 25-75
    else:
        conviction = 50.0

    conviction = max(25.0, min(80.0, conviction))
    thesis.conviction_score = conviction

    # Determine thesis type from claim types
    claim_types = [c["type"] for c in claims]
    if claim_types.count("guidance") >= 3 or claim_types.count("demand") >= 5:
        thesis.thesis_type = "growth"
    elif sector == "Utilities" or sector == "Real Estate":
        thesis.thesis_type = "income"
    else:
        thesis.thesis_type = "value"

    # Simple title
    dominant_type = max(set(claim_types), key=claim_types.count) if claim_types else "general"
    thesis.title = f"{thesis.company_ticker} {dominant_type}-driven {thesis.thesis_type} thesis"

    top_claims = [c["short"] for c in claims[:3]]
    thesis.summary = (
        f"{'Bullish' if conviction > 55 else 'Neutral' if conviction > 45 else 'Bearish'} "
        f"outlook based on {total} signals. "
        f"Key signals: {'; '.join(top_claims)}."
    )

    if conviction >= 65:
        thesis.state = ThesisState.STRENGTHENING
    elif conviction >= 45:
        thesis.state = ThesisState.FORMING
    else:
        thesis.state = ThesisState.WEAKENING

    thesis.updated_at = datetime.utcnow()

    session.add(ThesisStateHistory(
        thesis_id=thesis.id,
        state=thesis.state,
        conviction_score=thesis.conviction_score,
        valuation_gap_pct=thesis.valuation_gap_pct,
        note=f"Stub thesis generation: {positive}+ / {negative}- signals",
        created_at=datetime.utcnow(),
    ))

    logger.info(
        "Stub thesis for %s: conv=%.0f, type=%s",
        thesis.company_ticker, conviction, thesis.thesis_type,
    )
    return thesis
