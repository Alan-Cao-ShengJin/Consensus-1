from sqlalchemy.orm import Session

from models import Claim, ClaimCompanyLink, ClaimThemeLink, ThesisClaimLink
from crud import get_or_create_company, get_or_create_theme, create_document
from schemas import ExtractedClaim


def ingest_document_with_claims(
    session: Session,
    document_payload: dict,
    extracted_claims: list[ExtractedClaim],
    thesis_id: int | None = None,
) -> int:
    primary_ticker = document_payload.get("primary_company_ticker")
    if primary_ticker:
        get_or_create_company(session, primary_ticker)

    doc = create_document(session, **document_payload)

    for item in extracted_claims:
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
            published_at=item.published_at,
            is_structural=item.is_structural,
            is_ephemeral=item.is_ephemeral,
        )
        session.add(claim)
        session.flush()

        seen_tickers: set[str] = set()
        for ticker in item.affected_tickers:
            ticker_upper = ticker.strip().upper()
            if ticker_upper in seen_tickers:
                continue
            seen_tickers.add(ticker_upper)
            get_or_create_company(session, ticker_upper)
            session.add(
                ClaimCompanyLink(
                    claim_id=claim.id,
                    company_ticker=ticker_upper,
                    relation_type="affects",
                )
            )
        session.flush()  # flush company links before theme queries trigger autoflush

        seen_themes: set[str] = set()
        for theme_name in item.themes:
            if theme_name in seen_themes:
                continue
            seen_themes.add(theme_name)
            theme = get_or_create_theme(session, theme_name)
            session.add(ClaimThemeLink(claim_id=claim.id, theme_id=theme.id))

        if thesis_id and item.thesis_link_type:
            session.add(
                ThesisClaimLink(
                    thesis_id=thesis_id,
                    claim_id=claim.id,
                    link_type=item.thesis_link_type,
                )
            )

    session.commit()
    return doc.id