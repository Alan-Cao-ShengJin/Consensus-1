"""Claim extraction interface, stub implementation, and LLM-backed extractor."""
from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from typing import Optional

from models import ClaimType, EconomicChannel, Direction, NoveltyType
from schemas import ExtractedClaim

logger = logging.getLogger(__name__)


class ClaimExtractorBase(ABC):
    @abstractmethod
    def extract_claims(self, clean_text: str, metadata: dict) -> list[ExtractedClaim]:
        ...


class StubClaimExtractor(ClaimExtractorBase):
    """Returns 1-3 hardcoded claims derived from simple heuristics on the text.

    Good enough for pipeline testing. Replace with LLM extractor in Step 3.
    """

    def extract_claims(self, clean_text: str, metadata: dict) -> list[ExtractedClaim]:
        ticker = metadata.get("primary_company_ticker")
        claims: list[ExtractedClaim] = []

        # Heuristic 1: look for revenue / growth patterns
        if re.search(r"revenue.{0,30}(grew|increased|rose|up)", clean_text, re.IGNORECASE):
            claims.append(ExtractedClaim(
                claim_text_normalized="Revenue showed positive growth trends",
                claim_text_short="Revenue growth",
                claim_type=ClaimType.DEMAND,
                economic_channel=EconomicChannel.REVENUE,
                direction=Direction.POSITIVE,
                strength=0.7,
                novelty_type=NoveltyType.NEW,
                confidence=0.6,
                affected_tickers=[ticker] if ticker else [],
                themes=["Revenue Growth"],
                thesis_link_type="supports",
            ))

        # Heuristic 2: look for margin patterns
        if re.search(r"margin.{0,30}(expand|improv|increas)", clean_text, re.IGNORECASE):
            claims.append(ExtractedClaim(
                claim_text_normalized="Operating margins are expanding",
                claim_text_short="Margin expansion",
                claim_type=ClaimType.MARGIN,
                economic_channel=EconomicChannel.GROSS_MARGIN,
                direction=Direction.POSITIVE,
                strength=0.6,
                novelty_type=NoveltyType.NEW,
                confidence=0.5,
                affected_tickers=[ticker] if ticker else [],
                themes=["Margin Expansion"],
                thesis_link_type="supports",
            ))

        # Heuristic 3: look for guidance / outlook
        if re.search(r"(guidance|outlook|forecast|expect).{0,30}(above|raise|beat|strong)", clean_text, re.IGNORECASE):
            claims.append(ExtractedClaim(
                claim_text_normalized="Company raised or beat guidance expectations",
                claim_text_short="Guidance beat",
                claim_type=ClaimType.GUIDANCE,
                economic_channel=EconomicChannel.EARNINGS,
                direction=Direction.POSITIVE,
                strength=0.8,
                novelty_type=NoveltyType.NEW,
                confidence=0.7,
                affected_tickers=[ticker] if ticker else [],
                themes=["Earnings Momentum"],
                thesis_link_type="supports",
            ))

        # Heuristic 4: earnings beat/miss (FMP estimates format)
        beat_match = re.search(r"(?:Actual\s+(?:Revenue|EPS)).*?\(beat by (\d+\.?\d*)%\)", clean_text, re.IGNORECASE)
        if beat_match:
            beat_pct = float(beat_match.group(1))
            claims.append(ExtractedClaim(
                claim_text_normalized=f"Company beat consensus estimates by {beat_pct:.1f}%",
                claim_text_short="Earnings beat",
                claim_type=ClaimType.GUIDANCE,
                economic_channel=EconomicChannel.EARNINGS,
                direction=Direction.POSITIVE,
                strength=min(0.95, 0.7 + beat_pct / 100),
                novelty_type=NoveltyType.NEW,
                confidence=0.9,
                affected_tickers=[ticker] if ticker else [],
                themes=["Earnings Surprise"],
                thesis_link_type="supports",
                is_structural=True,
            ))

        miss_match = re.search(r"(?:Actual\s+(?:Revenue|EPS)).*?\(missed by (\d+\.?\d*)%\)", clean_text, re.IGNORECASE)
        if miss_match:
            miss_pct = float(miss_match.group(1))
            claims.append(ExtractedClaim(
                claim_text_normalized=f"Company missed consensus estimates by {miss_pct:.1f}%",
                claim_text_short="Earnings miss",
                claim_type=ClaimType.GUIDANCE,
                economic_channel=EconomicChannel.EARNINGS,
                direction=Direction.NEGATIVE,
                strength=min(0.95, 0.7 + miss_pct / 100),
                novelty_type=NoveltyType.NEW,
                confidence=0.9,
                affected_tickers=[ticker] if ticker else [],
                themes=["Earnings Surprise"],
                thesis_link_type="weakens",
                is_structural=True,
            ))

        # Heuristic 5: structured financial data (FMP financials format)
        rev_match = re.search(r"Revenue:\s*\$(\d+\.?\d*)B", clean_text)
        fcf_match = re.search(r"Free Cash Flow:\s*\$(-?\d+\.?\d*)B", clean_text)

        if rev_match:
            growth_match = re.search(r"Revenue Growth:\s*(-?\d+\.?\d*)%", clean_text)
            if growth_match:
                growth = float(growth_match.group(1))
                rev_b = float(rev_match.group(1))
                direction = Direction.POSITIVE if growth > 0 else Direction.NEGATIVE
                claims.append(ExtractedClaim(
                    claim_text_normalized=f"Revenue of ${rev_b:.1f}B with {growth:+.1f}% growth",
                    claim_text_short=f"Revenue {'growth' if growth > 0 else 'decline'} {growth:+.1f}%",
                    claim_type=ClaimType.DEMAND,
                    economic_channel=EconomicChannel.REVENUE,
                    direction=direction,
                    strength=min(0.95, 0.6 + abs(growth) / 100),
                    novelty_type=NoveltyType.NEW,
                    confidence=0.95,
                    affected_tickers=[ticker] if ticker else [],
                    themes=["Revenue Trend"],
                    thesis_link_type="supports" if growth > 0 else "weakens",
                    is_structural=True,
                ))

        if re.search(r"Gross Profit.*?margin\s+(\d+\.?\d*)%", clean_text, re.IGNORECASE):
            gm_match = re.search(r"Gross Profit.*?margin\s+(\d+\.?\d*)%", clean_text, re.IGNORECASE)
            gm_pct = float(gm_match.group(1))
            claims.append(ExtractedClaim(
                claim_text_normalized=f"Gross margin at {gm_pct:.1f}%",
                claim_text_short=f"Gross margin {gm_pct:.1f}%",
                claim_type=ClaimType.MARGIN,
                economic_channel=EconomicChannel.GROSS_MARGIN,
                direction=Direction.POSITIVE if gm_pct > 40 else Direction.NEUTRAL,
                strength=0.7,
                novelty_type=NoveltyType.NEW,
                confidence=0.95,
                affected_tickers=[ticker] if ticker else [],
                themes=["Margin Profile"],
                thesis_link_type="supports",
                is_structural=True,
            ))

        if fcf_match:
            fcf_b = float(fcf_match.group(1))
            direction = Direction.POSITIVE if fcf_b > 0 else Direction.NEGATIVE
            claims.append(ExtractedClaim(
                claim_text_normalized=f"Free cash flow of ${fcf_b:.1f}B",
                claim_text_short=f"FCF ${fcf_b:.1f}B",
                claim_type=ClaimType.CAPITAL_ALLOCATION,
                economic_channel=EconomicChannel.LIQUIDITY,
                direction=direction,
                strength=0.75,
                novelty_type=NoveltyType.NEW,
                confidence=0.95,
                affected_tickers=[ticker] if ticker else [],
                themes=["Cash Generation"],
                thesis_link_type="supports" if fcf_b > 0 else "weakens",
                is_structural=True,
            ))

        # Heuristic 6: earnings transcript / management commentary signals
        if re.search(r"(accelerat|re-?accelerat).{0,30}(growth|revenue|demand)", clean_text, re.IGNORECASE):
            claims.append(ExtractedClaim(
                claim_text_normalized="Management highlighted growth acceleration",
                claim_text_short="Growth acceleration",
                claim_type=ClaimType.DEMAND,
                economic_channel=EconomicChannel.REVENUE,
                direction=Direction.POSITIVE,
                strength=0.85,
                novelty_type=NoveltyType.NEW,
                confidence=0.7,
                affected_tickers=[ticker] if ticker else [],
                themes=["Growth Acceleration"],
                thesis_link_type="supports",
            ))

        if re.search(r"(headwind|decelerat|slowdown|weaken).{0,30}(demand|growth|revenue|macro)", clean_text, re.IGNORECASE):
            claims.append(ExtractedClaim(
                claim_text_normalized="Headwinds or deceleration flagged",
                claim_text_short="Growth headwinds",
                claim_type=ClaimType.DEMAND,
                economic_channel=EconomicChannel.REVENUE,
                direction=Direction.NEGATIVE,
                strength=0.8,
                novelty_type=NoveltyType.NEW,
                confidence=0.65,
                affected_tickers=[ticker] if ticker else [],
                themes=["Growth Deceleration"],
                thesis_link_type="weakens",
            ))

        if re.search(r"(raised|increased|upgraded).{0,20}(guidance|outlook|forecast|target)", clean_text, re.IGNORECASE):
            claims.append(ExtractedClaim(
                claim_text_normalized="Company raised forward guidance",
                claim_text_short="Guidance raised",
                claim_type=ClaimType.GUIDANCE,
                economic_channel=EconomicChannel.EARNINGS,
                direction=Direction.POSITIVE,
                strength=0.9,
                novelty_type=NoveltyType.NEW,
                confidence=0.8,
                affected_tickers=[ticker] if ticker else [],
                themes=["Earnings Momentum"],
                thesis_link_type="supports",
                is_structural=True,
            ))

        if re.search(r"(lowered|cut|reduced|downgraded).{0,20}(guidance|outlook|forecast|target)", clean_text, re.IGNORECASE):
            claims.append(ExtractedClaim(
                claim_text_normalized="Company lowered forward guidance",
                claim_text_short="Guidance cut",
                claim_type=ClaimType.GUIDANCE,
                economic_channel=EconomicChannel.EARNINGS,
                direction=Direction.NEGATIVE,
                strength=0.9,
                novelty_type=NoveltyType.NEW,
                confidence=0.8,
                affected_tickers=[ticker] if ticker else [],
                themes=["Earnings Risk"],
                thesis_link_type="weakens",
                is_structural=True,
            ))

        # Fallback: always return at least one generic claim
        if not claims:
            claims.append(ExtractedClaim(
                claim_text_normalized="Document contains relevant company information",
                claim_text_short="General info",
                claim_type=ClaimType.DEMAND,
                economic_channel=EconomicChannel.SENTIMENT,
                direction=Direction.NEUTRAL,
                strength=0.3,
                novelty_type=NoveltyType.REPETITIVE,
                confidence=0.4,
                affected_tickers=[ticker] if ticker else [],
                themes=[],
            ))

        return claims


