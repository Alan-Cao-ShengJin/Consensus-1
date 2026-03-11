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


def _normalize_enums(raw: dict) -> dict:
    """Fix common LLM enum swaps between claim_type and economic_channel."""
    ct = raw.get("claim_type", "")
    ec = raw.get("economic_channel", "")

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
