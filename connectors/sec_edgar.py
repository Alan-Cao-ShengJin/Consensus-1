"""SEC EDGAR connector: fetches 10-K, 10-Q, 8-K filings via EDGAR full-text search API."""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timedelta
from typing import Optional

import requests

from models import SourceType, SourceTier
from connectors.base import DocumentConnector, DocumentPayload

logger = logging.getLogger(__name__)

# Mapping from filing type to source registry key and SourceType
_FILING_MAP = {
    "10-K": ("sec_10k", SourceType.TEN_K),
    "10-Q": ("sec_10q", SourceType.TEN_Q),
    "8-K": ("sec_8k", SourceType.EIGHT_K),
}

_EFTS_BASE = "https://efts.sec.gov/LATEST/search-index/0"
_SUBMISSIONS_BASE = "https://data.sec.gov/submissions"
_FILINGS_BASE = "https://www.sec.gov/cgi-bin/browse-edgar"
_FULL_TEXT_SEARCH = "https://efts.sec.gov/LATEST/search-index"
_EDGAR_SEARCH_API = "https://efts.sec.gov/LATEST/search-index"
_EDGAR_SUBMISSIONS = "https://data.sec.gov/submissions"

# Rate limit: SEC asks for max 10 req/s
_MIN_REQUEST_INTERVAL = 0.12  # ~8 req/s to stay safe

_last_request_time = 0.0


def _get_user_agent() -> str:
    """Get the SEC-required User-Agent header."""
    default = "Consensus-1 Research Platform admin@example.com"
    return os.getenv("SEC_USER_AGENT", default)


def _throttled_get(url: str, params: Optional[dict] = None, headers: Optional[dict] = None) -> requests.Response:
    """Rate-limited GET request to SEC."""
    global _last_request_time
    elapsed = time.time() - _last_request_time
    if elapsed < _MIN_REQUEST_INTERVAL:
        time.sleep(_MIN_REQUEST_INTERVAL - elapsed)

    hdrs = {"User-Agent": _get_user_agent(), "Accept": "application/json"}
    if headers:
        hdrs.update(headers)

    resp = requests.get(url, params=params, headers=hdrs, timeout=30)
    _last_request_time = time.time()
    resp.raise_for_status()
    return resp


def _fetch_company_cik(ticker: str) -> Optional[str]:
    """Look up CIK number for a ticker via SEC company tickers JSON."""
    try:
        resp = _throttled_get("https://www.sec.gov/files/company_tickers.json")
        data = resp.json()
        ticker_upper = ticker.upper()
        for entry in data.values():
            if entry.get("ticker", "").upper() == ticker_upper:
                return str(entry["cik_str"]).zfill(10)
    except Exception as e:
        logger.warning("Failed to look up CIK for %s: %s", ticker, e)
    return None


class SECEdgarConnector(DocumentConnector):
    """Fetches SEC filings (10-K, 10-Q, 8-K) for a ticker via EDGAR."""

    def __init__(self, filing_types: Optional[list[str]] = None):
        self._filing_types = filing_types or ["10-K", "10-Q", "8-K"]

    @property
    def source_key(self) -> str:
        return "sec_edgar"

    def fetch(self, ticker: str, days: int = 30) -> list[DocumentPayload]:
        cik = _fetch_company_cik(ticker)
        if not cik:
            logger.warning("No CIK found for ticker %s, skipping SEC", ticker)
            return []

        payloads = []
        cutoff = datetime.utcnow() - timedelta(days=days)

        try:
            url = f"{_EDGAR_SUBMISSIONS}/CIK{cik}.json"
            resp = _throttled_get(url)
            data = resp.json()
        except Exception as e:
            logger.error("Failed to fetch submissions for %s (CIK %s): %s", ticker, cik, e)
            return []

        recent = data.get("filings", {}).get("recent", {})
        if not recent:
            return []

        forms = recent.get("form", [])
        dates = recent.get("filingDate", [])
        accessions = recent.get("accessionNumber", [])
        primary_docs = recent.get("primaryDocument", [])

        for i in range(len(forms)):
            form_type = forms[i]
            if form_type not in self._filing_types:
                continue

            try:
                filing_date = datetime.strptime(dates[i], "%Y-%m-%d")
            except (ValueError, IndexError):
                continue

            if filing_date < cutoff:
                continue

            accession = accessions[i] if i < len(accessions) else None
            primary_doc = primary_docs[i] if i < len(primary_docs) else None

            if not accession or not primary_doc:
                continue

            accession_clean = accession.replace("-", "")
            filing_url = f"https://www.sec.gov/Archives/edgar/data/{cik.lstrip('0')}/{accession_clean}/{primary_doc}"

            source_key, source_type = _FILING_MAP.get(form_type, ("sec_8k", SourceType.EIGHT_K))

            # Fetch the filing text
            raw_text = ""
            try:
                text_resp = _throttled_get(filing_url, headers={"Accept": "text/html"})
                raw_text = text_resp.text[:500_000]  # cap at 500KB
            except Exception as e:
                logger.warning("Failed to fetch filing text for %s %s: %s", ticker, accession, e)

            payloads.append(DocumentPayload(
                source_key=source_key,
                source_type=source_type,
                source_tier=SourceTier.TIER_1,
                ticker=ticker,
                title=f"{ticker} {form_type} filed {dates[i]}",
                url=filing_url,
                published_at=filing_date,
                author="SEC EDGAR",
                external_id=accession,
                raw_text=raw_text,
                metadata={"form_type": form_type, "cik": cik, "accession": accession},
            ))

        logger.info("SEC EDGAR: fetched %d filings for %s (days=%d)", len(payloads), ticker, days)
        return payloads
