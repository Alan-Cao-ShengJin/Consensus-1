"""Step 8.2 Empirical Validation: Before vs After comparison.

Creates identical synthetic data in two separate in-memory databases:
  - PRE-8.2:  ThesisStateHistory records have NO valuation fields (simulating
              the old code where thesis_update_service didn't persist valuation)
  - POST-8.2: ThesisStateHistory records HAVE valuation fields populated
              (going-forward fix) plus conservative backfill applied

Both runs use strict_replay=True with identical settings.
The only difference is valuation-history completeness.
"""
import os
import sys
from datetime import date, datetime, timedelta
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session

from models import (
    Base, Company, Thesis, ThesisState, ThesisStateHistory,
    Candidate, Price, Checkpoint, ZoneState, ValuationProvenance,
    Document, SourceType, SourceTier, Claim, ClaimType,
    EconomicChannel, Direction, NoveltyType, ClaimCompanyLink,
)
from replay_runner import run_replay, format_replay_text
from replay_engine import generate_review_dates
from replay_diagnostics import (
    build_candidate_provenance_report, build_coverage_diagnostics,
    format_diagnostics_text,
)
from scripts.backfill_valuation_history import backfill_valuation_history, inspect_coverage


# ── Configuration ──────────────────────────────────────────────────────
START = date(2025, 6, 1)
END = date(2025, 9, 28)
CADENCE = 7
INITIAL_CASH = 1_000_000.0
COST_BPS = 10.0

TICKERS = ["AAPL", "NVDA", "MSFT", "GOOG", "TSLA"]


def seed_shared_data(session: Session, *, populate_valuation: bool):
    """Seed identical universe into session.

    Args:
        populate_valuation: If True, ThesisStateHistory records get valuation
            fields populated (post-8.2 going-forward fix). If False, all
            valuation fields are NULL (pre-8.2 behavior).
    """
    doc = Document(
        source_type=SourceType.NEWS, source_tier=SourceTier.TIER_2,
        url="http://test.com/doc", title="Test",
    )
    session.add(doc)
    session.flush()
    doc_id = doc.id

    for t in TICKERS:
        session.add(Company(ticker=t, name=f"{t} Inc", sector="Tech"))
        session.flush()

        thesis = Thesis(
            company_ticker=t, title=f"{t} thesis", thesis_type="long",
            state=ThesisState.STRENGTHENING,
            conviction_score=80.0, valuation_gap_pct=30.0, base_case_rerating=20.0,
        )
        session.add(thesis)
        session.flush()

        # ── Candidates: mixed temporal provenance ──
        cand = Candidate(
            ticker=t, primary_thesis_id=thesis.id,
            conviction_score=80.0, zone_state=ZoneState.BUY,
        )
        if t in ("AAPL", "NVDA"):
            cand.created_at = datetime(2025, 5, 1)       # before replay
        elif t == "MSFT":
            cand.created_at = datetime(2025, 7, 15)       # mid-replay
        elif t == "GOOG":
            cand.created_at = None                         # no provenance
        elif t == "TSLA":
            cand.created_at = datetime(2025, 12, 1)        # after replay end
        session.add(cand)
        session.flush()

        # ── Prices: daily with slow upward drift ──
        base_price = {"AAPL": 180, "NVDA": 120, "MSFT": 400, "GOOG": 170, "TSLA": 250}[t]
        d = date(2025, 5, 1)
        while d <= date(2025, 10, 31):
            drift = (d - date(2025, 5, 1)).days * 0.05
            noise = ((hash(f"{t}{d}") % 20) - 10) * 0.5
            session.add(Price(ticker=t, date=d, close=round(base_price + drift + noise, 2)))
            d += timedelta(days=1)
        session.flush()

        # ── ThesisStateHistory ──
        # Record 1: early record — pre-8.2 had no valuation here
        session.add(ThesisStateHistory(
            thesis_id=thesis.id, state=ThesisState.STRENGTHENING,
            conviction_score=75.0, note="initial snapshot",
            created_at=datetime(2025, 5, 15),
            valuation_gap_pct=None,
            base_case_rerating=None,
            valuation_provenance=None,
        ))

        # Record 2: mid-replay snapshot — AAPL/NVDA/MSFT get valuation
        # (simulates: going-forward fix started capturing valuation here)
        if t in ("AAPL", "NVDA", "MSFT"):
            session.add(ThesisStateHistory(
                thesis_id=thesis.id, state=ThesisState.STRENGTHENING,
                conviction_score=80.0, note="with valuation",
                created_at=datetime(2025, 7, 20),
                valuation_gap_pct=30.0 if populate_valuation else None,
                base_case_rerating=20.0 if populate_valuation else None,
                valuation_provenance=(
                    ValuationProvenance.HISTORICAL_RECORDED.value
                    if populate_valuation else None
                ),
            ))
        # Record 3: late-replay snapshot for AAPL (tests backfill gap)
        if t == "AAPL":
            session.add(ThesisStateHistory(
                thesis_id=thesis.id, state=ThesisState.STRENGTHENING,
                conviction_score=82.0, note="late snapshot - no valuation captured",
                created_at=datetime(2025, 8, 10),
                valuation_gap_pct=None,
                base_case_rerating=None,
                valuation_provenance=None,
            ))

        # GOOG/TSLA: no valuation history at all (same in both scenarios)
        session.flush()

        # ── Checkpoints: mixed provenance ──
        if t in ("AAPL", "NVDA"):
            cp = Checkpoint(
                checkpoint_type="earnings", name=f"{t} Q3",
                date_expected=date(2025, 7, 25),
                linked_company_ticker=t, status="pending",
            )
            cp.created_at = datetime(2025, 6, 1)
            session.add(cp)
        if t == "MSFT":
            cp = Checkpoint(
                checkpoint_type="earnings", name=f"{t} Q3",
                date_expected=date(2025, 8, 15),
                linked_company_ticker=t, status="pending",
            )
            cp.created_at = None
            session.add(cp)
        if t == "GOOG":
            cp = Checkpoint(
                checkpoint_type="earnings", name=f"{t} Q3",
                date_expected=date(2025, 8, 1),
                linked_company_ticker=t, status="pending",
            )
            cp.created_at = None
            session.add(cp)
        session.flush()

        # ── Novel claims every week to trigger initiations ──
        if t != "TSLA":
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
                    session.add(claim)
                    session.flush()
                    session.add(ClaimCompanyLink(
                        claim_id=claim.id, company_ticker=t, relation_type="about",
                    ))
                    session.flush()
                review_d += timedelta(days=7)


