"""Simple thesis updater: one LLM call per document.

Information → Conviction → Investment.

Each call receives:
- Current thesis summary + score (compact state of what we know)
- New information (document text, source, date)
- Guardrails (max score change by source tier)

Returns:
- Updated thesis summary + new score + reasoning

No claim extraction. No hardwired dampening. The LLM does the thinking.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy import select

from models import Thesis, ThesisState, ThesisStateHistory
from llm_client import call_openai_json_object

logger = logging.getLogger(__name__)

# Max score adjustment by source tier
TIER_LIMITS = {
    "TIER_1": 15,  # SEC filings, earnings calls — direct from company
    "TIER_2": 5,   # analyst estimates, Finnhub news
    "TIER_3": 3,   # general news, RSS — cautious
}

SYSTEM_PROMPT = """\
You are an investment analyst updating a thesis on a single company.

You will receive:
1. Your current thesis summary and conviction score (what you know so far)
2. A new piece of information (document text) with its source and date
3. Rules on how much you can adjust the score

Your job:
- Read the new information carefully
- Compare it to what you already know (your current thesis summary)
- Determine if this information is GENUINELY NEW or already known/priced in
- Update your thesis summary to incorporate any new insights
- Adjust the conviction score appropriately

CONVICTION SCORE MEANING:
- 0-20: We know almost nothing, or evidence is overwhelmingly negative
- 20-40: Weak thesis, limited evidence, significant concerns
- 40-60: Moderate thesis, mixed signals, unclear direction
- 60-75: Solid thesis, good evidence, identifiable catalysts
- 75-90: Strong thesis, consistent evidence from high-quality sources
- 90-100: Exceptional conviction — reserve for rare cases with overwhelming evidence

CRITICAL RULES:
- If the information is NOT new (already reflected in your thesis summary), make minimal or zero adjustment
- If the information CONFIRMS what you already know, small positive adjustment (+1 to +3)
- If the information CONTRADICTS your thesis, adjust negatively and explain why
- Older information has less impact — the market may have already priced it in
- Your updated_summary must be COMPACT (3-5 sentences max) — this is your memory for next time
- The updated_summary should reflect your CUMULATIVE understanding, not just this document
- Always include key numbers (revenue, margins, growth rates) in your summary when available
- Be specific about risks and catalysts, not generic

OUTPUT FORMAT: Return a single JSON object with exactly these fields:
{
  "new_score": <int 0-100>,
  "score_change": <int, how much you changed it>,
  "reasoning": "<1-2 sentences: why you made this adjustment>",
  "updated_summary": "<3-5 sentences: your updated cumulative thesis>",
  "is_new_information": <bool: does this contain genuinely new info vs already known>
}
"""

USER_TEMPLATE = """\
## Current Thesis State
Company: {ticker}
Current Score: {current_score}/100
Current Summary: {current_summary}

## New Information
Source: {source_type} ({source_tier} — {tier_description})
Published: {published_date}
Days since last update: {days_since_last}

{document_text}

