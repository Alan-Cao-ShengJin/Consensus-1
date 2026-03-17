"""Integration tests: raw fixture -> parse -> extract -> ingest -> DB rows."""
import os
import pytest

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from models import (
    Base, Company, Document, Claim, Theme, Thesis,
    ClaimCompanyLink, ClaimThemeLink, ThesisClaimLink,
    SourceType, SourceTier, ThesisState,
)
from document_loader import load_document, LoadedDocument
from document_parser import parse_document
from claim_extractor import StubClaimExtractor
from ingest_runner import run_ingestion

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


# ---- document_loader tests ----

class TestDocumentLoader:

    def test_load_text_file(self):
        doc = load_document(
            os.path.join(FIXTURES, "nvda_earnings.txt"),
            SourceType.EARNINGS_TRANSCRIPT,
        )
        assert isinstance(doc, LoadedDocument)
        assert "revenue" in doc.raw_text.lower()
        assert doc.source_type == SourceType.EARNINGS_TRANSCRIPT

    def test_load_html_file(self):
        doc = load_document(
            os.path.join(FIXTURES, "nvda_news.html"),
            SourceType.NEWS,
        )
        assert isinstance(doc, LoadedDocument)
        assert "<html>" in doc.raw_text or "NVIDIA" in doc.raw_text


# ---- document_parser tests ----

class TestDocumentParser:

    def test_parse_plain_text(self):
        raw = "  Revenue   grew   20%  \n\n\n\n  year-over-year.  "
        cleaned = parse_document(raw)
        assert cleaned == "Revenue grew 20%\n\nyear-over-year."

    def test_parse_html(self):
        raw = "<html><body><p>Revenue grew &amp; margins expanded.</p></body></html>"
        cleaned = parse_document(raw)
        assert "Revenue grew & margins expanded." in cleaned
        assert "<p>" not in cleaned

    def test_strips_script_and_style(self):
        raw = '<style>body{color:red}</style><script>alert("x")</script><p>Hello</p>'
        cleaned = parse_document(raw, is_html=True)
        assert "alert" not in cleaned
        assert "color:red" not in cleaned
        assert "Hello" in cleaned


# ---- claim_extractor tests ----

class TestStubClaimExtractor:

    def test_extracts_revenue_claim(self):
        extractor = StubClaimExtractor()
        claims = extractor.extract_claims(
            "Revenue grew 93% year-over-year driven by AI demand.",
            {"primary_company_ticker": "NVDA"},
        )
        assert any(c.claim_type.value == "demand" for c in claims)
        assert any("NVDA" in c.affected_tickers for c in claims)

    def test_extracts_margin_claim(self):
        extractor = StubClaimExtractor()
        claims = extractor.extract_claims(
            "Gross margin expanded to 76% from 73%.",
            {"primary_company_ticker": "NVDA"},
        )
        assert any(c.claim_type.value == "margin" for c in claims)

    def test_extracts_guidance_claim(self):
        extractor = StubClaimExtractor()
        claims = extractor.extract_claims(
            "The company raised guidance above consensus for Q1.",
            {"primary_company_ticker": "NVDA"},
        )
        assert any(c.claim_type.value == "guidance" for c in claims)

    def test_fallback_claim_on_generic_text(self):
        extractor = StubClaimExtractor()
        claims = extractor.extract_claims(
            "The company held its annual meeting.",
            {"primary_company_ticker": "NVDA"},
        )
        assert len(claims) >= 1


# ---- end-to-end integration tests ----

class TestIngestionPipelineE2E:

    def test_earnings_transcript_to_db(self, session):
        result = run_ingestion(
            session,
            os.path.join(FIXTURES, "nvda_earnings.txt"),
            SourceType.EARNINGS_TRANSCRIPT,
            ticker="NVDA",
            extractor_type="stub",
        )
        assert result.document_id is not None
        assert result.num_claims >= 1

        # Document created
        doc = session.get(Document, result.document_id)
        assert doc is not None
        assert doc.source_type == SourceType.EARNINGS_TRANSCRIPT
        assert doc.primary_company_ticker == "NVDA"
        assert doc.raw_text is not None

        # Claims created
        claims = session.scalars(
            select(Claim).where(Claim.document_id == doc.id)
        ).all()
        assert len(claims) == result.num_claims

        # Company created
        company = session.get(Company, "NVDA")
        assert company is not None

        # ClaimCompanyLinks created
        links = session.scalars(select(ClaimCompanyLink)).all()
        assert len(links) >= 1
        assert any(l.company_ticker == "NVDA" for l in links)

    def test_html_news_to_db(self, session):
        result = run_ingestion(
            session,
            os.path.join(FIXTURES, "nvda_news.html"),
            SourceType.NEWS,
            ticker="NVDA",
            extractor_type="stub",
        )
        assert result.document_id is not None
        assert result.num_claims >= 1

        doc = session.get(Document, result.document_id)
        # HTML should be stripped in raw_text
        assert "<script>" not in doc.raw_text
        assert "<style>" not in doc.raw_text

    def test_claim_theme_links_created(self, session):
        result = run_ingestion(
            session,
            os.path.join(FIXTURES, "nvda_earnings.txt"),
            SourceType.EARNINGS_TRANSCRIPT,
            ticker="NVDA",
            extractor_type="stub",
        )
        if result.themes_linked:
            theme_links = session.scalars(select(ClaimThemeLink)).all()
            assert len(theme_links) >= 1
            themes = session.scalars(select(Theme)).all()
            assert len(themes) >= 1

    def test_thesis_claim_links_with_thesis_id(self, session):
        # Create company + thesis first
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

        result = run_ingestion(
            session,
            os.path.join(FIXTURES, "nvda_earnings.txt"),
            SourceType.EARNINGS_TRANSCRIPT,
            ticker="NVDA",
            thesis_id=thesis.id,
            extractor_type="stub",
        )

        thesis_links = session.scalars(select(ThesisClaimLink)).all()
        # At least some claims should have thesis_link_type set by stub
        assert len(thesis_links) >= 1
        assert all(l.thesis_id == thesis.id for l in thesis_links)

    def test_no_thesis_links_without_thesis_id(self, session):
        run_ingestion(
            session,
            os.path.join(FIXTURES, "nvda_earnings.txt"),
            SourceType.EARNINGS_TRANSCRIPT,
            ticker="NVDA",
            extractor_type="stub",
        )
        thesis_links = session.scalars(select(ThesisClaimLink)).all()
        assert len(thesis_links) == 0
