"""Backfill NVDA: pull all data, build conviction trajectory, backtest.

Simple loop: Information -> Conviction -> Investment.

1. Fetch all available documents (SEC filings, transcripts, FMP financials)
2. Fetch prices
3. Sort documents chronologically
4. Feed each document to thesis_updater (one LLM call each)
5. Result: auditable conviction timeline ready for backtesting
"""
import argparse
import logging
import os
import sys
import time
from datetime import date, datetime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger("nvda_backfill")

for name in ("httpx", "httpcore", "urllib3", "openai", "edgar"):
    logging.getLogger(name).setLevel(logging.WARNING)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Dedicated database for single-ticker exercise (separate from main DBs)
_BACKTEST_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backtests")
os.makedirs(_BACKTEST_DIR, exist_ok=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_BACKTEST_DIR, 'nvda_backtest.db')}"
os.environ.setdefault("SEC_USER_AGENT", "Consensus-1 Research admin@example.com")
os.environ["DISABLE_GRAPH_SYNC"] = "1"
os.environ["DISABLE_PROPAGATION"] = "1"

TICKER = "NVDA"
LOOKBACK_START = date(2024, 1, 1)


def fetch_all_documents(skip_finnhub=False):
    """Fetch all available documents from all sources. Returns list of DocumentPayload."""
    all_payloads = []
    days = (date.today() - LOOKBACK_START).days

    # 1. SEC filings (10-K, 10-Q, 8-K) — free, Tier 1
    try:
        from connectors.sec_edgar import SECEdgarConnector
        connector = SECEdgarConnector(filing_types=["10-K", "10-Q", "8-K"])
        payloads = connector.fetch(TICKER, days=days)
        logger.info("SEC EDGAR: %d documents", len(payloads))
        all_payloads.extend(payloads)
    except Exception as e:
        logger.warning("SEC EDGAR fetch failed: %s", e)

    # 2. Earnings call transcripts (DefeatBeta/HuggingFace) — free, Tier 1
    try:
        from connectors.defeatbeta_connector import DefeatBetaTranscriptConnector
        connector = DefeatBetaTranscriptConnector()
        if connector.available:
            payloads = connector.fetch(TICKER, days=days)
            logger.info("DefeatBeta transcripts: %d documents", len(payloads))
            all_payloads.extend(payloads)
    except Exception as e:
        logger.warning("DefeatBeta fetch failed: %s", e)

    # 3. FMP quarterly financials — API key, Tier 1
    try:
        from connectors.fmp_connector import FMPFinancialsConnector
        connector = FMPFinancialsConnector()
        if connector.available:
            payloads = connector.fetch(TICKER, days=days)
            logger.info("FMP financials: %d documents", len(payloads))
            all_payloads.extend(payloads)
    except Exception as e:
        logger.warning("FMP financials fetch failed: %s", e)

    # 4. Finnhub news — API key, Tier 2 (skippable)
    if not skip_finnhub:
        try:
            from connectors.finnhub_connector import FinnhubNewsConnector
            connector = FinnhubNewsConnector()
            if connector.available:
                chunk_start = LOOKBACK_START
                today = date.today()
                from datetime import timedelta
                finnhub_count = 0
                while chunk_start < today:
                    chunk_end = min(chunk_start + timedelta(days=90), today)
                    try:
                        payloads = connector.fetch(
                            TICKER,
                            start_date=chunk_start.isoformat(),
                            end_date=chunk_end.isoformat(),
                        )
                        all_payloads.extend(payloads)
                        finnhub_count += len(payloads)
                    except Exception:
                        pass
                    chunk_start = chunk_end + timedelta(days=1)
                    time.sleep(1)
                logger.info("Finnhub news: %d articles", finnhub_count)
        except Exception as e:
            logger.warning("Finnhub fetch failed: %s", e)

    # Sort everything by published_at
    all_payloads.sort(key=lambda p: p.published_at or datetime.min)

    logger.info("Total: %d documents fetched, sorted chronologically", len(all_payloads))
    return all_payloads


