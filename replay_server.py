"""Standalone replay UI server.

Serves the replay UI and API from proof-pack artifacts.

Usage:
    python replay_server.py
    python replay_server.py --port 5001
    python replay_server.py --run-dir path/to/historical_proof_runs
"""
from __future__ import annotations

import argparse
import logging
import os

from flask import Flask, send_from_directory

from replay_api import replay_bp, set_base_dir

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)


def create_replay_app(run_dir: str = "historical_proof_runs") -> Flask:
    """Create a Flask app for the replay UI."""
    static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
    app = Flask(__name__, static_folder=static_dir)

    set_base_dir(run_dir)
    app.register_blueprint(replay_bp)

    @app.route("/")
    def index():
        return send_from_directory(static_dir, "replay.html")

    @app.route("/replay")
    def replay():
        return send_from_directory(static_dir, "replay.html")

    @app.route("/static/<path:path>")
    def static_files(path):
        return send_from_directory(static_dir, path)

    return app


def main():
    parser = argparse.ArgumentParser(description="Replay UI server")
    parser.add_argument("--port", type=int, default=5001)
    parser.add_argument("--host", type=str, default="127.0.0.1")
    parser.add_argument("--run-dir", type=str, default="historical_proof_runs")
    args = parser.parse_args()

    app = create_replay_app(run_dir=args.run_dir)

    print(f"\n  Replay UI: http://{args.host}:{args.port}/")
    print(f"  Proof runs: {os.path.abspath(args.run_dir)}")
    print(f"  API base:   http://{args.host}:{args.port}/api/replay/runs\n")

    app.run(host=args.host, port=args.port, debug=True)


if __name__ == "__main__":
    main()
