"""Company enrichment service: update company metadata from external sources."""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from crud import get_or_create_company

logger = logging.getLogger(__name__)

# Fields that can be enriched on the Company model
_ENRICHABLE_FIELDS = {"name", "sector", "industry", "subindustry", "country", "market_cap_bucket", "primary_exchange"}


def enrich_company(session: Session, ticker: str, data: dict) -> bool:
    """Upsert company enrichment fields. Returns True if any field was updated."""
    company = get_or_create_company(session, ticker)
    updated = False

    for field, value in data.items():
        if field not in _ENRICHABLE_FIELDS:
            continue
        if value and getattr(company, field, None) != value:
            setattr(company, field, value)
            updated = True

    if updated:
        session.flush()

    return updated