def fetch_prices(session):
    """Pull NVDA + VIX prices."""
    from connectors.yfinance_prices import YFinancePriceUpdater
    updater = YFinancePriceUpdater()
    days = (date.today() - LOOKBACK_START).days
    count = 0
    for t in [TICKER, "^VIX"]:
        result = updater.update(session, t, days=days)
        count += getattr(result, 'rows_upserted', 0) or 0
    session.commit()
    logger.info("Prices: %d rows", count)
    return count


def fetch_estimates(session):
    """Pull FMP analyst estimates."""
    try:
        from connectors.fmp_connector import FMPEstimatesConnector
        connector = FMPEstimatesConnector()
        if connector.available:
            days = (date.today() - LOOKBACK_START).days
            count = connector.persist_estimates(session, TICKER, days=days)
            session.commit()
            logger.info("Estimates: %d rows", count)
            return count
    except Exception as e:
        logger.warning("FMP estimates failed: %s", e)
    return 0


def run_conviction_updates(session, documents, use_llm=True):
    """Feed each document to thesis_updater in chronological order."""
    from thesis_updater import update_thesis_with_document
    from sqlalchemy import select
    from models import Thesis

    thesis = session.scalars(
        select(Thesis).where(
            Thesis.company_ticker == TICKER,
            Thesis.status_active == True,
        )
    ).first()

    if not thesis:
        logger.error("No thesis found for %s", TICKER)
        return []

    results = []
    for i, doc in enumerate(documents, 1):
        source_type = doc.source_type.value if hasattr(doc.source_type, 'value') else str(doc.source_type)
        source_tier = doc.source_tier.value if hasattr(doc.source_tier, 'value') else str(doc.source_tier)
        published_at = doc.published_at or datetime(2024, 1, 1)

        result = update_thesis_with_document(
            session=session,
            thesis_id=thesis.id,
            document_text=doc.raw_text,
            source_type=source_type,
            source_tier=source_tier,
            published_at=published_at,
            document_title=doc.title,
            use_llm=use_llm,
        )
        session.commit()
        results.append({
            "date": published_at.strftime("%Y-%m-%d"),
            "title": doc.title,
            "source_type": source_type,
            "source_tier": source_tier,
            **result,
        })

        # Progress
        if i % 10 == 0:
            logger.info("Progress: %d/%d documents processed", i, len(documents))

    return results


def show_conviction_trajectory(results):
    """Print the conviction trajectory."""
    print("\n" + "=" * 80)
    print("CONVICTION TRAJECTORY")
    print("=" * 80)
    print(f"{'Date':<12} {'Score':>5} {'Chg':>5} {'Source':<25} {'Title':<40}")
    print("-" * 80)
    for r in results:
        title = (r['title'] or '')[:38]
        print(f"{r['date']:<12} {r['score_after']:5.0f} {r['score_change']:+5.0f} "
              f"{r['source_type']:<25} {title}")

    print("\n" + "=" * 80)
    print("AUDIT TRAIL")
    print("=" * 80)
    for r in results:
        if r['score_change'] != 0:
            print(f"\n{r['date']} | {r['source_type']} | {r['score_before']:.0f}->{r['score_after']:.0f}")
            print(f"  Reasoning: {r['reasoning']}")
            if r.get('is_new_information') is False:
                print(f"  (Not new information)")


