"""Base classes and shared models for source connectors."""
from __future__ import annotations

import hashlib
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from models import SourceType, SourceTier

logger = logging.getLogger(__name__)


@dataclass
class DocumentPayload:
    """Normalized document payload shared across all document connectors."""

    source_key: str               # registry key, e.g. "sec_10k"
    source_type: SourceType
    source_tier: SourceTier
    ticker: str
    title: str
    url: Optional[str] = None
    published_at: Optional[datetime] = None
    author: Optional[str] = None
    external_id: Optional[str] = None
    raw_text: str = ""
    content_hash: Optional[str] = None
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.content_hash and self.raw_text:
            self.content_hash = hashlib.sha256(self.raw_text.encode("utf-8")).hexdigest()


class DocumentConnector(ABC):
    """Base class for document source connectors."""

    @property
    @abstractmethod
    def source_key(self) -> str:
        """Registry source key (e.g. 'sec_10k')."""
        ...

    @abstractmethod
    def fetch(self, ticker: str, days: int = 7) -> list[DocumentPayload]:
        """Fetch new document payloads for a ticker.

        Args:
            ticker: Company ticker symbol.
            days: How many days back to look (for backfill).

        Returns:
            List of normalized DocumentPayload objects.
        """
        ...


@dataclass
class NonDocumentResult:
    """Summary of a non-document updater run."""

    source_key: str
    ticker: str
    rows_upserted: int = 0
    rows_skipped: int = 0
    errors: list[str] = field(default_factory=list)


class NonDocumentUpdater(ABC):
    """Base class for non-document data updaters (prices, calendar, enrichment)."""

    @property
    @abstractmethod
    def source_key(self) -> str:
        ...

    @abstractmethod
    def update(self, session, ticker: str, days: int = 7, dry_run: bool = False) -> NonDocumentResult:
        """Fetch and upsert non-document data for a ticker.

        Args:
            session: SQLAlchemy session.
            ticker: Company ticker symbol.
            days: How many days back to look.
            dry_run: If True, fetch but don't persist.

        Returns:
            Summary of what was done.
        """
        ...