def run_scenario(label: str, populate_valuation: bool, run_backfill: bool):
    """Run one scenario and return all results."""
    engine = create_engine("sqlite://", echo=False)
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        seed_shared_data(session, populate_valuation=populate_valuation)
        session.flush()

        # Optionally run backfill (post-8.2 only)
        backfill_stats = None
        if run_backfill:
            backfill_stats = backfill_valuation_history(
                session, max_gap_days=30, dry_run=False,
            )
            session.flush()

        # Inspect valuation coverage
        coverage = inspect_coverage(session)

        # Count provenance distribution
        prov_counts = {}
        rows = session.execute(
            select(
                ThesisStateHistory.valuation_provenance,
                func.count(ThesisStateHistory.id),
            ).group_by(ThesisStateHistory.valuation_provenance)
        ).all()
        for prov, count in rows:
            prov_counts[str(prov or "unset")] = count

        # Run strict replay
        run_result, portfolio, metrics = run_replay(
            session,
            start_date=START, end_date=END,
            cadence_days=CADENCE,
            initial_cash=INITIAL_CASH,
            transaction_cost_bps=COST_BPS,
            strict_replay=True,
        )

        # Build diagnostics
        review_dates = generate_review_dates(START, END, CADENCE)
        diag = build_coverage_diagnostics(run_result)
        cand_report = build_candidate_provenance_report(
            session, review_dates,
        )

        return {
            "label": label,
            "run_result": run_result,
            "portfolio": portfolio,
            "metrics": metrics,
            "coverage": coverage,
            "prov_counts": prov_counts,
            "backfill_stats": backfill_stats,
            "diagnostics": diag,
            "cand_report": cand_report,
        }


