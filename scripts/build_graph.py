"""CLI entrypoint: build and export the Consensus knowledge graph.

Usage:
  python scripts/build_graph.py --full
  python scripts/build_graph.py --ticker NVDA
  python scripts/build_graph.py --ticker NVDA --export-html
  python scripts/build_graph.py --full --export-html --output-dir artifacts/graph
  python scripts/build_graph.py --thesis-id 12 --export-html
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import get_session
from graph_sync import build_full_graph, build_ticker_graph, export_graph
from graph_visualizer import (
    export_html, export_vis_json,
    company_view, thesis_view, theme_view, thesis_evolution_view,
)


def setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def main():
    parser = argparse.ArgumentParser(
        description="Build and export the Consensus knowledge graph",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--full", action="store_true", help="Full graph rebuild from DB")
    mode.add_argument("--ticker", type=str, help="Build graph for a single ticker")
    mode.add_argument("--thesis-id", type=int, help="Build graph centered on a thesis")
    mode.add_argument("--theme-id", type=int, help="Build graph centered on a theme")

    parser.add_argument("--export-html", action="store_true", help="Export standalone HTML visualization")
    parser.add_argument("--export-json", action="store_true", default=True, help="Export graph JSON (default)")
    parser.add_argument("--output-dir", type=str, default=None, help="Output directory")
    parser.add_argument("--verbose", "-v", action="store_true")

    args = parser.parse_args()
    setup_logging(args.verbose)

    today = date.today().isoformat()
    output_dir = args.output_dir or os.path.join("artifacts", "graph", today)

    with get_session() as session:
        # Build the graph
        if args.full:
            cg = build_full_graph(session)
            prefix = "full_graph"
        elif args.ticker:
            cg = build_ticker_graph(session, args.ticker)
            prefix = f"ticker_{args.ticker}"
        elif args.thesis_id:
            cg = build_full_graph(session)
            cg = thesis_view(cg, args.thesis_id)
            prefix = f"thesis_{args.thesis_id}"
        elif args.theme_id:
            cg = build_full_graph(session)
            cg = theme_view(cg, args.theme_id)
            prefix = f"theme_{args.theme_id}"

    # Summary
    summary = cg.summary()
    print(f"Graph built: {summary['total_nodes']} nodes, {summary['total_edges']} edges")
    if summary.get("node_types"):
        for nt, count in sorted(summary["node_types"].items()):
            print(f"  {nt}: {count}")

    # Export JSON
    json_path = export_graph(cg, output_dir, prefix)
    print(f"JSON exported: {json_path}")

    # Export HTML
    if args.export_html:
        html_path = os.path.join(output_dir, f"{prefix}.html")
        title = "Consensus Knowledge Graph"
        if args.ticker:
            title = f"Consensus — {args.ticker}"
        elif args.thesis_id:
            title = f"Consensus — Thesis {args.thesis_id}"
        elif args.theme_id:
            title = f"Consensus — Theme {args.theme_id}"
        export_html(cg, html_path, title=title)
        print(f"HTML exported: {html_path}")


if __name__ == "__main__":
    main()
