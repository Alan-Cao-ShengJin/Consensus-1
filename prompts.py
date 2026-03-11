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