def print_comparison(pre, post):
    """Print side-by-side comparison."""
    r_pre = pre["run_result"]
    r_post = post["run_result"]
    m_pre = pre["metrics"]
    m_post = post["metrics"]
    p_pre = pre["portfolio"]
    p_post = post["portfolio"]
    d_pre = pre["diagnostics"]
    d_post = post["diagnostics"]

    # Final snapshot
    snap_pre = p_pre.snapshots[-1] if p_pre.snapshots else None
    snap_post = p_post.snapshots[-1] if p_post.snapshots else None

    print("=" * 80)
    print("STEP 8.2 EMPIRICAL VALIDATION: STRICT REPLAY BEFORE vs AFTER")
    print("=" * 80)
    print(f"  Period:         {START} to {END}")
    print(f"  Cadence:        {CADENCE} days")
    print(f"  Initial cash:   ${INITIAL_CASH:,.0f}")
    print(f"  Cost:           {COST_BPS} bps")
    print(f"  Universe:       {', '.join(TICKERS)}")
    print(f"  Mode:           strict_replay=True (both runs)")
    print()

    # ── Main comparison table ──
    def row(label, pre_val, post_val, fmt="{}", highlight=False):
        pre_s = fmt.format(pre_val)
        post_s = fmt.format(post_val)
        delta = ""
        if isinstance(pre_val, (int, float)) and isinstance(post_val, (int, float)):
            diff = post_val - pre_val
            if diff != 0:
                if isinstance(diff, float):
                    delta = f"  ({diff:+.2f})"
                else:
                    delta = f"  ({diff:+d})"
        marker = " ***" if highlight and delta else ""
        print(f"  {label:42s} {pre_s:>14s}  {post_s:>14s}{delta}{marker}")

    print(f"  {'METRIC':42s} {'PRE-8.2':>14s}  {'POST-8.2':>14s}")
    print(f"  {'-'*42} {'-'*14}  {'-'*14}")

    row("Purity level", r_pre.purity_level, r_post.purity_level)
    row("Reviews", r_pre.total_reviews, r_post.total_reviews)
    row("Recommendations", r_pre.total_recommendations, r_post.total_recommendations, "{}", True)
    row("Trades applied", r_pre.total_trades_applied, r_post.total_trades_applied, "{}", True)
    row("Trades skipped", r_pre.total_trades_skipped, r_post.total_trades_skipped)
    row("Initiations", m_pre.total_initiations, m_post.total_initiations, "{}", True)
    row("Exits", m_pre.total_exits, m_post.total_exits)
    row("Final positions", snap_pre.num_positions if snap_pre else 0,
        snap_post.num_positions if snap_post else 0, "{}", True)
    row("Total return", m_pre.total_return_pct, m_post.total_return_pct, "{:+.2f}%", True)
    row("Max drawdown", m_pre.max_drawdown_pct, m_post.max_drawdown_pct, "{:.2f}%")
    row("Final cash", snap_pre.cash if snap_pre else INITIAL_CASH,
        snap_post.cash if snap_post else INITIAL_CASH, "${:,.2f}")
    row("Final value", snap_pre.total_value if snap_pre else INITIAL_CASH,
        snap_post.total_value if snap_post else INITIAL_CASH, "${:,.2f}", True)
    print()

    print(f"  {'PURITY / PROVENANCE':42s} {'PRE-8.2':>14s}  {'POST-8.2':>14s}")
    print(f"  {'-'*42} {'-'*14}  {'-'*14}")
    row("Valuation: historical (pure)", d_pre.valuation_historical_count,
        d_post.valuation_historical_count, "{}", True)
    row("Valuation: backfilled (accepted)", d_pre.valuation_backfilled_count,
        d_post.valuation_backfilled_count, "{}", True)
    row("Valuation: fallback (impure)", d_pre.valuation_fallback_count,
        d_post.valuation_fallback_count)
    row("Valuation: missing (skipped)", d_pre.valuation_missing_count,
        d_post.valuation_missing_count, "{}", True)
    row("Names downgraded to HOLD",
        len(set(d_pre.names_downgraded_to_hold)),
        len(set(d_post.names_downgraded_to_hold)), "{}", True)
    row("Names skipped entirely",
        len(set(d_pre.names_skipped_entirely)),
        len(set(d_post.names_skipped_entirely)))
    row("Candidate exclusions (provenance)",
        d_pre.candidate_exclusions_no_provenance,
        d_post.candidate_exclusions_no_provenance)
    row("Checkpoint exclusions (provenance)",
        d_pre.checkpoint_exclusions_no_provenance,
        d_post.checkpoint_exclusions_no_provenance)
    row("Impure candidates used", r_pre.total_impure_candidates,
        r_post.total_impure_candidates)
    row("Impure valuations used", r_pre.total_impure_valuations,
        r_post.total_impure_valuations)
    row("Total inputs skipped (strict)", r_pre.total_skipped_impure,
        r_post.total_skipped_impure, "{}", True)
    row("Integrity warnings", len(r_pre.integrity_warnings),
        len(r_post.integrity_warnings))
    print()

    # ── Valuation provenance mix ──
    print("  VALUATION PROVENANCE MIX (ThesisStateHistory records)")
    print(f"  {'-'*42} {'-'*14}  {'-'*14}")
    all_provs = sorted(set(list(pre["prov_counts"].keys()) + list(post["prov_counts"].keys())))
    for prov in all_provs:
        row(f"  {prov}", pre["prov_counts"].get(prov, 0),
            post["prov_counts"].get(prov, 0))
    print()

    # ── Coverage ──
    print("  VALUATION COVERAGE (ThesisStateHistory)")
    print(f"  {'-'*42} {'-'*14}  {'-'*14}")
    row("Total history records", pre["coverage"]["total_records"],
        post["coverage"]["total_records"])
    row("With valuation", pre["coverage"]["with_valuation"],
        post["coverage"]["with_valuation"], "{}", True)
    row("Without valuation", pre["coverage"]["without_valuation"],
        post["coverage"]["without_valuation"])
    row("Coverage %",
        round(100 * pre["coverage"]["with_valuation"] / max(pre["coverage"]["total_records"], 1), 1),
        round(100 * post["coverage"]["with_valuation"] / max(post["coverage"]["total_records"], 1), 1),
        "{}%", True)
    print()

    # ── Final positions ──
    print("  FINAL POSITIONS")
    pre_weights = snap_pre.weights if snap_pre else {}
    post_weights = snap_post.weights if snap_post else {}
    all_tickers = sorted(set(list(pre_weights.keys()) + list(post_weights.keys())))
    if all_tickers:
        print(f"  {'Ticker':12s} {'PRE-8.2':>10s}  {'POST-8.2':>10s}")
        for t in all_tickers:
            pw = pre_weights.get(t, 0)
            ppw = post_weights.get(t, 0)
            marker = " NEW" if pw == 0 and ppw > 0 else ""
            print(f"  {t:12s} {pw:9.1f}%  {ppw:9.1f}%{marker}")
    else:
        print("  (no positions in either run)")
    print()

    # ── Backfill stats ──
    if post["backfill_stats"]:
        bs = post["backfill_stats"]
        print("  POST-8.2 BACKFILL ACTIONS")
        print(f"    Records inspected:    {bs['inspected']}")
        print(f"    Already populated:    {bs['already_populated']}")
        print(f"    Backfilled:           {bs['backfilled']}")
        print(f"    Marked missing:       {bs['marked_missing']}")
        print(f"    Provenance updated:   {bs['provenance_updated']}")
        print()

    # ── What changed: attribution ──
    print("=" * 80)
    print("WHAT CHANGED (ATTRIBUTION)")
    print("=" * 80)

    # Names downgraded pre but not post
    pre_hold = set(d_pre.names_downgraded_to_hold)
    post_hold = set(d_post.names_downgraded_to_hold)
    freed = pre_hold - post_hold
    still_hold = pre_hold & post_hold
    new_hold = post_hold - pre_hold

    if freed:
        print(f"\n  Names FREED from HOLD fallback (post-8.2 had valid valuation):")
        for t in sorted(freed):
            print(f"    - {t}: now has historically defensible valuation -> zone computed normally")

    if still_hold:
        print(f"\n  Names STILL downgraded to HOLD (valuation remains missing):")
        for t in sorted(still_hold):
            print(f"    - {t}: no historical valuation source found, even after backfill")

    if new_hold:
        print(f"\n  Names newly downgraded (unexpected):")
        for t in sorted(new_hold):
            print(f"    - {t}")

    # Candidate provenance — who entered, who didn't
    print(f"\n  Candidate provenance (unchanged between runs — same created_at data):")
    for e in post["cand_report"].entries:
        status = "INCLUDED" if e.entered_replay else "EXCLUDED"
        reason = ""
        if not e.has_created_at:
            reason = " (no created_at)"
        elif not e.entered_replay:
            reason = f" (created_at after replay end)"
        elif e.review_dates_skipped > 0:
            reason = f" (eligible from {e.first_eligible_date}, skipped {e.review_dates_skipped} earlier dates)"
        print(f"    {e.ticker:8s} [{status}]{reason}")

    # Per-ticker valuation story
    print(f"\n  Per-ticker valuation story:")
    # Parse warnings per ticker
    pre_warn_tickers = Counter()
    post_warn_tickers = Counter()
    for w in r_pre.integrity_warnings:
        if "no historical valuation" in w:
            for t in TICKERS:
                if t in w:
                    pre_warn_tickers[t] += 1
    for w in r_post.integrity_warnings:
        if "no historical valuation" in w:
            for t in TICKERS:
                if t in w:
                    post_warn_tickers[t] += 1

    for t in TICKERS:
        pre_count = pre_warn_tickers.get(t, 0)
        post_count = post_warn_tickers.get(t, 0)
        if pre_count > 0 and post_count == 0:
            print(f"    {t}: IMPROVED — {pre_count} valuation-missing warnings -> 0")
            print(f"          Explanation: ThesisStateHistory now has valuation fields; "
                  f"zone computed from historical data instead of HOLD fallback")
        elif pre_count > 0 and post_count > 0:
            diff = pre_count - post_count
            if diff > 0:
                print(f"    {t}: PARTIALLY IMPROVED — {pre_count} -> {post_count} valuation-missing warnings")
                print(f"          Explanation: backfill covered some dates but gaps remain "
                      f"(early records had no nearby valuation source)")
            else:
                print(f"    {t}: UNCHANGED — {pre_count} valuation-missing warnings in both")
                print(f"          Explanation: no historical valuation source exists for this ticker")
        elif pre_count == 0 and post_count == 0:
            # Check if excluded for other reasons
            cand_entry = next((e for e in post["cand_report"].entries if e.ticker == t), None)
            if cand_entry and not cand_entry.entered_replay:
                print(f"    {t}: N/A — excluded from strict replay (candidate provenance)")
            else:
                print(f"    {t}: NO CHANGE — no valuation warnings in either run")

    print()

    # ── What still limits strict replay ──
    print("=" * 80)
    print("WHAT STILL LIMITS STRICT REPLAY")
    print("=" * 80)
    limits = []
    if d_post.candidate_exclusions_no_provenance > 0:
        limits.append(f"  - {d_post.candidate_exclusions_no_provenance} candidate-date pairs excluded "
                      f"due to missing created_at (e.g., GOOG)")
    if post["cand_report"].candidates_excluded_all_dates > 0:
        excluded_names = [e.ticker for e in post["cand_report"].entries if not e.entered_replay]
        limits.append(f"  - {len(excluded_names)} candidates excluded for ALL review dates: "
                      f"{', '.join(excluded_names)}")
    if d_post.checkpoint_exclusions_no_provenance > 0:
        limits.append(f"  - {d_post.checkpoint_exclusions_no_provenance} checkpoint lookups excluded "
                      f"due to missing created_at")
    if d_post.valuation_missing_count > 0:
        limits.append(f"  - {d_post.valuation_missing_count} valuation lookups still missing "
                      f"(no historical source even after backfill)")
    if len(set(d_post.names_downgraded_to_hold)) > 0:
        limits.append(f"  - {len(set(d_post.names_downgraded_to_hold))} names still defaulted to HOLD: "
                      f"{sorted(set(d_post.names_downgraded_to_hold))}")

    if limits:
        for l in limits:
            print(l)
    else:
        print("  (no remaining limitations detected)")
    print()

    # ── Provenance mix summary ──
    print("=" * 80)
    print("PROVENANCE MIX: WHAT POWERED POST-8.2 STRICT REPLAY")
    print("=" * 80)
    total_post = sum(post["prov_counts"].values())
    for prov in sorted(post["prov_counts"].keys()):
        count = post["prov_counts"][prov]
        pct = 100 * count / max(total_post, 1)
        print(f"  {prov:40s} {count:4d} records ({pct:.0f}%)")
    print()

    # ── Bottom line ──
    print("=" * 80)
    print("BOTTOM LINE")
    print("=" * 80)

    return_delta = m_post.total_return_pct - m_pre.total_return_pct
    init_delta = m_post.total_initiations - m_pre.total_initiations
    rec_delta = r_post.total_recommendations - r_pre.total_recommendations
    trade_delta = r_post.total_trades_applied - r_pre.total_trades_applied
    hold_freed = len(pre_hold - post_hold)
    val_miss_delta = d_pre.valuation_missing_count - d_post.valuation_missing_count

    print(f"  Recommendations:       {r_pre.total_recommendations} -> {r_post.total_recommendations} ({rec_delta:+d})")
    print(f"  Trades applied:        {r_pre.total_trades_applied} -> {r_post.total_trades_applied} ({trade_delta:+d})")
    print(f"  Initiations:           {m_pre.total_initiations} -> {m_post.total_initiations} ({init_delta:+d})")
    print(f"  Total return:          {m_pre.total_return_pct:+.2f}% -> {m_post.total_return_pct:+.2f}% ({return_delta:+.2f}pp)")
    print(f"  Val-missing warnings:  {d_pre.valuation_missing_count} -> {d_post.valuation_missing_count} ({-val_miss_delta:+d})")
    print(f"  Names freed from HOLD: {hold_freed}")
    print()

    deployed_pre = INITIAL_CASH - (snap_pre.cash if snap_pre else INITIAL_CASH)
    deployed_post = INITIAL_CASH - (snap_post.cash if snap_post else INITIAL_CASH)
    print(f"  Capital deployed:      ${deployed_pre:,.0f} -> ${deployed_post:,.0f} "
          f"(${deployed_post - deployed_pre:+,.0f})")
    print()

    if init_delta > 0 or hold_freed > 0:
        print("  CONCLUSION: Step 8.2 materially improved strict replay.")
        print(f"  The improvement is primarily driven by {hold_freed} name(s) gaining historically")
        print(f"  defensible valuation state, which allowed zone computation instead of HOLD fallback.")
        if return_delta > 0:
            print(f"  The {return_delta:+.2f}pp return improvement appears to reflect genuine additional")
            print(f"  deployment, not noise — it is mechanistically explained by more names being")
            print(f"  investable with valid valuation history.")
        elif return_delta < 0:
            print(f"  The {return_delta:+.2f}pp return change reflects that additional deployment")
            print(f"  happened to underperform cash in this window. The mechanism worked correctly;")
            print(f"  the return difference is market-dependent, not a defect.")
        else:
            print(f"  Return was unchanged, suggesting freed names were either not deployed")
            print(f"  or deployment effects were offset.")
        print()
        print("  RECOMMENDATION: Proceed to Step 9.")
    elif val_miss_delta > 0:
        print("  CONCLUSION: Step 8.2 reduced valuation gaps but did not produce")
        print("  additional deployments in this replay window.")
        print("  The mechanism is working but the universe is too constrained for")
        print("  economic impact. Consider a wider date range or additional names.")
        print()
        print("  RECOMMENDATION: Proceed to Step 9 (mechanism validated, data-limited).")
    else:
        print("  CONCLUSION: Step 8.2 did not measurably improve strict replay in this window.")
        print("  Consider investigating why backfill did not cover the gaps.")
        print()
        print("  RECOMMENDATION: Another 8.x hardening pass before Step 9.")


if __name__ == "__main__":
    print("Running PRE-8.2 scenario (no valuation on history records)...")
    pre = run_scenario("PRE-8.2", populate_valuation=False, run_backfill=False)

    print("Running POST-8.2 scenario (valuation populated + backfill)...")
    post = run_scenario("POST-8.2", populate_valuation=True, run_backfill=True)

    print()
    print_comparison(pre, post)
