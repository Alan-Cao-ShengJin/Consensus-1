"""NVDA backfill: Tier 1 docs + 10% DefeatBeta news sample.

Fetches all Tier 1 sources (SEC, transcripts, FMP financials)
plus a 10% sample of DefeatBeta news, merges chronologically,
and runs conviction updates through the LLM.
"""
import logging
import os
import sys
import time
from datetime import date, datetime, timedelta

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger("nvda_backfill_news")

for name in ("httpx", "httpcore", "urllib3", "openai", "edgar"):
    logging.getLogger(name).setLevel(logging.WARNING)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

_BACKTEST_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backtests")
os.makedirs(_BACKTEST_DIR, exist_ok=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_BACKTEST_DIR, 'nvda_backtest.db')}"
os.environ.setdefault("SEC_USER_AGENT", "Consensus-1 Research admin@example.com")
os.environ["DISABLE_GRAPH_SYNC"] = "1"
os.environ["DISABLE_PROPAGATION"] = "1"

TICKER = "NVDA"
LOOKBACK_START = date(2024, 1, 1)

NEWS_PARQUET_URL = (
    "https://huggingface.co/datasets/defeatbeta/yahoo-finance-data"
    "/resolve/main/data/stock_news.parquet"
)


def fetch_news_sample(sample_pct=10):
    """Fetch 10% sample of DefeatBeta news for NVDA, spread evenly over time."""
    from connectors.base import DocumentPayload
    from models import SourceType, SourceTier

    try:
        import duckdb
    except ImportError:
        logger.warning("duckdb not installed")
        return []

    conn = duckdb.connect(config={"custom_user_agent": "ConsensusEngine/1.0"})
    conn.execute("INSTALL httpfs; LOAD httpfs;")

    rows = conn.execute(f"""
        SELECT title, publisher, report_date, type, news
        FROM (
            SELECT *, ROW_NUMBER() OVER (ORDER BY report_date) as rn
            FROM '{NEWS_PARQUET_URL}'
            WHERE related_symbols LIKE '%NVDA%'
              AND news IS NOT NULL
        )
        WHERE rn % {100 // sample_pct} = 0
        ORDER BY report_date
    """).fetchall()
    conn.close()

    payloads = []
    for title, publisher, report_date, news_type, news_content in rows:
        # Build text from paragraphs
        text_parts = []
        if title:
            text_parts.append(title)
            text_parts.append("")
        if isinstance(news_content, list):
            for item in news_content:
                if isinstance(item, dict):
                    highlight = item.get("highlight", "")
                    para = item.get("paragraph", "")
                    if highlight:
                        text_parts.append(f"[{highlight}]")
                    if para:
                        text_parts.append(para)
                        text_parts.append("")

        raw_text = "\n".join(text_parts)
        if len(raw_text) < 50:
            continue  # skip empty/tiny articles

        # Parse date
        if isinstance(report_date, str):
            pub_date = datetime.fromisoformat(report_date[:10])
        elif isinstance(report_date, date):
            pub_date = datetime(report_date.year, report_date.month, report_date.day)
        else:
            pub_date = datetime(2025, 1, 1)

        payloads.append(DocumentPayload(
            source_type=SourceType.NEWS,
            source_tier=SourceTier.TIER_2,
            ticker="NVDA",
            title=f"[{publisher}] {title}" if publisher else title,
            raw_text=raw_text,
            published_at=pub_date,
            source_key=f"defeatbeta_news_{hash(title) % 100000}",
        ))

    logger.info("DefeatBeta news sample: %d articles (from %d%% sample)", len(payloads), sample_pct)
    return payloads


