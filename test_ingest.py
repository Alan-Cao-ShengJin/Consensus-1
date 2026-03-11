import pytest
from datetime import datetime

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from models import (
    Base, Claim, ClaimCompanyLink, ClaimThemeLink, Company,
    Document, Theme, ThesisClaimLink, Thesis, ThesisState,
    SourceType, SourceTier, ClaimType, EconomicChannel,
    Direction, NoveltyType,
)
from schemas import ExtractedClaim
from injest import ingest_document_with_claims


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _make_doc_payload(**overrides):
    defaults = dict(
        source_type=SourceType.NEWS,
        source_tier=SourceTier.TIER_1,
        title="Test Article",
        published_at=datetime(2025, 1, 15),
    )
    defaults.update(overrides)
    return defaults


def _make_claim(**overrides):
    defaults = dict(
        claim_text_normalized="Revenue grew 20% YoY",
        claim_text_short="Revenue +20%",
        claim_type=ClaimType.DEMAND,
        economic_channel=EconomicChannel.REVENUE,
        direction=Direction.POSITIVE,
        strength=0.8,
        novelty_type=NoveltyType.NEW,
        confidence=0.9,
        affected_tickers=[],
        themes=[],
        thesis_link_type=None,
    )
    defaults.update(overrides)
    return ExtractedClaim(**defaults)


class TestIngestDocumentWithClaims:

    def test_creates_document(self, session):
        doc_id = ingest_document_with_claims(session, _make_doc_payload(), [])
        doc = session.get(Document, doc_id)
        assert doc is not None
        assert doc.title == "Test Article"
        assert doc.source_type == SourceType.NEWS

    def test_creates_claims(self, session):
        claims = [_make_claim(), _make_claim(claim_text_normalized="Margins expanding")]
        doc_id = ingest_document_with_claims(session, _make_doc_payload(), claims)
        db_claims = session.scalars(select(Claim).where(Claim.document_id == doc_id)).all()
        assert len(db_claims) == 2

    def test_creates_company_on_primary_ticker(self, session):
        payload = _make_doc_payload(primary_company_ticker="AAPL")
        ingest_document_with_claims(session, payload, [])
        company = session.get(Company, "AAPL")
        assert company is not None

    def test_links_affected_tickers(self, session):
        claim = _make_claim(affected_tickers=["MSFT", "GOOGL"])
        doc_id = ingest_document_with_claims(session, _make_doc_payload(), [claim])
        links = session.scalars(select(ClaimCompanyLink)).all()
        assert len(links) == 2
        assert {l.company_ticker for l in links} == {"MSFT", "GOOGL"}

    def test_links_themes(self, session):
        claim = _make_claim(themes=["AI Spending", "Cloud Growth"])
        ingest_document_with_claims(session, _make_doc_payload(), [claim])
        theme_links = session.scalars(select(ClaimThemeLink)).all()
        assert len(theme_links) == 2
        themes = session.scalars(select(Theme)).all()
        assert {t.theme_name for t in themes} == {"AI Spending", "Cloud Growth"}

    def test_links_thesis(self, session):
        # Create a company and thesis first
        company = Company(ticker="NVDA", name="NVIDIA")
        session.add(company)
        session.flush()
        thesis = Thesis(
            title="AI Capex Thesis",
            company_ticker="NVDA",
            state=ThesisState.FORMING,
        )
        session.add(thesis)
        session.flush()

        claim = _make_claim(thesis_link_type="supports")
        ingest_document_with_claims(
            session, _make_doc_payload(), [claim], thesis_id=thesis.id
        )
        links = session.scalars(select(ThesisClaimLink)).all()
        assert len(links) == 1
        assert links[0].link_type == "supports"
        assert links[0].thesis_id == thesis.id

    def test_no_thesis_link_without_thesis_id(self, session):
        claim = _make_claim(thesis_link_type="supports")
        ingest_document_with_claims(session, _make_doc_payload(), [claim])
        links = session.scalars(select(ThesisClaimLink)).all()
        assert len(links) == 0

    def test_no_thesis_link_without_link_type(self, session):
        company = Company(ticker="NVDA", name="NVIDIA")
        session.add(company)
        session.flush()
        thesis = Thesis(
            title="Test", company_ticker="NVDA", state=ThesisState.FORMING
        )
        session.add(thesis)
        session.flush()

        claim = _make_claim(thesis_link_type=None)
        ingest_document_with_claims(
            session, _make_doc_payload(), [claim], thesis_id=thesis.id
        )
        links = session.scalars(select(ThesisClaimLink)).all()
        assert len(links) == 0

    def test_deduplicates_companies(self, session):
        payload = _make_doc_payload(primary_company_ticker="AAPL")
        claim = _make_claim(affected_tickers=["AAPL"])
        ingest_document_with_claims(session, payload, [claim])
        companies = session.scalars(select(Company)).all()
        assert len(companies) == 1

    def test_deduplicates_themes(self, session):
        claims = [
            _make_claim(themes=["AI Spending"]),
            _make_claim(themes=["AI Spending"]),
        ]
        ingest_document_with_claims(session, _make_doc_payload(), claims)
        themes = session.scalars(select(Theme)).all()
        assert len(themes) == 1
