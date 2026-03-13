from datetime import datetime
from pydantic import BaseModel, Field
from typing import List, Optional

from models import ClaimType, EconomicChannel, Direction, NoveltyType


class ExtractedClaim(BaseModel):
    claim_text_normalized: str
    claim_text_short: str
    claim_type: ClaimType
    economic_channel: EconomicChannel
    direction: Direction
    strength: float = Field(ge=0, le=1)
    time_horizon: Optional[str] = None
    novelty_type: NoveltyType
    confidence: float = Field(ge=0, le=1)
    published_at: Optional[datetime] = None
    is_structural: bool = False
    is_ephemeral: bool = True
    affected_tickers: List[str] = []
    themes: List[str] = []
    thesis_link_type: Optional[str] = None  # supports / weakens / context
    source_excerpt: Optional[str] = None   # raw text span from source document