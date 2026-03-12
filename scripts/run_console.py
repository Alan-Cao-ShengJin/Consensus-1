"""CLI entrypoint: launch the operator console.

Usage:
  python scripts/run_console.py
  python scripts/run_console.py --port 8080
  python scripts/run_console.py --demo
  python scripts/run_console.py --no-graph
  python scripts/run_console.py --host 0.0.0.0 --port 5000
  python scripts/run_console.py --focus latest-thesis-delta
  python scripts/run_console.py --no-auto-refresh
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def main():
    parser = argparse.ArgumentParser(
        description="Launch the Consensus operator console",
    )
    parser.add_argument("--host", type=str, default="127.0.0.1",
                       help="Host to bind to (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=5000,
                       help="Port to listen on (default: 5000)")
    parser.add_argument("--demo", action="store_true",
                       help="Run in demo mode (badge shown in UI)")
    parser.add_argument("--no-graph", dest="load_graph", action="store_false",
                       default=True,
                       help="Skip loading the graph layer")
    parser.add_argument("--focus", type=str, default=None,
                       choices=["latest-thesis-delta", "latest-actionable",
                                "latest-trigger"],
                       help="Pre-select a demo subject on launch")
    parser.add_argument("--no-auto-refresh", dest="auto_refresh",
                       action="store_false", default=True,
                       help="Disable auto-refresh (useful during demos)")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--debug", action="store_true",
                       help="Enable Flask debug mode (auto-reload)")

    args = parser.parse_args()
    setup_logging(args.verbose)

    logger = logging.getLogger("console")

    # Load graph if requested
    graph = None
    if args.load_graph:
        try:
            from db import get_session
            from graph_sync import build_full_graph
            logger.info("Building graph from database...")
            with get_session() as session:
                graph = build_full_graph(session)
            summary = graph.summary()
            logger.info(
                "Graph loaded: %d nodes, %d edges",
                summary["total_nodes"], summary["total_edges"],
            )
        except Exception as e:
            logger.warning("Could not load graph: %s", e)
            logger.info("Console will run without graph views.")

    # Create and run app
    from console_app import create_console_app
    app = create_console_app(
        graph=graph,
        demo_mode=args.demo,
    )
    app.config["AUTO_REFRESH"] = args.auto_refresh
    app.config["FOCUS"] = args.focus

    logger.info("=" * 50)
    logger.info("CONSENSUS OPERATOR CONSOLE")
    logger.info("=" * 50)
    logger.info("URL: http://%s:%d", args.host, args.port)
    if args.demo:
        logger.info("Mode: DEMO")
    if args.focus:
        logger.info("Focus: %s", args.focus)
    if not args.auto_refresh:
        logger.info("Auto-refresh: DISABLED")
    logger.info("Graph: %s", "loaded" if graph else "not loaded")
    logger.info("=" * 50)

    app.run(
        host=args.host,
        port=args.port,
        debug=args.debug,
        use_reloader=args.debug,
    )


if __name__ == "__main__":
    main()
