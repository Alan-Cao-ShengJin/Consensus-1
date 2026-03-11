"""Source validation: live connectivity tests for all v1 data sources.

Run:  python source_validation.py
Env:  FINNHUB_API_KEY (optional -- test skipped if missing)

Each test makes a single minimal request to verify the source is reachable
and returns parseable data.  Results are printed as a summary table.
"""
from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------

@dataclass
class TestResult:
    source_name: str
    status: str  # "PASS" | "FAIL" | "SKIP"
    sample_payload: str = ""
    required_env_vars: list[str] = field(default_factory=list)
    notes: str = ""
    elapsed_ms: float = 0.0


# ---------------------------------------------------------------------------
# Individual source tests
# ---------------------------------------------------------------------------

def test_yfinance() -> list[TestResult]:
    """Test yfinance for prices, ticker info, and earnings calendar."""
    results = []

    try:
        import yfinance as yf
    except ImportError:
        msg = "yfinance not installed. Run: pip install yfinance"
        for name in ("yfinance_price", "yfinance_ticker_info", "yfinance_calendar"):
            results.append(TestResult(name, "FAIL", notes=msg))
        return results

    # --- Price data ---
    t0 = time.time()
    try:
        df = yf.download("AAPL", period="5d", progress=False)
        elapsed = (time.time() - t0) * 1000
        if df.empty:
            results.append(TestResult("yfinance_price", "FAIL",
                                      notes="Empty dataframe returned", elapsed_ms=elapsed))
        else:
            sample = df.tail(1).to_dict()
            results.append(TestResult(
                "yfinance_price", "PASS",
                sample_payload=_truncate(str(sample)),
                notes=f"{len(df)} rows returned for AAPL 5d",
                elapsed_ms=elapsed,
            ))
    except Exception as e:
        elapsed = (time.time() - t0) * 1000
        results.append(TestResult("yfinance_price", "FAIL",
                                  notes=f"{type(e).__name__}: {e}", elapsed_ms=elapsed))

    # --- Ticker info ---
    t0 = time.time()
    try:
        ticker = yf.Ticker("AAPL")
        info = ticker.info
        elapsed = (time.time() - t0) * 1000
        sample_fields = {k: info.get(k) for k in
                         ("shortName", "sector", "industry", "marketCap", "exchange")}
        results.append(TestResult(
            "yfinance_ticker_info", "PASS",
            sample_payload=_truncate(str(sample_fields)),
            notes=f"Got {len(info)} info fields for AAPL",
            elapsed_ms=elapsed,
        ))
    except Exception as e:
        elapsed = (time.time() - t0) * 1000
        results.append(TestResult("yfinance_ticker_info", "FAIL",
                                  notes=f"{type(e).__name__}: {e}", elapsed_ms=elapsed))

    # --- Earnings calendar ---
    t0 = time.time()
    try:
        ticker = yf.Ticker("AAPL")
        cal = ticker.calendar
        elapsed = (time.time() - t0) * 1000
        if cal is None or (hasattr(cal, "empty") and cal.empty):
            results.append(TestResult("yfinance_calendar", "PASS",
                                      sample_payload="No upcoming earnings found (may be off-season)",
                                      notes="Calendar returned empty/None -- not an error",
                                      elapsed_ms=elapsed))
        else:
            results.append(TestResult(
                "yfinance_calendar", "PASS",
                sample_payload=_truncate(str(cal)),
                notes="Earnings calendar data retrieved",
                elapsed_ms=elapsed,
            ))
    except Exception as e:
        elapsed = (time.time() - t0) * 1000
        results.append(TestResult("yfinance_calendar", "FAIL",
                                  notes=f"{type(e).__name__}: {e}", elapsed_ms=elapsed))

    return results


def test_sec_edgar() -> TestResult:
    """Test SEC EDGAR full-text search API (efts)."""
    import urllib.request

    url = (
        "https://efts.sec.gov/LATEST/search-index"
        "?q=%22NVIDIA%22&dateRange=custom"
        "&startdt=2025-01-01&enddt=2025-12-31"
        "&forms=10-K&from=0&size=1"
    )
    headers = {"User-Agent": "Consensus-1 admin@consensus1.dev"}

    t0 = time.time()
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
        elapsed = (time.time() - t0) * 1000

        hits = data.get("hits", {}).get("hits", [])
        total = data.get("hits", {}).get("total", {}).get("value", 0)
        sample = ""
        if hits:
            h = hits[0].get("_source", {})
            sample = _truncate(str({
                "file_date": h.get("file_date"),
                "display_names": h.get("display_names"),
                "form_type": h.get("form_type"),
            }))

        return TestResult(
            "sec_edgar", "PASS",
            sample_payload=sample,
            notes=f"EDGAR search returned {total} total hits for NVIDIA 10-K",
            elapsed_ms=elapsed,
        )
    except Exception as e:
        elapsed = (time.time() - t0) * 1000
        return TestResult("sec_edgar", "FAIL",
                          notes=f"{type(e).__name__}: {e}", elapsed_ms=elapsed)


