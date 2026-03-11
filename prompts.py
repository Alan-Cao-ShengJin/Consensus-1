"""Prompt templates for LLM claim extraction."""
from __future__ import annotations

SYSTEM_PROMPT = """\
You are a structured-data extraction engine for an investment research platform.

Your job: read public-market documents (earnings transcripts, news articles, SEC filings, broker reports) and extract **atomic, investable claims**.

Rules:
- Each claim must be a single factual assertion — not a summary of the document.
- Prefer fewer high-quality claims over many weak ones.
- Do NOT output duplicate or near-duplicate claims.
- Do NOT summarize the document as a whole.
- Every claim must conform exactly to the JSON schema provided.
- Output ONLY a JSON array of claim objects. No prose, no markdown, no explanation.
"""

USER_PROMPT_TEMPLATE = """\
Extract atomic investable claims from the document below.

## Document metadata
- Source type: {source_type}
- Primary company ticker: {primary_company_ticker}
- Title: {title}

## Extraction schema
Each claim must be a JSON object with these fields:
- claim_text_normalized (string): Full normalized claim sentence.
- claim_text_short (string): ≤10-word summary of the claim.
- claim_type (string enum): One of: demand, pricing, margin, capacity, guidance, regulation, competition, capital_allocation, inventory, customer_behavior, supply_chain
- economic_channel (string enum): One of: revenue, gross_margin, opex, earnings, multiple, sentiment, liquidity, timing
- direction (string enum): One of: positive, negative, mixed, neutral
- strength (float 0-1): How strong the signal is.
- time_horizon (string|null): e.g. "Q1 2026", "next 12 months", or null if unspecified.
- novelty_type (string enum): One of: new, confirming, conflicting, repetitive
- confidence (float 0-1): Your confidence in the extraction accuracy.
- is_structural (bool): True if this is a lasting structural shift (not a one-quarter blip).
- is_ephemeral (bool): True if this is a short-lived / one-quarter data point.
- affected_tickers (list[string]): Tickers affected by this claim. Always include the primary ticker if relevant.
- themes (list[string]): Thematic tags, e.g. "AI Infrastructure Spend", "Margin Expansion".
- thesis_link_type (string|null): One of: supports, weakens, context, or null.

## Document text
{document_text}

## Output
Return ONLY a JSON array of claim objects. Example:
[
  {{"claim_text_normalized": "...", "claim_text_short": "...", ...}},
  ...
]
"""


def build_extraction_messages(
    clean_text: str,
    metadata: dict,
) -> list[dict]:
    """Build the messages list for an OpenAI chat completion call."""
    user_content = USER_PROMPT_TEMPLATE.format(
        source_type=metadata.get("source_type", "unknown"),
        primary_company_ticker=metadata.get("primary_company_ticker", "N/A"),
        title=metadata.get("title", "Untitled"),
        document_text=clean_text,
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


# ---------------------------------------------------------------------------
# Thesis update prompts
# ---------------------------------------------------------------------------

THESIS_UPDATE_SYSTEM_PROMPT = """\
You are an investment thesis analyst engine for a structured research platform.

Your job: given an existing investment thesis and a set of newly ingested claims, assess how each claim affects the thesis.

Rules:
- CRITICAL: First assess whether each claim is RELEVANT to the specific thesis. A claim about retail competition is NOT relevant to a cloud/AWS thesis. A claim about a competitor is only relevant if it directly affects the thesis company's competitive position in the thesis domain.
- If a claim is NOT relevant to the thesis, set impact to "neutral" and materiality to 0.0.
- For relevant claims, classify impact as: supports, weakens, neutral, or conflicting.
- Assign a materiality score (0-1) for how significant the claim is to the thesis. Only relevant claims should have materiality > 0.
- Provide a brief rationale for each classification, including why the claim is or is not relevant.
- Recommend an overall thesis state based on the cumulative RELEVANT evidence only.
- Output ONLY valid JSON matching the schema provided. No prose, no markdown.
"""

THESIS_UPDATE_USER_TEMPLATE = """\
## Current thesis snapshot
- Title: {thesis_title}
- Company: {company_ticker}
- Current state: {current_state}
- Current conviction score: {conviction_score}
- Summary: {thesis_summary}

## New claims to assess
{claims_json}

## Output schema
Return a single JSON object with:
- overall_state_recommendation (string): One of: forming, strengthening, stable, weakening, probation, broken, achieved
- summary_note (string): 1-2 sentence summary of how these claims collectively affect the thesis.
- claim_assessments (array): One object per claim:
  - claim_id (int): The claim's ID.
  - impact (string): One of: supports, weakens, neutral, conflicting
  - rationale (string): Brief explanation.
  - materiality (float 0-1): How material this claim is to the thesis.

Example:
{{
  "overall_state_recommendation": "strengthening",
  "summary_note": "Strong revenue beat and raised guidance reinforce the AI demand thesis.",
  "claim_assessments": [
    {{"claim_id": 1, "impact": "supports", "rationale": "Revenue growth confirms demand.", "materiality": 0.8}}
  ]
}}
"""


def build_thesis_update_messages(
    thesis_title: str,
    company_ticker: str,
    current_state: str,
    conviction_score: float,
    thesis_summary: str,
    claims_json: str,
) -> list[dict]:
    """Build the messages list for a thesis-update LLM call."""
    user_content = THESIS_UPDATE_USER_TEMPLATE.format(
        thesis_title=thesis_title,
        company_ticker=company_ticker,
        current_state=current_state,
        conviction_score=conviction_score,
        thesis_summary=thesis_summary or "(no summary)",
        claims_json=claims_json,
    )
    return [
        {"role": "system", "content": THESIS_UPDATE_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