## Scoring Rules
This is a {source_tier} source. You may adjust the score by at most ±{max_change} points.
- TIER_1 (SEC filings, earnings calls): ±15 max — direct from the company, highest weight
- TIER_2 (analyst estimates, financial news): ±5 max — informed but external
- TIER_3 (general news, RSS): ±3 max — noisy, often duplicated or speculative
Your new_score must be between {score_floor} and {score_ceiling} (current {current_score} ± {max_change}).
"""

TIER_DESCRIPTIONS = {
    "TIER_1": "direct from company, highest reliability",
    "TIER_2": "informed external source, moderate reliability",
    "TIER_3": "general news, lower reliability — treat cautiously",
}


def _resolve_state(score: float) -> ThesisState:
    """Map conviction score to thesis state."""
    if score >= 65:
        return ThesisState.STRENGTHENING
    elif score >= 45:
        return ThesisState.FORMING
    elif score >= 30:
        return ThesisState.WEAKENING
    else:
        return ThesisState.WEAKENING


def _trim_document(text: str, max_chars: int = 30000) -> str:
    """Trim document text to fit in LLM context."""
    if len(text) <= max_chars:
        return text
    # Keep first and last portions
    half = max_chars // 2
    return text[:half] + "\n\n[... middle section trimmed for length ...]\n\n" + text[-half:]


def update_thesis_with_document(
    session: Session,
    thesis_id: int,
    document_text: str,
    source_type: str,
    source_tier: str,
    published_at: datetime,
    document_title: str = "",
    use_llm: bool = True,
) -> dict:
    """Update thesis conviction based on a single document.

    Args:
        session: DB session
        thesis_id: ID of the thesis to update
        document_text: Raw text of the document
        source_type: e.g. "10-K", "EARNINGS_TRANSCRIPT", "NEWS"
        source_tier: "TIER_1", "TIER_2", or "TIER_3"
        published_at: When the document was published
        document_title: Title for logging
        use_llm: If False, skip LLM and return unchanged

    Returns:
        Dict with score_before, score_after, score_change, reasoning, updated_summary
    """
    thesis = session.get(Thesis, thesis_id)
    if not thesis:
        raise ValueError(f"Thesis {thesis_id} not found")

    score_before = thesis.conviction_score or 0.0
    summary_before = thesis.summary or "(No thesis yet — starting from scratch)"

    # Compute days since last update
    last_history = session.scalars(
        select(ThesisStateHistory)
        .where(ThesisStateHistory.thesis_id == thesis_id)
        .order_by(ThesisStateHistory.created_at.desc())
        .limit(1)
    ).first()
    if last_history and last_history.created_at:
        days_since = (published_at - last_history.created_at).days
    else:
        days_since = 0

    tier = source_tier.upper() if source_tier else "TIER_3"
    max_change = TIER_LIMITS.get(tier, 3)

    if not use_llm:
        # Stub mode — no change
        return {
            "score_before": score_before,
            "score_after": score_before,
            "score_change": 0,
            "reasoning": "Stub mode — no LLM call",
            "updated_summary": summary_before,
            "is_new_information": False,
        }

    # Build LLM messages
    score_floor = max(0, int(score_before) - max_change)
    score_ceiling = min(100, int(score_before) + max_change)

    # For the very first update (score=0, no summary), give more room
    if score_before == 0 and summary_before.startswith("(No thesis"):
        max_change = 50  # calibration phase — can set initial score freely
        score_floor = 0
        score_ceiling = 100

    trimmed_text = _trim_document(document_text)

    user_content = USER_TEMPLATE.format(
        ticker=thesis.company_ticker,
        current_score=int(score_before),
        current_summary=summary_before,
        source_type=source_type,
        source_tier=tier,
        tier_description=TIER_DESCRIPTIONS.get(tier, "unknown source"),
        published_date=published_at.strftime("%Y-%m-%d"),
        days_since_last=days_since,
        max_change=max_change,
        score_floor=score_floor,
        score_ceiling=score_ceiling,
        document_text=trimmed_text,
    )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]

    # Call LLM
    try:
        result = call_openai_json_object(messages, temperature=0.3)
    except Exception as e:
        logger.error("LLM call failed for thesis %d: %s", thesis_id, e)
        return {
            "score_before": score_before,
            "score_after": score_before,
            "score_change": 0,
            "reasoning": f"LLM error: {e}",
            "updated_summary": summary_before,
            "is_new_information": False,
        }

    # Extract and validate response
    new_score = result.get("new_score", score_before)
    new_score = max(score_floor, min(score_ceiling, float(new_score)))
    score_change = new_score - score_before
    updated_summary = result.get("updated_summary", summary_before)
    reasoning = result.get("reasoning", "")
    is_new = result.get("is_new_information", True)

    # Update thesis
    thesis.conviction_score = new_score
    thesis.summary = updated_summary
    thesis.state = _resolve_state(new_score)
    thesis.updated_at = published_at  # set to document date, not now

    # Record history (audit trail)
    session.add(ThesisStateHistory(
        thesis_id=thesis_id,
        state=thesis.state,
        conviction_score=new_score,
        note=f"[{source_type}] {reasoning}",
        created_at=published_at,  # back-date to document publication
    ))

    session.flush()

    logger.info(
        "%s | %s | %s | score %d→%d (%+d) | %s",
        published_at.strftime("%Y-%m-%d"),
        thesis.company_ticker,
        source_type,
        int(score_before), int(new_score), int(score_change),
        reasoning[:80],
    )

    return {
        "score_before": score_before,
        "score_after": new_score,
        "score_change": score_change,
        "reasoning": reasoning,
        "updated_summary": updated_summary,
        "is_new_information": is_new,
    }
