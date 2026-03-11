#!/usr/bin/env python
"""Quick script to run source validation and print results.

Usage:
    python scripts/test_sources.py              # run all tests
    python scripts/test_sources.py --source sec # run only SEC EDGAR test

Set FINNHUB_API_KEY env var to test Finnhub (skipped otherwise).
"""
import sys
import os

# Ensure project root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from source_validation import (
    run_all,
    test_yfinance,
    test_sec_edgar,
    test_finnhub,
    test_google_news_rss,
    test_prnewswire_rss,
    audit_universe,
    _print_results,
    TestResult,
)


def main():
    source_filter = None
    if "--source" in sys.argv:
        idx = sys.argv.index("--source")
        if idx + 1 < len(sys.argv):
            source_filter = sys.argv[idx + 1].lower()

    if source_filter:
        results: list[TestResult] = []
        if source_filter in ("yfinance", "yf", "price"):
            results.extend(test_yfinance())
        elif source_filter in ("sec", "edgar", "sec_edgar"):
            results.append(test_sec_edgar())
        elif source_filter in ("finnhub", "news", "finn"):
            results.append(test_finnhub())
        elif source_filter in ("google", "google_rss", "gnews"):
            results.append(test_google_news_rss())
        elif source_filter in ("prnewswire", "pr", "rss"):
            results.append(test_prnewswire_rss())
        else:
            print(f"Unknown source: {source_filter}")
            print("Valid: yfinance, sec, finnhub, google, prnewswire")
            sys.exit(1)

        audit = audit_universe()
        _print_results(results, audit)
    else:
        results, audit = run_all()
        _print_results(results, audit)

    if any(r.status == "FAIL" for r in results):
        sys.exit(1)


if __name__ == "__main__":
    main()
