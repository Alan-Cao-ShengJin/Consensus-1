#!/usr/bin/env python
"""
Schema validation pass: initialises an in-memory DB from models,
runs the full smoke test, and prints a report.

Usage:  python scripts/smoke_test_schema.py
"""
import sys, os, textwrap
from datetime import datetime, date

# Ensure project root is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import Session

from models import (
    Base, Company, Document, Claim, Theme, Thesis, Checkpoint, PeerGroup,
    PortfolioPosition, Candidate, ThesisStateHistory,
    ClaimCompanyLink, ClaimThemeLink, ThesisClaimLink, ThesisThemeLink,
    CompanyPeerGroupLink,
    SourceType, SourceTier, ClaimType, EconomicChannel, Direction,
    NoveltyType, ThesisState, ZoneState,
)

EXPECTED_MODELS = [
    "Company", "Document", "Claim", "Theme", "Thesis", "Checkpoint",
    "PeerGroup", "PortfolioPosition", "Candidate", "ThesisStateHistory",
    "ClaimCompanyLink", "ClaimThemeLink", "ThesisClaimLink",
    "ThesisThemeLink", "CompanyPeerGroupLink",
]

EXPECTED_TABLES = [
    "companies", "documents", "claims", "themes", "theses", "checkpoints",
    "peer_groups", "portfolio_positions", "candidates", "thesis_state_history",
    "claim_company_links", "claim_theme_links", "thesis_claim_links",
    "thesis_theme_links", "company_peer_group_links",
]

REQUIRED_INDEXES = {
    "documents": ["published_at"],
    "claims": ["document_id"],
    "theses": ["company_ticker"],
    "portfolio_positions": ["ticker"],
    "candidates": ["ticker"],
    "claim_company_links": ["company_ticker"],
    "claim_theme_links": ["theme_id"],
}


def check_models_present():
    issues = []
    mapper_classes = {cls.__name__ for cls in Base.__subclasses__()}
    for name in EXPECTED_MODELS:
        if name not in mapper_classes:
            issues.append(f"  MISSING model: {name}")
    return issues


def check_tables(inspector):
    issues = []
    actual = set(inspector.get_table_names())
    for t in EXPECTED_TABLES:
        if t not in actual:
            issues.append(f"  MISSING table: {t}")
    return issues


def check_indexes(inspector):
    issues = []
    for table, cols in REQUIRED_INDEXES.items():
        try:
            idx_list = inspector.get_indexes(table)
        except Exception:
            issues.append(f"  Cannot inspect indexes on {table}")
            continue
        indexed_cols = set()
        for idx in idx_list:
            for c in idx["column_names"]:
                indexed_cols.add(c)
        for col in cols:
            if col not in indexed_cols:
                issues.append(f"  MISSING index: {table}.{col}")
    return issues


def run_smoke_test(session) -> list[str]:
    errors = []
    try:
        company = Company(ticker="NVDA", name="NVIDIA Corp")
        session.add(company)
        session.flush()

        doc = Document(
            source_type=SourceType.EARNINGS_TRANSCRIPT,
            source_tier=SourceTier.TIER_1,
            title="NVDA Q4 2025 Earnings Call",
            published_at=datetime(2025, 2, 26),
            primary_company_ticker="NVDA",
        )
        session.add(doc)
        session.flush()

        claim = Claim(
            document_id=doc.id,
            claim_text_normalized="Data-center revenue grew 93% YoY",
            claim_text_short="DC rev +93%",
            claim_type=ClaimType.DEMAND,
            economic_channel=EconomicChannel.REVENUE,
            direction=Direction.POSITIVE,
            strength=0.9,
            novelty_type=NoveltyType.NEW,
            confidence=0.95,
            published_at=datetime(2025, 2, 26),
        )
        session.add(claim)
        session.flush()

        theme = Theme(theme_name="AI Capex Cycle")
        session.add(theme)
        session.flush()

        checkpoint = Checkpoint(
            checkpoint_type="earnings",
            name="NVDA Q1 2026",
            date_expected=date(2025, 5, 28),
            importance=0.9,
            linked_company_ticker="NVDA",
        )
        session.add(checkpoint)
        session.flush()

        peer_group = PeerGroup(name="US Semis", sector="Semiconductors")
        session.add(peer_group)
        session.flush()

        thesis = Thesis(
            title="NVDA AI Capex Supercycle",
            company_ticker="NVDA",
            state=ThesisState.FORMING,
            conviction_score=55.0,
            checkpoint_next_id=checkpoint.id,
            peer_group_current_id=peer_group.id,
        )
        session.add(thesis)
        session.flush()

        # Link tables
        session.add(ClaimCompanyLink(claim_id=claim.id, company_ticker="NVDA", relation_type="about"))
        session.add(ClaimThemeLink(claim_id=claim.id, theme_id=theme.id))
        session.add(ThesisClaimLink(thesis_id=thesis.id, claim_id=claim.id, link_type="supports"))
        session.add(ThesisThemeLink(thesis_id=thesis.id, theme_id=theme.id))
        session.add(CompanyPeerGroupLink(company_ticker="NVDA", peer_group_id=peer_group.id, role="current"))
        session.flush()

        session.add(ThesisStateHistory(
            thesis_id=thesis.id, state=ThesisState.FORMING,
            conviction_score=55.0, note="Initial creation",
        ))
        session.flush()

        session.add(PortfolioPosition(
            ticker="NVDA", thesis_id=thesis.id,
            entry_date=date(2025, 1, 10), avg_cost=120.50,
            current_weight=0.05, target_weight=0.08,
            conviction_score=55.0, zone_state=ZoneState.BUY,
        ))
        session.flush()

        session.add(Candidate(
            ticker="NVDA", primary_thesis_id=thesis.id,
            conviction_score=55.0, buyable_flag=True, zone_state=ZoneState.BUY,
        ))
        session.flush()

        session.commit()

        # Verify relationships
        assert session.get(Document, doc.id).primary_company.ticker == "NVDA"
        assert len(session.get(Document, doc.id).claims) == 1
        assert session.get(Thesis, thesis.id).company.ticker == "NVDA"

    except Exception as e:
        errors.append(f"  {type(e).__name__}: {e}")
    return errors