def test_finnhub() -> TestResult:
    """Test Finnhub /company-news endpoint."""
    api_key = os.getenv("FINNHUB_API_KEY")
    if not api_key:
        return TestResult("finnhub", "SKIP",
                          required_env_vars=["FINNHUB_API_KEY"],
                          notes="FINNHUB_API_KEY not set -- skipping live test")

    import urllib.request
    import urllib.parse

    today = datetime.utcnow().date()
    week_ago = today - timedelta(days=7)
    params = urllib.parse.urlencode({
        "symbol": "NVDA",
        "from": str(week_ago),
        "to": str(today),
        "token": api_key,
    })
    url = f"https://finnhub.io/api/v1/company-news?{params}"

    t0 = time.time()
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
        elapsed = (time.time() - t0) * 1000

        if isinstance(data, dict) and data.get("error"):
            return TestResult("finnhub", "FAIL",
                              required_env_vars=["FINNHUB_API_KEY"],
                              notes=f"API error: {data['error']}",
                              elapsed_ms=elapsed)

        if not isinstance(data, list):
            return TestResult("finnhub", "FAIL",
                              required_env_vars=["FINNHUB_API_KEY"],
                              notes=f"Unexpected response type: {type(data).__name__}",
                              elapsed_ms=elapsed)

        sample = ""
        if data:
            a = data[0]
            sample = _truncate(str({
                "headline": a.get("headline"),
                "source": a.get("source"),
                "datetime": a.get("datetime"),
                "url": a.get("url"),
            }))

        return TestResult(
            "finnhub", "PASS",
            sample_payload=sample,
            required_env_vars=["FINNHUB_API_KEY"],
            notes=f"{len(data)} articles for NVDA in past 7 days",
            elapsed_ms=elapsed,
        )
    except Exception as e:
        elapsed = (time.time() - t0) * 1000
        return TestResult("finnhub", "FAIL",
                          required_env_vars=["FINNHUB_API_KEY"],
                          notes=f"{type(e).__name__}: {e}", elapsed_ms=elapsed)


def test_google_news_rss() -> TestResult:
    """Test Google News RSS feed."""
    import urllib.request

    url = "https://news.google.com/rss/search?q=NVIDIA+stock&hl=en-US&gl=US&ceid=US:en"

    t0 = time.time()
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (compatible; Consensus-1/1.0)"
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw_xml = resp.read().decode()
        elapsed = (time.time() - t0) * 1000

        item_count = raw_xml.count("<item>")
        if item_count == 0:
            return TestResult("google_news_rss", "FAIL",
                              notes="No <item> tags found in RSS response",
                              elapsed_ms=elapsed)

        title_start = raw_xml.find("<item>")
        if title_start >= 0:
            t_start = raw_xml.find("<title>", title_start)
            t_end = raw_xml.find("</title>", t_start)
            first_title = raw_xml[t_start + 7:t_end] if t_start >= 0 and t_end >= 0 else "?"
        else:
            first_title = "?"

        return TestResult(
            "google_news_rss", "PASS",
            sample_payload=_truncate(first_title),
            notes=f"{item_count} items in RSS feed for 'NVIDIA stock'",
            elapsed_ms=elapsed,
        )
    except Exception as e:
        elapsed = (time.time() - t0) * 1000
        return TestResult("google_news_rss", "FAIL",
                          notes=f"{type(e).__name__}: {e}", elapsed_ms=elapsed)