def main():
    import argparse
    import pathlib
    from connectors.base import DocumentPayload

    parser = argparse.ArgumentParser()
    parser.add_argument("--fresh", action="store_true")
    parser.add_argument("--skip-finnhub", action="store_true", default=True)
    parser.add_argument("--news-pct", type=int, default=10, help="News sample percentage")
    args = parser.parse_args()

    db_path = pathlib.Path(_BACKTEST_DIR) / "nvda_backtest.db"
    if args.fresh and db_path.exists():
        db_path.unlink()
        logger.info("Deleted existing %s", db_path)

    from db import engine, SessionLocal
    from models import Base, Company, Thesis, ThesisState, Candidate
    from sqlalchemy import select

    Base.metadata.create_all(engine)
    session = SessionLocal()

    if not session.scalars(select(Company).where(Company.ticker == TICKER)).first():
        session.add(Company(ticker=TICKER, name="NVIDIA Corp", sector="Technology",
                            industry="Semiconductors"))
        session.add(Thesis(company_ticker=TICKER, title="NVDA thesis",
                           conviction_score=0.0, state=ThesisState.FORMING,
                           status_active=True))
        session.add(Candidate(ticker=TICKER, conviction_score=0.0))
        session.commit()
        logger.info("Seeded NVDA company + thesis (conv=0)")

    start = time.time()

    try:
        # Step 1: Prices + estimates
        from scripts.backfill_nvda import fetch_prices, fetch_estimates
        fetch_prices(session)
        fetch_estimates(session)

        # Step 2: Fetch Tier 1 documents (same as before)
        from scripts.backfill_nvda import fetch_all_documents
        tier1_docs = fetch_all_documents(skip_finnhub=True)
        logger.info("Tier 1 documents: %d", len(tier1_docs))

        # Step 3: Fetch news sample
        news_docs = fetch_news_sample(sample_pct=args.news_pct)
        logger.info("News documents: %d", len(news_docs))

        # Step 4: Merge, dedupe, and sort chronologically
        all_docs = tier1_docs + news_docs

        # Dedupe by title similarity (normalize and check)
        seen_titles = set()
        deduped = []
        for d in all_docs:
            # Normalize title for comparison
            norm_title = (d.title or "").lower().strip()
            # Remove common prefixes like "[Publisher] "
            if "] " in norm_title:
                norm_title = norm_title.split("] ", 1)[-1]
            # Take first 50 chars as key (catches rephrased duplicates)
            title_key = norm_title[:50]

            # Also dedupe by source_key if present
            source_key = getattr(d, 'source_key', None)

            if title_key and title_key in seen_titles:
                continue
            seen_titles.add(title_key)
            if source_key:
                if source_key in seen_titles:
                    continue
                seen_titles.add(source_key)
            deduped.append(d)

        logger.info("After dedup: %d docs (removed %d dupes)", len(deduped), len(all_docs) - len(deduped))
        all_docs = deduped
        all_docs.sort(key=lambda p: p.published_at or datetime.min)

        print(f"\n{'=' * 70}")
        print(f"DOCUMENTS TO PROCESS ({len(all_docs)} total: {len(tier1_docs)} Tier 1 + {len(news_docs)} news)")
        print(f"{'=' * 70}")
        for d in all_docs:
            tier = d.source_tier.value if hasattr(d.source_tier, 'value') else str(d.source_tier)
            dt = d.published_at.strftime("%Y-%m-%d") if d.published_at else "?"
            title = (d.title or "").encode("ascii", "replace").decode()[:60]
            chars = len(d.raw_text) if d.raw_text else 0
            print(f"  {dt} | {tier:6s} | {chars:6d}c | {title}")

        # Step 5: Run conviction updates
        print(f"\n{'=' * 70}")
        print("RUNNING CONVICTION UPDATES")
        print(f"{'=' * 70}")
        from scripts.backfill_nvda import run_conviction_updates, show_conviction_trajectory, show_summary
        results = run_conviction_updates(session, all_docs, use_llm=True)

        # Step 6: Show results
        show_conviction_trajectory(results)
        show_summary(session)

        elapsed = time.time() - start
        score_changes = len([r for r in results if r['score_change'] != 0])
        print(f"\nCompleted in {elapsed:.0f}s ({len(all_docs)} documents, "
              f"{score_changes} score changes)")

    finally:
        session.close()


if __name__ == "__main__":
    main()
