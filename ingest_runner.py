"""End-to-end ingestion: file -> parse -> extract claims -> DB."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy.orm import Session

from sqlalchemy import select

from document_loader import LoadedDocument, load_document
from document_parser import parse_document
from claim_extractor import ClaimExtractorBase, StubClaimExtractor, LLMClaimExtractor
from ingest import ingest_document_with_claims
from novelty_classifier import classify_novelty
from models import Claim, SourceType


@dataclass
class IngestResult:
    document_id: int
    num_claims: int
    tickers_linked: list[str]
    themes_linked: list[str]


def _make_extractor(extractor_type: str) -> ClaimExtractorBase:
    """Instantiate an extractor by name."""
    if extractor_type == "stub":
        return StubClaimExtractor()
    elif extractor_type == "llm":
        return LLMClaimExtractor()
    else:
        raise ValueError(f"Unknown extractor_type: {extractor_type!r}. Use 'stub' or 'llm'.")


def run_ingestion(
    session: Session,
    file_path: str,
    source_type: SourceType,
    ticker: Optional[str] = None,
    thesis_id: Optional[int] = None,
    extractor: Optional[ClaimExtractorBase] = None,
    extractor_type: str = "llm",
    **loader_overrides,
) -> IngestResult:
    """Load, parse, extract, and ingest a document in one call.

    Args:
        extractor: Explicit extractor instance (takes priority).
        extractor_type: "stub" or "llm" — used when extractor is None.
    """

    # 1. Load
    loaded = load_document(file_path, source_type, **loader_overrides)
    if ticker:
        loaded.primary_company_ticker = ticker

    # 2. Parse
    clean_text = parse_document(loaded.raw_text)

    # 3. Extract claims
    if extractor is None:
        extractor = _make_extractor(extractor_type)

    metadata = {
        "primary_company_ticker": loaded.primary_company_ticker,
        "title": loaded.title,
        "source_type": loaded.source_type.value,
    }
    claims = extractor.extract_claims(clean_text, metadata)

    # 4. Build document payload
    doc_payload = {
        "source_type": loaded.source_type,
        "source_tier": loaded.source_tier,
        "title": loaded.title,
        "url": loaded.url,
        "published_at": loaded.published_at,
        "publisher": loaded.publisher,
        "primary_company_ticker": loaded.primary_company_ticker,
        "raw_text": clean_text,
    }

    # 5. Ingest
    doc_id = ingest_document_with_claims(session, doc_payload, claims, thesis_id=thesis_id)

    # 5b. Post-extraction novelty classification against existing DB claims
    db_claims = session.scalars(
        select(Claim).where(Claim.document_id == doc_id)
    ).all()
    if db_claims:
        classify_novelty(session, db_claims, company_ticker=ticker)
        session.flush()

    # 6. Collect summary
    all_tickers: set[str] = set()
    all_themes: set[str] = set()
    for c in claims:
        all_tickers.update(c.affected_tickers)
        all_themes.update(c.themes)

    return IngestResult(
        document_id=doc_id,
        num_claims=len(claims),
        tickers_linked=sorted(all_tickers),
        themes_linked=sorted(all_themes),
    )