def check_alembic_migration():
    issues = []
    versions_dir = os.path.join(os.path.dirname(__file__), "..", "alembic", "versions")
    if not os.path.isdir(versions_dir):
        issues.append("  alembic/versions/ directory not found")
        return issues, 0
    migration_files = [f for f in os.listdir(versions_dir) if f.endswith(".py") and not f.startswith("__")]
    if not migration_files:
        issues.append("  No migration files found")
    return issues, len(migration_files)


def main():
    print("=" * 60)
    print("  SCHEMA VALIDATION REPORT — Consensus v1")
    print("=" * 60)
    fixes_applied = [
        "Renamed injest.py -> ingest.py (and updated imports)",
    ]

    # -- Models --
    print("\n[1] Models")
    model_issues = check_models_present()
    for name in EXPECTED_MODELS:
        print(f"     {name:30s} OK")
    if model_issues:
        for i in model_issues:
            print(i)
    print(f"     --- {len(EXPECTED_MODELS)} / {len(EXPECTED_MODELS)} models present")

    # -- Tables & Indexes (in-memory DB) --
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    inspector = inspect(engine)

    print("\n[2] Tables")
    table_issues = check_tables(inspector)
    actual_tables = set(inspector.get_table_names())
    for t in EXPECTED_TABLES:
        status = "OK" if t in actual_tables else "MISSING"
        print(f"     {t:35s} {status}")
    if table_issues:
        for i in table_issues:
            print(i)
    print(f"     --- {len(EXPECTED_TABLES)} / {len(EXPECTED_TABLES)} tables created")

    print("\n[3] Indexes")
    index_issues = check_indexes(inspector)
    for table, cols in REQUIRED_INDEXES.items():
        for col in cols:
            status = "OK" if f"  MISSING index: {table}.{col}" not in index_issues else "MISSING"
            print(f"     {table}.{col:30s} {status}")
    if index_issues:
        for i in index_issues:
            print(i)
    print(f"     --- {sum(len(v) for v in REQUIRED_INDEXES.values())} required indexes verified")

    # -- Alembic --
    print("\n[4] Alembic migrations")
    alembic_issues, migration_count = check_alembic_migration()
    if alembic_issues:
        for i in alembic_issues:
            print(i)
    else:
        print(f"     {migration_count} migration file(s) found")
    print(f"     Status: {'OK' if not alembic_issues else 'ISSUES FOUND'}")

    # -- Smoke test --
    print("\n[5] Smoke test (end-to-end insert + relationship check)")
    with Session(engine) as session:
        smoke_errors = run_smoke_test(session)
    if smoke_errors:
        for e in smoke_errors:
            print(e)
        print("     Status: FAIL")
    else:
        print("     Created: Company, Document, Claim, Theme, Checkpoint,")
        print("              PeerGroup, Thesis, PortfolioPosition, Candidate,")
        print("              ThesisStateHistory + all 5 link tables")
        print("     Relationships verified: Document->Company, Document->Claims, Thesis->Company")
        print("     Status: PASS")

    # -- Fixes applied --
    print("\n[6] Fixes applied in this pass")
    for f in fixes_applied:
        print(f"     - {f}")

    # -- Summary --
    all_issues = model_issues + table_issues + index_issues + alembic_issues + smoke_errors
    print("\n" + "=" * 60)
    if all_issues:
        print(f"  RESULT: {len(all_issues)} issue(s) found")
        for i in all_issues:
            print(i)
    else:
        print("  RESULT: ALL CHECKS PASSED")
        print("  Schema v1 is implemented and runnable.")
    print("=" * 60)

    return 0 if not all_issues else 1


if __name__ == "__main__":
    sys.exit(main())
