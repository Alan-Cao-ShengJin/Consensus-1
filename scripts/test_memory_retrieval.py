#!/usr/bin/env python
"""Inspect the memory snapshot for a given thesis.

Usage:
    python scripts/test_memory_retrieval.py --thesis-id 1
    python scripts/test_memory_retrieval.py --thesis-id 1 --limit 20
"""
import argparse
import os
import sys

# Ensure project root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from models import Base
from memory_retrieval import retrieve_memory


def main():
    parser = argparse.ArgumentParser(description="Inspect memory snapshot for a thesis")
    parser.add_argument("--thesis-id", type=int, required=True, help="Thesis ID to inspect")
    parser.add_argument("--db", type=str, default="sqlite:///consensus1.db", help="Database URL")
    parser.add_argument("--limit", type=int, default=10, help="Max thesis-linked claims")
    args = parser.parse_args()

    engine = create_engine(args.db)
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        try:
            snap = retrieve_memory(
                session,
                args.thesis_id,
                thesis_claims_limit=args.limit,
            )
        except ValueError as e:
            print(f"Error: {e}")
            sys.exit(1)

        print("=" * 70)
        print(f"MEMORY SNAPSHOT FOR THESIS #{snap.thesis_id}")
        print(f"  Title:      {snap.thesis_title}")
        print(f"  Company:    {snap.company_ticker}")
        print(f"  State:      {snap.current_state}")
        print(f"  Conviction: {snap.current_conviction:.1f}")
        print("=" * 70)
        print(f"\nTotal prior claims: {snap.total_prior_claims}")
        print(f"  Thesis-linked: {len(snap.thesis_claims)}")
        print(f"  Company:       {len(snap.company_claims)}")
        print(f"  Theme:         {len(snap.theme_claims)}")
        print(f"State history:   {len(snap.state_history)} entries")
        print(f"Checkpoints:     {len(snap.checkpoints)}")
        print()
        print("--- Prompt text ---")
        print(snap.to_prompt_text())
        print()


if __name__ == "__main__":
    main()