def show_summary(session):
    """Show data summary."""
    from sqlalchemy import text

    print("\n" + "=" * 60)
    print("NVDA DATABASE SUMMARY")
    print("=" * 60)

    r = session.execute(text(
        "SELECT MIN(date), MAX(date), COUNT(*) FROM prices WHERE ticker = :t"
    ), {"t": TICKER}).fetchone()
    print(f"Prices: {r[0]} to {r[1]} ({r[2]} days)")

    r = session.execute(text(
        "SELECT conviction_score, state, summary FROM theses "
        "WHERE company_ticker = :t AND status_active = 1"
    ), {"t": TICKER}).fetchone()
    if r:
        print(f"Thesis: score={r[0]:.0f}, state={r[1]}")
        print(f"Summary: {r[2]}")

    rows = session.execute(text("""
        SELECT state, conviction_score, note, created_at
        FROM thesis_state_history
        WHERE thesis_id = (SELECT id FROM theses WHERE company_ticker = :t AND status_active = 1)
        ORDER BY created_at
    """), {"t": TICKER}).fetchall()
    if rows:
        print(f"\nHistory ({len(rows)} entries):")
        for r in rows:
            note = (r[2] or '')[:70]
            print(f"  {r[3]} | score={r[1]:5.1f} | {note}")


def main():
    parser = argparse.ArgumentParser(description="NVDA backfill + conviction trajectory")
    parser.add_argument("--no-llm", action="store_true", help="Skip LLM calls")
    parser.add_argument("--skip-fetch", action="store_true", help="Skip document fetching, use cached")
    parser.add_argument("--skip-finnhub", action="store_true", help="Skip Finnhub news")
    parser.add_argument("--summary-only", action="store_true")
    parser.add_argument("--fresh", action="store_true", help="Delete and recreate database")
    args = parser.parse_args()

    # Fresh DB setup
    import pathlib
    db_path = pathlib.Path(_BACKTEST_DIR) / "nvda_backtest.db"
    if args.fresh and db_path.exists():
        db_path.unlink()
        logger.info("Deleted existing %s", db_path)

    from db import engine, SessionLocal
    from models import Base, Company, Thesis, ThesisState, Candidate
    from sqlalchemy import select

    Base.metadata.create_all(engine)
    session = SessionLocal()

    # Seed if needed
    if not session.scalars(select(Company).where(Company.ticker == TICKER)).first():
        session.add(Company(ticker=TICKER, name="NVIDIA Corp", sector="Technology",
                            industry="Semiconductors"))
        session.add(Thesis(company_ticker=TICKER, title="NVDA thesis",
                           conviction_score=0.0, state=ThesisState.FORMING,
                           status_active=True))
        session.add(Candidate(ticker=TICKER, conviction_score=0.0))
        session.commit()
        logger.info("Seeded NVDA company + thesis (conv=0)")

    if args.summary_only:
        show_summary(session)
        session.close()
        return

    start = time.time()

    try:
        # Step 1: Prices + estimates (free, fast)
        fetch_prices(session)
        fetch_estimates(session)

        # Step 2: Fetch all documents
        documents = fetch_all_documents(skip_finnhub=args.skip_finnhub)

        # Preview what we have
        print(f"\n{'=' * 60}")
        print(f"DOCUMENTS TO PROCESS ({len(documents)} total)")
        print(f"{'=' * 60}")
        for d in documents:
            tier = d.source_tier.value if hasattr(d.source_tier, 'value') else str(d.source_tier)
            dt = d.published_at.strftime("%Y-%m-%d") if d.published_at else "?"
            title = (d.title or "").encode("ascii", "replace").decode()
            print(f"  {dt} | {tier:6s} | {title}")

        # Step 3: Run conviction updates
        print(f"\n{'=' * 60}")
        print("RUNNING CONVICTION UPDATES")
        print(f"{'=' * 60}")
        results = run_conviction_updates(session, documents, use_llm=not args.no_llm)

        # Step 4: Show results
        show_conviction_trajectory(results)
        show_summary(session)

        elapsed = time.time() - start
        print(f"\nCompleted in {elapsed:.0f}s ({len(documents)} documents, "
              f"{len([r for r in results if r['score_change'] != 0])} score changes)")

    finally:
        session.close()


if __name__ == "__main__":
    main()