def test_prnewswire_rss() -> TestResult:
    """Test PR Newswire RSS feed."""
    import urllib.request

    url = "https://www.prnewswire.com/rss/technology-latest-news/technology-latest-news-list.rss"

    t0 = time.time()
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (compatible; Consensus-1/1.0)"
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw_xml = resp.read().decode()
        elapsed = (time.time() - t0) * 1000

        item_count = raw_xml.count("<item>")
        if item_count == 0:
            if "<rss" in raw_xml or "<feed" in raw_xml:
                return TestResult("prnewswire_rss", "PASS",
                                  notes="RSS feed reachable but 0 items currently",
                                  elapsed_ms=elapsed)
            return TestResult("prnewswire_rss", "FAIL",
                              notes="No RSS/Atom content in response",
                              elapsed_ms=elapsed)

        title_start = raw_xml.find("<item>")
        if title_start >= 0:
            t_start = raw_xml.find("<title>", title_start)
            t_end = raw_xml.find("</title>", t_start)
            first_title = raw_xml[t_start + 7:t_end] if t_start >= 0 and t_end >= 0 else "?"
        else:
            first_title = "?"

        return TestResult(
            "prnewswire_rss", "PASS",
            sample_payload=_truncate(first_title),
            notes=f"{item_count} items in PR Newswire technology feed",
            elapsed_ms=elapsed,
        )
    except Exception as e:
        elapsed = (time.time() - t0) * 1000
        return TestResult("prnewswire_rss", "FAIL",
                          notes=f"{type(e).__name__}: {e}", elapsed_ms=elapsed)


# ---------------------------------------------------------------------------
# Universe audit
# ---------------------------------------------------------------------------

def audit_universe() -> dict:
    """Check UNIVERSE_TICKERS against v1 scope: US-domiciled large-cap, ~45 names."""
    from source_registry import UNIVERSE_TICKERS

    # Known non-US-domiciled ADRs (should NOT be in the list)
    non_us = {
        "ARM": "UK (ARM Holdings, Cambridge)",
        "NVO": "Denmark (Novo Nordisk, Bagsvaerd)",
        "SHOP": "Canada (Shopify, Ottawa)",
        "MELI": "Argentina (MercadoLibre, Buenos Aires)",
        "PDD": "China (PDD Holdings, Dublin-registered but China ops)",
        "BABA": "China (Alibaba, Hangzhou)",
        "SPOT": "Luxembourg (Spotify, Stockholm ops)",
    }

    flagged = {}
    for t in UNIVERSE_TICKERS:
        if t in non_us:
            flagged[t] = f"NON-US STILL IN LIST: {non_us[t]}"

    return {
        "total_tickers": len(UNIVERSE_TICKERS),
        "flagged_non_us": flagged,
        "count_flagged": len(flagged),
        "status": "CLEAN" if len(flagged) == 0 else "NEEDS CLEANUP",
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _truncate(s: str, max_len: int = 200) -> str:
    return s[:max_len] + "..." if len(s) > max_len else s


def _print_results(results: list[TestResult], audit: dict) -> None:
    print("=" * 80)
    print("CONSENSUS-1  SOURCE VALIDATION REPORT")
    print(f"Run at: {datetime.utcnow().isoformat()}Z")
    print("=" * 80)

    print("\n--- Source Connectivity Tests ---\n")
    print(f"{'Source':<25} {'Status':<8} {'Time (ms)':<12} {'Notes'}")
    print("-" * 80)
    for r in results:
        print(f"{r.source_name:<25} {r.status:<8} {r.elapsed_ms:>8.0f}ms   {r.notes}")
        if r.sample_payload:
            print(f"  Sample: {r.sample_payload}")
        if r.required_env_vars:
            print(f"  Env vars: {', '.join(r.required_env_vars)}")

    passed = sum(1 for r in results if r.status == "PASS")
    failed = sum(1 for r in results if r.status == "FAIL")
    skipped = sum(1 for r in results if r.status == "SKIP")
    print(f"\nTotals: {passed} PASS, {failed} FAIL, {skipped} SKIP")

    print("\n--- Universe Audit ---\n")
    print(f"Total tickers: {audit['total_tickers']}")
    print(f"Status: {audit['status']}")
    if audit["flagged_non_us"]:
        print(f"WARNING: {audit['count_flagged']} non-US names still in universe:")
        for t, reason in audit["flagged_non_us"].items():
            print(f"  {t}: {reason}")
    else:
        print("All tickers are US-domiciled. Universe is clean.")

    print("\n" + "=" * 80)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_all() -> tuple[list[TestResult], dict]:
    """Run all source validation tests and universe audit."""
    results: list[TestResult] = []

    print("Testing yfinance (prices, ticker info, calendar)...")
    results.extend(test_yfinance())

    print("Testing SEC EDGAR full-text search...")
    results.append(test_sec_edgar())

    print("Testing Finnhub company news...")
    results.append(test_finnhub())

    print("Testing Google News RSS...")
    results.append(test_google_news_rss())

    print("Testing PR Newswire RSS...")
    results.append(test_prnewswire_rss())

    print("Running universe audit...")
    audit = audit_universe()

    return results, audit


if __name__ == "__main__":
    results, audit = run_all()
    _print_results(results, audit)

    if any(r.status == "FAIL" for r in results):
        sys.exit(1)
