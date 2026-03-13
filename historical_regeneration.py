"""Historical regeneration pipeline: time-ordered thesis reconstruction.

Processes historical documents in chronological order, performs claim
extraction / novelty classification / thesis updates incrementally,
and builds thesis state that reflects only information available at each
point in time.

Key invariant: for any review date, the thesis state reflects only
information published on or before that date.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session, sessionmaker

from models import (
    Base, Company, Document, Claim, Thesis, ThesisStateHistory,
    Candidate, Price, Checkpoint, ThesisState,
    ClaimCompanyLink,
)
from historical_eval_config import HistoricalEvalConfig
from crud import get_or_create_company

logger = logging.getLogger(__name__)


@dataclass
class RegenerationStepResult:
    """Result of processing one document batch (one timestamp)."""
    process_date: date
    documents_processed: int = 0
    claims_created: int = 0
    theses_updated: int = 0
    thesis_changes: list[dict] = field(default_factory=list)


@dataclass
class RegenerationResult:
    """Full result of a historical regeneration run."""
    config: HistoricalEvalConfig
    db_path: str = ""
    total_documents: int = 0
    total_claims: int = 0
    total_thesis_updates: int = 0
    total_state_changes: int = 0
    total_state_flips: int = 0
    steps: list[RegenerationStepResult] = field(default_factory=list)
    data_coverage: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "db_path": self.db_path,
            "total_documents": self.total_documents,
            "total_claims": self.total_claims,
            "total_thesis_updates": self.total_thesis_updates,
            "total_state_changes": self.total_state_changes,
            "total_state_flips": self.total_state_flips,
            "data_coverage": self.data_coverage,
            "warnings": self.warnings,
            "steps_count": len(self.steps),
        }


def create_regeneration_db(config: HistoricalEvalConfig) -> tuple[Session, str]:
    """Create a fresh SQLite database for historical regeneration.

    Returns (session, db_path). The session has a `_engine` attribute
    for proper cleanup on Windows (dispose engine to release file locks).
    """
    os.makedirs(config.output_dir, exist_ok=True)
    db_path = os.path.join(config.output_dir, f"{config.run_id}_regen.db")

    if config.rebuild_from_scratch and os.path.exists(db_path):
        os.remove(db_path)

    engine = create_engine(f"sqlite:///{db_path}", echo=False)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=True, expire_on_commit=False)
    session = SessionLocal()
    session._engine = engine  # stash for cleanup

    return session, db_path


def copy_prices_to_regen_db(
    source_session: Session,
    regen_session: Session,
    tickers: list[str],
    start_date: date,
    end_date: date,
) -> int:
    """Copy price data from source DB to regeneration DB.

    Returns count of rows copied.
    """
    prices = source_session.scalars(
        select(Price).where(
            Price.ticker.in_(tickers),
            Price.date >= start_date,
            Price.date <= end_date,
        )
    ).all()

    count = 0
    for p in prices:
        get_or_create_company(regen_session, p.ticker)
        existing = regen_session.scalars(
            select(Price).where(Price.ticker == p.ticker, Price.date == p.date)
        ).first()
        if not existing:
            regen_session.add(Price(
                ticker=p.ticker, date=p.date,
                open=p.open, high=p.high, low=p.low,
                close=p.close, adj_close=p.adj_close,
                volume=p.volume, source=p.source,
            ))
            count += 1

    regen_session.flush()
    return count


def copy_documents_to_regen_db(
    source_session: Session,
    regen_session: Session,
    tickers: list[str],
    start_date: date,
    end_date: date,
) -> list[int]:
    """Copy documents from source DB to regen DB without claims.

    Documents are copied but claims are NOT copied — they will be
    re-extracted during regeneration to ensure clean state.

    Returns list of source document IDs copied.
    """
    start_dt = datetime(start_date.year, start_date.month, start_date.day)
    end_dt = datetime(end_date.year, end_date.month, end_date.day, 23, 59, 59)

    docs = source_session.scalars(
        select(Document).where(
            Document.primary_company_ticker.in_(tickers),
            Document.published_at >= start_dt,
            Document.published_at <= end_dt,
        ).order_by(Document.published_at.asc())
    ).all()

    source_ids = []
    for doc in docs:
        get_or_create_company(regen_session, doc.primary_company_ticker)
        regen_session.add(Document(
            source_type=doc.source_type,
            source_tier=doc.source_tier,
            title=doc.title,
            url=doc.url,
            published_at=doc.published_at,
            publisher=doc.publisher,
            primary_company_ticker=doc.primary_company_ticker,
            raw_text=doc.raw_text,
            hash=doc.hash,
            source_key=doc.source_key,
            external_id=doc.external_id,
            ingested_at=doc.ingested_at,
        ))
        source_ids.append(doc.id)

    regen_session.flush()
    return source_ids


def run_regeneration(
    source_session: Session,
    config: HistoricalEvalConfig,
) -> RegenerationResult:
    """Run full historical thesis regeneration.

    Steps:
      1. Create fresh regeneration DB
      2. Copy price data from source DB
      3. Copy documents from source DB (without claims)
      4. Process documents in chronological order:
         a. Extract claims
         b. Classify novelty (against only prior claims)
         c. Update thesis state incrementally
      5. Record thesis state history at each step

    Returns RegenerationResult with the regen DB path for downstream evaluation.
    """
    result = RegenerationResult(config=config)

    # 1. Create fresh DB
    regen_session, db_path = create_regeneration_db(config)
    result.db_path = db_path

    tickers = config.effective_tickers()

    try:
        # Ensure all companies exist in regen DB
        for ticker in tickers:
            get_or_create_company(regen_session, ticker)
        # Also create benchmark company
        if config.benchmark_ticker:
            get_or_create_company(regen_session, config.benchmark_ticker)
        regen_session.flush()

        # 2. Copy price data
        all_tickers = tickers + ([config.benchmark_ticker] if config.benchmark_ticker and config.benchmark_ticker not in tickers else [])
        price_count = copy_prices_to_regen_db(
            source_session, regen_session, all_tickers,
            config.backfill_start, config.backfill_end,
        )
        logger.info("Copied %d price rows to regeneration DB", price_count)

        # 3. Get documents from source DB in chronological order
        start_dt = datetime(config.backfill_start.year, config.backfill_start.month, config.backfill_start.day)
        end_dt = datetime(config.backfill_end.year, config.backfill_end.month, config.backfill_end.day, 23, 59, 59)

        source_docs = source_session.scalars(
            select(Document).where(
                Document.primary_company_ticker.in_(tickers),
                Document.published_at >= start_dt,
                Document.published_at <= end_dt,
                Document.raw_text.isnot(None),
            ).order_by(Document.published_at.asc(), Document.id.asc())
        ).all()

        if not source_docs:
            result.warnings.append(
                f"No documents found in source DB for tickers {tickers[:5]}... "
                f"between {config.backfill_start} and {config.backfill_end}"
            )
            regen_session.commit()
            return result

        logger.info("Found %d source documents to process chronologically", len(source_docs))

        # 4. Process each document in chronological order
        # Group by date for step tracking
        current_date = None
        current_step = None

        for doc in source_docs:
            doc_date = doc.published_at.date() if doc.published_at else config.backfill_start

            if doc_date != current_date:
                if current_step:
                    result.steps.append(current_step)
                current_date = doc_date
                current_step = RegenerationStepResult(process_date=current_date)

            # Insert document into regen DB
            ticker = doc.primary_company_ticker
            get_or_create_company(regen_session, ticker)

            regen_doc = Document(
                source_type=doc.source_type,
                source_tier=doc.source_tier,
                title=doc.title,
                url=doc.url,
                published_at=doc.published_at,
                publisher=doc.publisher,
                primary_company_ticker=ticker,
                raw_text=doc.raw_text,
                hash=doc.hash,
                source_key=doc.source_key,
                external_id=doc.external_id,
                ingested_at=doc.published_at or doc.ingested_at,
            )
            regen_session.add(regen_doc)
            regen_session.flush()

            # Extract claims (this also runs novelty classification against
            # only claims that exist in regen DB so far — which is exactly
            # the as-of-date set)
            try:
                claim_ids = _extract_claims_for_doc(
                    regen_session, regen_doc, ticker, config.use_llm,
                )
            except Exception as e:
                logger.warning(
                    "Claim extraction failed for doc %s (%s): %s — skipping",
                    regen_doc.id, ticker, e,
                )
                result.warnings.append(
                    f"Claim extraction failed for {ticker} doc {regen_doc.id}: {e}"
                )
                claim_ids = []

            current_step.documents_processed += 1
            current_step.claims_created += len(claim_ids)
            result.total_documents += 1
            result.total_claims += len(claim_ids)

            # Update thesis if claims were extracted
            if claim_ids:
                thesis_result = _update_thesis_incrementally(
                    regen_session, ticker, claim_ids,
                    config.use_llm, config.memory_enabled,
                    doc_published_at=doc.published_at,
                )
                if thesis_result:
                    # Back-date thesis state history to document's published_at
                    # so replay as-of-date queries work correctly
                    doc_timestamp = doc.published_at or doc.ingested_at
                    if doc_timestamp:
                        _backdate_latest_thesis_history(
                            regen_session, ticker, doc_timestamp,
                        )

                    current_step.theses_updated += 1
                    current_step.thesis_changes.append(thesis_result)
                    result.total_thesis_updates += 1

                    if thesis_result.get("state_changed"):
                        result.total_state_changes += 1
                    if thesis_result.get("state_flipped"):
                        result.total_state_flips += 1

            regen_session.flush()

        # Append final step
        if current_step:
            result.steps.append(current_step)

        # Create candidates for all tickers with theses
        _create_candidates(regen_session, tickers)

        # Compute data coverage stats
        result.data_coverage = _compute_data_coverage(
            regen_session, tickers, config,
        )

        regen_session.commit()

    except Exception as e:
        logger.error("Regeneration failed: %s", e)
        result.warnings.append(f"Regeneration error: {e}")
        regen_session.rollback()
        raise
    finally:
        regen_session.close()
        if hasattr(regen_session, '_engine'):
            regen_session._engine.dispose()

    logger.info(
        "Regeneration complete: %d docs, %d claims, %d thesis updates, "
        "%d state changes, %d state flips",
        result.total_documents, result.total_claims,
        result.total_thesis_updates, result.total_state_changes,
        result.total_state_flips,
    )

    return result


def _extract_claims_for_doc(
    session: Session,
    doc: Document,
    ticker: str,
    use_llm: bool,
) -> list[int]:
    """Extract claims from a document in the regeneration DB.

    Uses the same ingestion path as production but on the regen DB,
    so novelty classification only sees claims that exist so far.
    """
    if not doc.raw_text:
        return []

    try:
        from claim_extractor import StubClaimExtractor, LLMClaimExtractor
        extractor = LLMClaimExtractor() if use_llm else StubClaimExtractor()
    except ImportError:
        return []

    metadata = {
        "primary_company_ticker": ticker,
        "title": doc.title or "",
        "source_type": doc.source_type.value,
    }
    extracted = extractor.extract_claims(doc.raw_text, metadata)

    claim_ids = []
    for item in extracted:
        claim = Claim(
            document_id=doc.id,
            claim_text_normalized=item.claim_text_normalized,
            claim_text_short=item.claim_text_short,
            claim_type=item.claim_type,
            economic_channel=item.economic_channel,
            direction=item.direction,
            strength=item.strength,
            time_horizon=item.time_horizon,
            novelty_type=item.novelty_type,
            confidence=item.confidence,
            published_at=item.published_at or doc.published_at,
            is_structural=item.is_structural,
            is_ephemeral=item.is_ephemeral,
            source_excerpt=item.source_excerpt,
        )
        session.add(claim)
        session.flush()
        claim_ids.append(claim.id)

        # Create company link
        get_or_create_company(session, ticker)
        session.add(ClaimCompanyLink(
            claim_id=claim.id, company_ticker=ticker, relation_type="about",
        ))

    session.flush()

    # Novelty classification against existing claims in regen DB
    if claim_ids:
        try:
            from novelty_classifier import classify_novelty
            db_claims = session.scalars(
                select(Claim).where(Claim.id.in_(claim_ids))
            ).all()
            if db_claims:
                novelty_results = classify_novelty(session, db_claims, company_ticker=ticker)
                # Apply contradiction metadata
                from models import NoveltyType
                for claim_id, novelty_type, _sim, prior_claim_id in novelty_results:
                    if novelty_type == NoveltyType.CONFLICTING and prior_claim_id is not None:
                        claim = session.get(Claim, claim_id)
                        if claim:
                            claim.is_contradicted = True
                            claim.contradicts_claim_id = prior_claim_id
                session.flush()
        except Exception as e:
            logger.warning("Novelty classification failed (non-fatal): %s", e)

    return claim_ids


def _update_thesis_incrementally(
    session: Session,
    ticker: str,
    claim_ids: list[int],
    use_llm: bool,
    memory_enabled: bool,
    doc_published_at: Optional[datetime] = None,
) -> Optional[dict]:
    """Update or create thesis for a ticker based on new claims.

    If no thesis exists, creates one in FORMING state.
    """
    # Find or create thesis
    thesis = session.scalars(
        select(Thesis).where(
            Thesis.company_ticker == ticker,
            Thesis.status_active == True,
        ).order_by(Thesis.updated_at.desc()).limit(1)
    ).first()

    if not thesis:
        thesis = Thesis(
            title=f"{ticker} thesis",
            company_ticker=ticker,
            state=ThesisState.FORMING,
            conviction_score=50.0,
            status_active=True,
        )
        session.add(thesis)
        session.flush()

        # Record initial state (created_at will be back-dated by caller)
        session.add(ThesisStateHistory(
            thesis_id=thesis.id,
            state=thesis.state,
            conviction_score=thesis.conviction_score,
            note="Initial thesis created during regeneration",
        ))
        session.flush()

    before_state = thesis.state
    before_score = thesis.conviction_score or 50.0

    try:
        from thesis_update_service import update_thesis_from_claims
        result = update_thesis_from_claims(
            session, thesis.id, claim_ids, use_llm=use_llm,
            reference_time=doc_published_at,
        )

        after_state = ThesisState(result["after_state"])
        after_score = result["after_score"]

        # Determine state change / flip
        state_changed = before_state != after_state
        bullish_states = {ThesisState.FORMING, ThesisState.STRENGTHENING, ThesisState.STABLE}
        bearish_states = {ThesisState.WEAKENING, ThesisState.BROKEN, ThesisState.PROBATION}
        state_flipped = (
            (before_state in bullish_states and after_state in bearish_states)
            or (before_state in bearish_states and after_state in bullish_states)
        )

        return {
            "ticker": ticker,
            "before_state": before_state.value,
            "after_state": after_state.value,
            "before_score": before_score,
            "after_score": after_score,
            "state_changed": state_changed,
            "state_flipped": state_flipped,
            "claims_processed": len(claim_ids),
        }

    except Exception as e:
        logger.warning("Thesis update failed for %s: %s", ticker, e)
        return None


def _backdate_latest_thesis_history(
    session: Session,
    ticker: str,
    doc_timestamp: datetime,
) -> None:
    """Back-date ThesisStateHistory entries for a ticker to a document timestamp.

    During regeneration, ThesisStateHistory entries get created with utcnow()
    timestamps. For historical replay to work correctly with as-of-date
    queries, we need to set created_at to the source document's published_at.

    Back-dates ALL entries that still have future (wall-clock) timestamps,
    including the initial FORMING entry created when the thesis was first
    instantiated. Also back-dates the Thesis.created_at itself so the
    fallback path in _get_thesis_state_as_of works correctly.
    """
    thesis = session.scalars(
        select(Thesis).where(
            Thesis.company_ticker == ticker,
            Thesis.status_active == True,
        ).limit(1)
    ).first()
    if not thesis:
        return

    # Back-date all entries that have timestamps after doc_timestamp
    # (i.e., wall-clock timestamps from utcnow() during regeneration)
    entries = session.scalars(
        select(ThesisStateHistory).where(
            ThesisStateHistory.thesis_id == thesis.id,
            ThesisStateHistory.created_at > doc_timestamp,
        )
    ).all()
    for entry in entries:
        entry.created_at = doc_timestamp

    # Also back-date the Thesis.created_at for the fallback path
    if thesis.created_at and thesis.created_at > doc_timestamp:
        thesis.created_at = doc_timestamp

    session.flush()


def _create_candidates(session: Session, tickers: list[str]) -> None:
    """Create candidate entries for tickers that have active theses.

    Uses the earliest document published_at for each ticker as created_at
    so that replay temporal filtering includes candidates at the correct
    historical dates (not wall-clock time).
    """
    for ticker in tickers:
        thesis = session.scalars(
            select(Thesis).where(
                Thesis.company_ticker == ticker,
                Thesis.status_active == True,
            ).limit(1)
        ).first()

        if thesis:
            existing = session.scalars(
                select(Candidate).where(Candidate.ticker == ticker)
            ).first()
            if not existing:
                # Use earliest document date for this ticker as created_at
                earliest_doc = session.scalars(
                    select(Document).where(
                        Document.primary_company_ticker == ticker,
                    ).order_by(Document.published_at.asc()).limit(1)
                ).first()
                cand_created_at = (
                    earliest_doc.published_at
                    if earliest_doc and earliest_doc.published_at
                    else datetime.utcnow()
                )
                session.add(Candidate(
                    ticker=ticker,
                    primary_thesis_id=thesis.id,
                    conviction_score=thesis.conviction_score,
                    buyable_flag=True,
                    created_at=cand_created_at,
                ))
    session.flush()


def _compute_data_coverage(
    session: Session,
    tickers: list[str],
    config: HistoricalEvalConfig,
) -> dict:
    """Compute data coverage statistics for the regeneration DB."""
    doc_count = session.scalar(
        select(func.count(Document.id)).where(
            Document.primary_company_ticker.in_(tickers)
        )
    ) or 0

    claim_count = session.scalar(
        select(func.count(Claim.id))
    ) or 0

    price_count = session.scalar(
        select(func.count(Price.id)).where(
            Price.ticker.in_(tickers)
        )
    ) or 0

    thesis_count = session.scalar(
        select(func.count(Thesis.id)).where(
            Thesis.company_ticker.in_(tickers)
        )
    ) or 0

    # Documents by source type
    from sqlalchemy import case
    doc_by_type = {}
    for doc in session.scalars(select(Document).where(Document.primary_company_ticker.in_(tickers))):
        st = doc.source_type.value if doc.source_type else "unknown"
        doc_by_type[st] = doc_by_type.get(st, 0) + 1

    # Price coverage: count tickers with at least some price data
    tickers_with_prices = session.scalars(
        select(Price.ticker).where(Price.ticker.in_(tickers)).distinct()
    ).all()

    return {
        "total_documents": doc_count,
        "total_claims": claim_count,
        "total_prices": price_count,
        "total_theses": thesis_count,
        "documents_by_source_type": doc_by_type,
        "tickers_with_prices": len(tickers_with_prices),
        "tickers_without_prices": len(set(tickers) - set(tickers_with_prices)),
        "tickers_total": len(tickers),
    }


def open_regeneration_db(db_path: str) -> Session:
    """Open an existing regeneration DB for evaluation.

    The returned session has a `_engine` attribute. Call
    `session._engine.dispose()` after `session.close()` to release
    file locks on Windows.
    """
    engine = create_engine(f"sqlite:///{db_path}", echo=False)
    SessionLocal = sessionmaker(bind=engine, autoflush=True, expire_on_commit=False)
    session = SessionLocal()
    session._engine = engine
    return session


def close_regeneration_db(session: Session) -> None:
    """Close a regeneration DB session and dispose its engine."""
    session.close()
    if hasattr(session, '_engine'):
        session._engine.dispose()