# ---------------------------------------------------------------------------
# Fuzzy enum mapping: salvage claims when LLM swaps claim_type / economic_channel
# ---------------------------------------------------------------------------

_ECONOMIC_CHANNEL_TO_CLAIM_TYPE = {
    "revenue": "demand",
    "gross_margin": "margin",
    "opex": "margin",
    "earnings": "margin",
    "multiple": "pricing",
    "sentiment": "demand",
    "liquidity": "capital_allocation",
    "timing": "guidance",
}

_CLAIM_TYPE_TO_ECONOMIC_CHANNEL = {
    "demand": "revenue",
    "pricing": "multiple",
    "margin": "gross_margin",
    "capacity": "revenue",
    "guidance": "earnings",
    "regulation": "sentiment",
    "competition": "revenue",
    "capital_allocation": "liquidity",
    "inventory": "revenue",
    "customer_behavior": "revenue",
    "supply_chain": "revenue",
}

_VALID_CLAIM_TYPES = {ct.value for ct in ClaimType}
_VALID_ECONOMIC_CHANNELS = {ec.value for ec in EconomicChannel}


_EC_ALIASES = {
    "cash_flow": "liquidity",
    "free_cash_flow": "liquidity",
    "operating_margin": "gross_margin",
    "net_income": "earnings",
    "eps": "earnings",
    "ebitda": "earnings",
    "market_cap": "multiple",
    "valuation": "multiple",
}


