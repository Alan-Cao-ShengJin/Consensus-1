"""Compare strict vs non-strict replay runs over the same data."""
from datetime import date, datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from models import (
    Base, Company, Thesis, ThesisState, ThesisStateHistory,
    Candidate, Price, Checkpoint, ZoneState,
    Document, SourceType, SourceTier, Claim, ClaimType,
    EconomicChannel, Direction, NoveltyType, ClaimCompanyLink,
)
from replay_runner import run_replay, format_replay_text

engine = create_engine("sqlite://")
Base.metadata.create_all(engine)

START = date(2025, 6, 1)
END = date(2025, 9, 28)


with Session(engine) as s:
    # Shared document for claims
    doc = Document(
        source_type=SourceType.NEWS, source_tier=SourceTier.TIER_2,
        url="http://test.com/doc", title="Test",
    )
    s.add(doc)
    s.flush()
    doc_id = doc.id

    tickers = ["AAPL", "NVDA", "MSFT", "GOOG", "TSLA"]

    for t in tickers:
        s.add(Company(ticker=t, name=f"{t} Inc", sector="Tech"))
        s.flush()

        thesis = Thesis(
            company_ticker=t, title=f"{t} thesis", thesis_type="long",
            state=ThesisState.STRENGTHENING,
            conviction_score=80.0, valuation_gap_pct=30.0, base_case_rerating=20.0,
        )
        s.add(thesis)
        s.flush()

        # --- Candidates: mixed temporal provenance ---
        cand = Candidate(
            ticker=t, primary_thesis_id=thesis.id,
            conviction_score=80.0, zone_state=ZoneState.BUY,
        )
        if t in ("AAPL", "NVDA"):
            cand.created_at = datetime(2025, 5, 1)      # before replay
        elif t == "MSFT":
            cand.created_at = datetime(2025, 7, 15)      # mid-replay
        elif t == "GOOG":
            cand.created_at = None                        # no provenance
        elif t == "TSLA":
            cand.created_at = datetime(2025, 12, 1)       # after replay end
        s.add(cand)
        s.flush()

        # --- Prices: daily with slow upward drift ---
        base_price = {"AAPL": 180, "NVDA": 120, "MSFT": 400, "GOOG": 170, "TSLA": 250}[t]
        d = date(2025, 5, 1)
        while d <= date(2025, 10, 31):
            drift = (d - date(2025, 5, 1)).days * 0.05
            noise = ((hash(f"{t}{d}") % 20) - 10) * 0.5
            s.add(Price(ticker=t, date=d, close=round(base_price + drift + noise, 2)))
            d += timedelta(days=1)
        s.flush()

        # --- ThesisStateHistory: early records lack valuation (pre-8.1 gap) ---
        s.add(ThesisStateHistory(
            thesis_id=thesis.id, state=ThesisState.STRENGTHENING,
            conviction_score=75.0, note="initial - no valuation",
            created_at=datetime(2025, 5, 15),
            valuation_gap_pct=None, base_case_rerating=None,
        ))
        # Mid-replay: AAPL/NVDA/MSFT get valuation history
        if t in ("AAPL", "NVDA", "MSFT"):
            s.add(ThesisStateHistory(
                thesis_id=thesis.id, state=ThesisState.STRENGTHENING,
                conviction_score=80.0, note="with valuation",
                created_at=datetime(2025, 7, 20),
                valuation_gap_pct=30.0, base_case_rerating=20.0,
            ))
        # GOOG/TSLA: no valuation history at all
        s.flush()

        # --- Checkpoints: mixed provenance ---
        if t in ("AAPL", "NVDA"):
            cp = Checkpoint(
                checkpoint_type="earnings", name=f"{t} Q3",
                date_expected=date(2025, 7, 25),
                linked_company_ticker=t, status="pending",
            )
            cp.created_at = datetime(2025, 6, 1)  # clean provenance
            s.add(cp)
        if t == "MSFT":
            cp = Checkpoint(
                checkpoint_type="earnings", name=f"{t} Q3",
                date_expected=date(2025, 8, 15),
                linked_company_ticker=t, status="pending",
            )
            cp.created_at = None  # no provenance
            s.add(cp)
        if t == "GOOG":
            cp = Checkpoint(
                checkpoint_type="earnings", name=f"{t} Q3",
                date_expected=date(2025, 8, 1),
                linked_company_ticker=t, status="pending",
            )
            cp.created_at = None  # no provenance
            s.add(cp)
        s.flush()

        # --- Novel claims every week to trigger initiations ---
        if t != "TSLA":  # TSLA has future created_at, should never enter
            review_d = START
            while review_d <= END:
                for offset in [2, 5]:
                    claim_date = datetime.combine(
                        review_d - timedelta(days=offset), datetime.min.time()
                    )
                    claim = Claim(
                        document_id=doc_id,
                        claim_text_normalized=f"{t} bullish signal {review_d}",
                        claim_type=ClaimType.DEMAND,
                        economic_channel=EconomicChannel.REVENUE,
                        direction=Direction.POSITIVE,
                        published_at=claim_date,
                        novelty_type=NoveltyType.NEW,
                    )
                    s.add(claim)
                    s.flush()
                    s.add(ClaimCompanyLink(
                        claim_id=claim.id, company_ticker=t, relation_type="about",
                    ))
                    s.flush()
                review_d += timedelta(days=7)

    # ===== RUN BOTH MODES =====
    r_ns, p_ns, m_ns = run_replay(
        s, start_date=START, end_date=END,
        cadence_days=7, initial_cash=1_000_000.0, strict_replay=False,
    )
    r_st, p_st, m_st = run_replay(
        s, start_date=START, end_date=END,
        cadence_days=7, initial_cash=1_000_000.0, strict_replay=True,
    )

    # ===== OUTPUT =====
    print("=" * 80)
    print("NON-STRICT REPLAY")
    print("=" * 80)
    print(format_replay_text(r_ns, p_ns, m_ns))
    print()
    print("=" * 80)
    print("STRICT REPLAY")
    print("=" * 80)
    print(format_replay_text(r_st, p_st, m_st))
    print()

    print("=" * 80)
    print("DELTA: NON-STRICT vs STRICT")
    print("=" * 80)
    print(f"  Reviews:             {r_ns.total_reviews} vs {r_st.total_reviews}")
    print(f"  Recommendations:     {r_ns.total_recommendations} vs {r_st.total_recommendations}")
    print(f"  Trades applied:      {r_ns.total_trades_applied} vs {r_st.total_trades_applied}")
    print(f"  Trades skipped:      {r_ns.total_trades_skipped} vs {r_st.total_trades_skipped}")
    print(f"  Purity level:        {r_ns.purity_level} vs {r_st.purity_level}")
    print(f"  Impure candidates:   {r_ns.total_impure_candidates} vs {r_st.total_impure_candidates}")
    print(f"  Impure valuations:   {r_ns.total_impure_valuations} vs {r_st.total_impure_valuations}")
    print(f"  Impure checkpoints:  {r_ns.total_impure_checkpoints} vs {r_st.total_impure_checkpoints}")
    print(f"  Skipped (strict):    {r_ns.total_skipped_impure} vs {r_st.total_skipped_impure}")
    print(f"  Integrity warnings:  {len(r_ns.integrity_warnings)} vs {len(r_st.integrity_warnings)}")
    print(f"  Total return:        {m_ns.total_return_pct:+.2f}% vs {m_st.total_return_pct:+.2f}%")
    print(f"  Max drawdown:        {m_ns.max_drawdown_pct:.2f}% vs {m_st.max_drawdown_pct:.2f}%")
    print(f"  Initiations:         {m_ns.total_initiations} vs {m_st.total_initiations}")
    print(f"  Exits:               {m_ns.total_exits} vs {m_st.total_exits}")

    if p_ns.snapshots and p_st.snapshots:
        print(f"  Final value:         ${p_ns.snapshots[-1].total_value:,.2f} vs ${p_st.snapshots[-1].total_value:,.2f}")
        print(f"  Final positions:     {p_ns.snapshots[-1].num_positions} vs {p_st.snapshots[-1].num_positions}")
        print(f"  Final cash:          ${p_ns.snapshots[-1].cash:,.2f} vs ${p_st.snapshots[-1].cash:,.2f}")
        print()
        print("NON-STRICT final holdings:")
        for t, w in sorted(p_ns.snapshots[-1].weights.items(), key=lambda x: -x[1]):
            print(f"  {t:8s} {w:.1f}%")
        print("STRICT final holdings:")
        for t, w in sorted(p_st.snapshots[-1].weights.items(), key=lambda x: -x[1]):
            print(f"  {t:8s} {w:.1f}%")

    print()
    ns_unique = sorted(set(r_ns.integrity_warnings))
    st_unique = sorted(set(r_st.integrity_warnings))
    print(f"NON-STRICT UNIQUE WARNINGS ({len(ns_unique)}):")
    for w in ns_unique:
        print(f"  {w}")
    print()
    print(f"STRICT UNIQUE WARNINGS ({len(st_unique)}):")
    for w in st_unique:
        print(f"  {w}")
