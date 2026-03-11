"""Claim extraction interface and stub implementation for v1 testing."""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Optional

from models import ClaimType, EconomicChannel, Direction, NoveltyType
from schemas import ExtractedClaim


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
