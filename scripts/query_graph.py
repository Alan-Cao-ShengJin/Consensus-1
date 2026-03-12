"""CLI entrypoint: query the Consensus knowledge graph for explainability.

Usage:
  python scripts/query_graph.py --why-own NVDA
  python scripts/query_graph.py --thesis-evolution NVDA
  python scripts/query_graph.py --thesis-evidence 12
  python scripts/query_graph.py --company-summary NVDA
  python scripts/query_graph.py --themes NVDA
  python scripts/query_graph.py --cross-themes NVDA MSFT
  python scripts/query_graph.py --state-transition 12 --from-state stable --to-state weakening
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import get_session
from graph_sync import build_full_graph, build_ticker_graph
from graph_queries import (
    why_own, format_why_own,
    thesis_evolution, thesis_evolution_by_ticker, format_thesis_evolution,
    thesis_evidence, documents_for_thesis,
    themes_for_company, cross_company_themes, companies_sharing_theme,
    company_summary, explain_state_transition,
    claims_for_thesis,
)


def setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def main():
    parser = argparse.ArgumentParser(
        description="Query the Consensus knowledge graph",
    )

    query = parser.add_mutually_exclusive_group(required=True)
    query.add_argument("--why-own", type=str, metavar="TICKER",
                       help="Explain why a stock is owned / watched")
    query.add_argument("--thesis-evolution", type=str, metavar="TICKER",
                       help="Show thesis state evolution for a ticker")
    query.add_argument("--thesis-evidence", type=int, metavar="THESIS_ID",
                       help="Show all evidence for a thesis")
    query.add_argument("--thesis-docs", type=int, metavar="THESIS_ID",
                       help="Show documents that influenced a thesis")
    query.add_argument("--thesis-claims", type=int, metavar="THESIS_ID",
                       help="Show claims linked to a thesis")
    query.add_argument("--company-summary", type=str, metavar="TICKER",
                       help="Full graph-derived summary for a company")
    query.add_argument("--themes", type=str, metavar="TICKER",
                       help="Show themes connected to a company")
    query.add_argument("--cross-themes", nargs=2, metavar="TICKER",
                       help="Show shared themes between two companies")
    query.add_argument("--state-transition", type=int, metavar="THESIS_ID",
                       help="Explain a thesis state transition")

    parser.add_argument("--from-state", type=str, help="Starting state (for --state-transition)")
    parser.add_argument("--to-state", type=str, help="Ending state (for --state-transition)")
    parser.add_argument("--json", dest="json_output", action="store_true", help="JSON output")
    parser.add_argument("--verbose", "-v", action="store_true")

    args = parser.parse_args()
    setup_logging(args.verbose)

    # Build graph from DB
    with get_session() as session:
        # Use ticker-specific graph when possible for efficiency
        if args.why_own:
            cg = build_ticker_graph(session, args.why_own)
        elif args.thesis_evolution:
            cg = build_ticker_graph(session, args.thesis_evolution)
        elif args.company_summary:
            cg = build_ticker_graph(session, args.company_summary)
        elif args.themes:
            cg = build_ticker_graph(session, args.themes)
        else:
            cg = build_full_graph(session)

    # Execute query
    if args.why_own:
        result = why_own(cg, args.why_own)
        if args.json_output:
            print(json.dumps(result, indent=2, default=str))
        else:
            print(format_why_own(result))

    elif args.thesis_evolution:
        evolutions = thesis_evolution_by_ticker(cg, args.thesis_evolution)
        if args.json_output:
            print(json.dumps(evolutions, indent=2, default=str))
        else:
            if not evolutions:
                print(f"No theses found for {args.thesis_evolution}")
            for tid, evo in evolutions.items():
                print(format_thesis_evolution(evo, tid))
                print()

    elif args.thesis_evidence:
        result = thesis_evidence(cg, args.thesis_evidence)
        if args.json_output:
            print(json.dumps(result, indent=2, default=str))
        else:
            print(f"=== Thesis {args.thesis_evidence}: {result.get('title', '?')} ===")
            print(f"  State: {result.get('state')}  Conviction: {result.get('conviction_score')}")
            print(f"  Total claims: {result.get('total_claims')}")
            print(f"  Supporting: {len(result.get('supporting_claims', []))}")
            print(f"  Weakening: {len(result.get('weakening_claims', []))}")
            for c in result.get("supporting_claims", [])[:5]:
                print(f"    [+] {c['claim_text_short']}")
            for c in result.get("weakening_claims", [])[:5]:
                print(f"    [-] {c['claim_text_short']}")

    elif args.thesis_docs:
        result = documents_for_thesis(cg, args.thesis_docs)
        if args.json_output:
            print(json.dumps(result, indent=2, default=str))
        else:
            print(f"=== Documents influencing thesis {args.thesis_docs} ===")
            for d in result:
                print(f"  [{d.get('source_type')}] {d.get('title')} ({d.get('published_at')})")

    elif args.thesis_claims:
        result = claims_for_thesis(cg, args.thesis_claims)
        if args.json_output:
            print(json.dumps(result, indent=2, default=str))
        else:
            print(f"=== Claims linked to thesis {args.thesis_claims} ===")
            for c in result:
                print(f"  [{c.get('link_type')}] [{c.get('direction')}] {c.get('claim_text_short')}")

    elif args.company_summary:
        result = company_summary(cg, args.company_summary)
        if args.json_output:
            print(json.dumps(result, indent=2, default=str))
        else:
            print(f"=== {result.get('ticker')} — {result.get('name')} ===")
            print(f"  Sector: {result.get('sector')} / {result.get('industry')}")
            print(f"  Documents: {result.get('documents')}")
            print(f"  Claims: {result.get('claims')}")
            print(f"  Theses: {result.get('theses')}")
            print(f"  Positions: {result.get('positions')}")
            print(f"  Candidates: {result.get('candidates')}")
            if result.get("themes"):
                print(f"  Themes: {', '.join(t['theme_name'] for t in result['themes'])}")

    elif args.themes:
        result = themes_for_company(cg, args.themes)
        if args.json_output:
            print(json.dumps(result, indent=2, default=str))
        else:
            print(f"=== Themes for {args.themes} ===")
            for t in result:
                print(f"  [{t.get('theme_type', '?')}] {t.get('theme_name')}")

    elif args.cross_themes:
        ticker_a, ticker_b = args.cross_themes
        result = cross_company_themes(cg, ticker_a, ticker_b)
        if args.json_output:
            print(json.dumps(result, indent=2, default=str))
        else:
            print(f"=== Shared themes: {ticker_a} & {ticker_b} ===")
            if not result:
                print("  No shared themes found.")
            for t in result:
                print(f"  {t.get('theme_name')}")

    elif args.state_transition:
        result = explain_state_transition(
            cg, args.state_transition,
            from_state=args.from_state,
            to_state=args.to_state,
        )
        if args.json_output:
            print(json.dumps(result, indent=2, default=str))
        else:
            print(f"=== State transition for thesis {args.state_transition} ===")
            if result.get("status") == "no_history":
                print("  No state history found.")
            else:
                for e in result.get("state_path", []):
                    print(f"  {e['created_at']}  {e['state']}  conviction={e['conviction_score']}")


if __name__ == "__main__":
    main()
