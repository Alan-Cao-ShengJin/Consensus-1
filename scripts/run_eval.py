#!/usr/bin/env python
"""
Pipeline evaluation: run 15+ real documents through ingestion + thesis update,
save structured outputs for manual quality inspection.

Usage:
    python scripts/run_eval.py
    python scripts/run_eval.py --extractor stub   # skip LLM, use stub extractor
    python scripts/run_eval.py --output eval_output.json
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv

load_dotenv()

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from models import (
    Base, Company, Thesis, Claim, Document, ThesisClaimLink,
    ThesisStateHistory, SourceType, ThesisState,
)
from ingest_runner import run_ingestion
from thesis_update_service import update_thesis_from_claims

# ---------------------------------------------------------------------------
# Document definitions: (file, source_type, ticker, description)
# ---------------------------------------------------------------------------

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "..", "tests", "fixtures")

DOCUMENTS = [
    # --- NVDA: 4 docs, including a repetitive one and a negative one ---
    {
        "file": "nvda_earnings.txt",
        "source_type": "earnings_transcript",
        "ticker": "NVDA",
        "desc": "NVDA Q4 earnings transcript -- strong bullish (93% DC rev growth)",
    },
    {
        "file": "nvda_news.html",
        "source_type": "news",
        "ticker": "NVDA",
        "desc": "NVDA news article -- bullish (beat estimates, raised guidance)",
    },
    {
        "file": "nvda_earnings_repeat.txt",
        "source_type": "news",
        "ticker": "NVDA",
        "desc": "NVDA repeat news -- same Q4 data rehashed (test repetitive dampening)",
    },
    {
        "file": "nvda_competition_news.txt",
        "source_type": "news",
        "ticker": "NVDA",
        "desc": "AMD MI350 benchmarks challenge NVDA -- bearish competitive signal",
    },
    {
        "file": "nvda_supply_constraint.txt",
        "source_type": "news",
        "ticker": "NVDA",
        "desc": "Blackwell supply delays -- mixed (constrains near-term, extends backlog)",
    },
    # --- AAPL: 2 docs, one mixed one bearish ---
    {
        "file": "aapl_earnings_q1_2025.txt",
        "source_type": "earnings_transcript",
        "ticker": "AAPL",
        "desc": "AAPL Q1 earnings -- mixed (record rev but China -11%)",
    },
    {
        "file": "aapl_china_warning.txt",
        "source_type": "news",
        "ticker": "AAPL",
        "desc": "AAPL revenue warning -- strongly bearish (China collapse)",
    },
    # --- TSLA: 3 docs, bearish auto + mixed signals + robotaxi wildcard ---
    {
        "file": "tsla_10q_excerpt.txt",
        "source_type": "10Q",
        "ticker": "TSLA",
        "desc": "TSLA 10-Q -- bearish auto (deliveries -13%, margins compressed)",
    },
    {
        "file": "tsla_8k_robotaxi.txt",
        "source_type": "8K",
        "ticker": "TSLA",
        "desc": "TSLA 8-K robotaxi approval -- mixed (limited, needs safety driver)",
    },
    {
        "file": "tsla_mixed_signals.txt",
        "source_type": "news",
        "ticker": "TSLA",
        "desc": "TSLA mixed analysis -- energy boom vs auto margin compression",
    },
    # --- AMZN: 2 docs, AWS bullish + retail competition bearish ---
    {
        "file": "amzn_news_aws.txt",
        "source_type": "news",
        "ticker": "AMZN",
        "desc": "AWS revenue surge -- bullish (19% growth, record margins)",
    },
    {
        "file": "amzn_retail_competition.txt",
        "source_type": "news",
        "ticker": "AMZN",
        "desc": "Temu/Shein taking share -- bearish retail competitive pressure",
    },
    # --- META: 2 docs, bullish broker report + bearish regulatory ---
    {
        "file": "meta_broker_report.txt",
        "source_type": "broker_report",
        "ticker": "META",
        "desc": "Goldman Buy initiation -- bullish (AI ads + Reels + RL narrowing)",
    },
    {
        "file": "meta_regulatory_eu.txt",
        "source_type": "news",
        "ticker": "META",
        "desc": "EU $1.8B fine + ad targeting restrictions -- bearish regulatory",
    },
    # --- MSFT: 2 docs, both bullish ---
    {
        "file": "msft_press_release.txt",
        "source_type": "press_release",
        "ticker": "MSFT",
        "desc": "MSFT Q2 earnings press release -- bullish (Azure +31%, Copilot traction)",
    },
    {
        "file": "msft_azure_growth.txt",
        "source_type": "news",
        "ticker": "MSFT",
        "desc": "Azure AI $15B run rate -- bullish (but non-AI cloud decelerating)",
    },
    # --- GOOGL: 2 docs, one bullish one bearish ---
    {
        "file": "googl_ai_search.txt",
        "source_type": "news",
        "ticker": "GOOGL",
        "desc": "AI Overviews boost ad revenue -- bullish monetization signal",
    },
    {
        "file": "googl_antitrust.txt",
        "source_type": "news",
        "ticker": "GOOGL",
        "desc": "DOJ proposes Chrome divestiture -- bearish regulatory risk",
    },
]

# Thesis definitions per ticker
THESES = {
    "NVDA": {
        "title": "AI Infrastructure Capex Thesis",
        "summary": "NVIDIA is the primary beneficiary of the multi-year AI infrastructure buildout, with dominant market share in training and inference GPUs.",
        "initial_score": 65.0,
        "initial_state": ThesisState.STRENGTHENING,
    },
    "AAPL": {
        "title": "Apple Services Growth Thesis",
        "summary": "Apple's high-margin Services segment will drive earnings growth and multiple expansion even as hardware growth slows.",
        "initial_score": 55.0,
        "initial_state": ThesisState.STABLE,
    },
    "TSLA": {
        "title": "Tesla Platform Transition Thesis",
        "summary": "Tesla will transition from a pure automaker to a diversified energy/autonomy platform, unlocking new revenue streams.",
        "initial_score": 45.0,
        "initial_state": ThesisState.FORMING,
    },
    "AMZN": {
        "title": "AWS Cloud Dominance Thesis",
        "summary": "AWS will maintain cloud leadership and AI workloads will accelerate revenue growth and margin expansion.",
        "initial_score": 60.0,
        "initial_state": ThesisState.STABLE,
    },
    "META": {
        "title": "AI-Powered Advertising Thesis",
        "summary": "Meta's AI investments in ad targeting and Reels monetization will drive sustained revenue acceleration and margin expansion.",
        "initial_score": 58.0,
        "initial_state": ThesisState.STRENGTHENING,
    },
    "MSFT": {
        "title": "Azure + Copilot AI Monetization Thesis",
        "summary": "Microsoft will monetize AI through Azure AI services and Copilot for M365, driving accelerating cloud revenue growth.",
        "initial_score": 62.0,
        "initial_state": ThesisState.STRENGTHENING,
    },
    "GOOGL": {
        "title": "Search AI Monetization Thesis",
        "summary": "Google will successfully monetize AI-powered search, maintaining search dominance and ad revenue growth.",
        "initial_score": 50.0,
        "initial_state": ThesisState.FORMING,
    },
}


def setup_db(db_url: str):
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)
    return engine


def seed_companies_and_theses(session: Session) -> dict[str, Thesis]:
    """Create companies and theses, return {ticker: thesis}."""
    theses = {}
    for ticker, tdef in THESES.items():
        company = Company(ticker=ticker, name=ticker)
        session.add(company)
        session.flush()

        thesis = Thesis(
            title=tdef["title"],
            company_ticker=ticker,
            state=tdef["initial_state"],
            conviction_score=tdef["initial_score"],
            summary=tdef["summary"],
        )
        session.add(thesis)
        session.flush()
        theses[ticker] = thesis

    session.commit()
    return theses


def run_single_document(session, doc_def, theses, extractor_type, use_llm_update):
    """Ingest one document and run thesis update. Returns structured result dict."""
    file_path = os.path.join(FIXTURES_DIR, doc_def["file"])
    ticker = doc_def["ticker"]
    source_type_map = {st.value: st for st in SourceType}

    result = {"document": doc_def["desc"], "file": doc_def["file"], "ticker": ticker}

    # --- Ingestion ---
    t0 = time.time()
    try:
        ingest_result = run_ingestion(
            session,
            file_path=file_path,
            source_type=source_type_map[doc_def["source_type"]],
            ticker=ticker,
            extractor_type=extractor_type,
        )
        session.commit()
        ingest_time = round(time.time() - t0, 2)

        # Fetch claims for inspection
        claims = session.scalars(
            select(Claim).where(Claim.document_id == ingest_result.document_id)
        ).all()

        claims_data = []
        for c in claims:
            claims_data.append({
                "id": c.id,
                "text": c.claim_text_normalized,
                "short": c.claim_text_short,
                "type": c.claim_type.value,
                "channel": c.economic_channel.value,
                "direction": c.direction.value,
                "strength": c.strength,
                "novelty": c.novelty_type.value,
                "confidence": c.confidence,
                "is_structural": c.is_structural,
                "is_ephemeral": c.is_ephemeral,
            })

        result["ingestion"] = {
            "document_id": ingest_result.document_id,
            "num_claims": ingest_result.num_claims,
            "tickers_linked": ingest_result.tickers_linked,
            "themes_linked": ingest_result.themes_linked,
            "time_seconds": ingest_time,
            "claims": claims_data,
        }
    except Exception as e:
        result["ingestion"] = {"error": str(e)}
        return result

    # --- Thesis update ---
    thesis = theses[ticker]
    claim_ids = [c.id for c in claims]

    before_state = thesis.state.value
    before_score = thesis.conviction_score

    t1 = time.time()
    try:
        update_result = update_thesis_from_claims(
            session,
            thesis.id,
            claim_ids,
            use_llm=use_llm_update,
        )
        session.commit()
        update_time = round(time.time() - t1, 2)

        result["thesis_update"] = {
            "thesis_title": thesis.title,
            "before_state": before_state,
            "after_state": update_result["after_state"],
            "before_score": before_score,
            "after_score": update_result["after_score"],
            "score_delta": round(update_result["after_score"] - before_score, 2),
            "summary_note": update_result.get("summary_note", ""),
            "time_seconds": update_time,
            "assessments": update_result.get("assessments", []),
        }
    except Exception as e:
        result["thesis_update"] = {"error": str(e)}

    return result


def print_summary(results):
    """Print a human-readable summary to console."""
    print("\n" + "=" * 80)
    print("  PIPELINE EVALUATION SUMMARY")
    print("=" * 80)

    for i, r in enumerate(results, 1):
        print(f"\n{'-' * 80}")
        print(f"  [{i:02d}] {r['document']}")
        print(f"{'-' * 80}")

        ing = r.get("ingestion", {})
        if "error" in ing:
            print(f"  ERROR: INGESTION ERROR: {ing['error']}")
            continue

        print(f"  Claims extracted: {ing['num_claims']}")
        print(f"  Tickers: {', '.join(ing.get('tickers_linked', []))}")
        print(f"  Themes:  {', '.join(ing.get('themes_linked', []))}")
        print(f"  Ingest time: {ing.get('time_seconds', '?')}s")

        for j, claim in enumerate(ing.get("claims", []), 1):
            print(f"    claim {j}: [{claim['direction']:8s}] "
                  f"str={claim['strength']:.2f} nov={claim['novelty']:11s} "
                  f"conf={claim['confidence']:.2f}  "
                  f"| {claim['short']}")

        upd = r.get("thesis_update", {})
        if "error" in upd:
            print(f"  ERROR: THESIS UPDATE ERROR: {upd['error']}")
            continue

        state_arrow = f"{upd['before_state']} -> {upd['after_state']}"
        score_arrow = f"{upd['before_score']:.1f} -> {upd['after_score']:.1f} (d={upd['score_delta']:+.2f})"
        print(f"\n  Thesis: {upd.get('thesis_title', '?')}")
        print(f"  State:  {state_arrow}")
        print(f"  Score:  {score_arrow}")
        print(f"  Note:   {upd.get('summary_note', '')}")
        print(f"  Update time: {upd.get('time_seconds', '?')}s")

        for a in upd.get("assessments", []):
            print(f"    claim_id={a['claim_id']:3d}  impact={a['impact']:12s}  "
                  f"materiality={a['materiality']:.2f}  delta={a['delta']:+.4f}")

    # --- Per-ticker thesis journey ---
    print(f"\n{'=' * 80}")
    print("  THESIS JOURNEYS (cumulative)")
    print(f"{'=' * 80}")

    ticker_journey = {}
    for r in results:
        t = r["ticker"]
        upd = r.get("thesis_update", {})
        if "error" not in upd and "after_score" in upd:
            if t not in ticker_journey:
                ticker_journey[t] = []
            ticker_journey[t].append({
                "doc": r["file"],
                "state": upd["after_state"],
                "score": upd["after_score"],
                "delta": upd["score_delta"],
            })

    for ticker, steps in sorted(ticker_journey.items()):
        initial = THESES[ticker]
        print(f"\n  {ticker} -- {initial['title']}")
        print(f"    START: state={initial['initial_state'].value}, score={initial['initial_score']}")
        for s in steps:
            print(f"    -> {s['doc']:40s}  state={s['state']:14s}  "
                  f"score={s['score']:5.1f}  (d={s['delta']:+.2f})")


def main():
    parser = argparse.ArgumentParser(description="Pipeline evaluation runner")
    parser.add_argument("--extractor", choices=["stub", "llm"], default="llm",
                        help="Claim extractor type (default: llm)")
    parser.add_argument("--use-llm-update", action="store_true", default=False,
                        help="Use LLM for thesis update classification too")
    parser.add_argument("--output", default="eval_output.json",
                        help="Output JSON file path")
    parser.add_argument("--db-url", default="sqlite:///eval.db",
                        help="Database URL (default: sqlite:///eval.db)")
    args = parser.parse_args()

    print(f"Extractor: {args.extractor}")
    print(f"LLM thesis update: {args.use_llm_update}")
    print(f"Output: {args.output}")
    print(f"Documents: {len(DOCUMENTS)}")
    print()

    engine = setup_db(args.db_url)

    with Session(engine) as session:
        theses = seed_companies_and_theses(session)

        results = []
        for i, doc_def in enumerate(DOCUMENTS, 1):
            print(f"[{i:02d}/{len(DOCUMENTS)}] Processing: {doc_def['desc']}...")
            result = run_single_document(
                session, doc_def, theses,
                extractor_type=args.extractor,
                use_llm_update=args.use_llm_update,
            )
            results.append(result)

        print_summary(results)

    # Save full output
    output = {
        "timestamp": datetime.utcnow().isoformat(),
        "config": {
            "extractor": args.extractor,
            "use_llm_update": args.use_llm_update,
            "num_documents": len(DOCUMENTS),
        },
        "theses_initial": {
            t: {"title": d["title"], "score": d["initial_score"], "state": d["initial_state"].value}
            for t, d in THESES.items()
        },
        "results": results,
    }

    with open(args.output, "w") as f:
        json.dump(output, f, indent=2, default=str)

    print(f"\nFull output saved to: {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