def _normalize_enums(raw: dict) -> dict:
    """Fix common LLM enum swaps between claim_type and economic_channel."""
    ct = raw.get("claim_type", "")
    ec = raw.get("economic_channel", "")

    # Fix common aliases first
    if ec in _EC_ALIASES:
        raw["economic_channel"] = _EC_ALIASES[ec]
        ec = raw["economic_channel"]

    if ct not in _VALID_CLAIM_TYPES and ct in _VALID_ECONOMIC_CHANNELS:
        mapped = _ECONOMIC_CHANNEL_TO_CLAIM_TYPE.get(ct, "demand")
        logger.info("Fuzzy fix: claim_type '%s' -> '%s' (was economic_channel value)", ct, mapped)
        raw["claim_type"] = mapped
        if ec not in _VALID_ECONOMIC_CHANNELS:
            raw["economic_channel"] = ct

    if ec not in _VALID_ECONOMIC_CHANNELS and ec in _VALID_CLAIM_TYPES:
        mapped = _CLAIM_TYPE_TO_ECONOMIC_CHANNEL.get(ec, "revenue")
        logger.info("Fuzzy fix: economic_channel '%s' -> '%s' (was claim_type value)", ec, mapped)
        raw["economic_channel"] = mapped

    return raw


class LLMClaimExtractor(ClaimExtractorBase):
    """Production extractor that calls OpenAI to extract structured claims.

    Requires OPENAI_API_KEY env var. Optionally set OPENAI_MODEL (default: gpt-4o-mini).
    """

    def __init__(self, model: str | None = None):
        self._model = model

    def extract_claims(self, clean_text: str, metadata: dict) -> list[ExtractedClaim]:
        from llm_client import call_openai_json
        from prompts import build_extraction_messages

        messages = build_extraction_messages(clean_text, metadata)
        raw_claims = call_openai_json(messages, model=self._model)

        validated: list[ExtractedClaim] = []
        for i, raw in enumerate(raw_claims):
            try:
                raw = _normalize_enums(raw)
                claim = ExtractedClaim.model_validate(raw)
                validated.append(claim)
            except Exception as e:
                logger.warning("Skipping claim %d: validation failed: %s", i, e)
                continue

        if not validated:
            logger.warning(
                "LLM returned %d raw claims but none passed validation", len(raw_claims)
            )

        return validated
