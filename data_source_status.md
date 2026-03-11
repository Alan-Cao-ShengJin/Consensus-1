# Data Source Status -- Consensus-1 v1

Last updated: 2026-03-11

## Classification Key

| Status | Meaning |
|--------|---------|
| **validated** | Live connectivity test passed; connector ready for v1 |
| **spec-only** | Defined in source_registry.py but connector not yet implemented |
| **manual-only** | No automated connector; user uploads/pastes content |
| **v2+ only** | Not in v1 scope; requires paid license or infrastructure not yet built |

---

## Source Status Matrix

| # | Registry Key | Provider | Status | Connector | Destination Table(s) | Cadence | Notes |
|---|-------------|----------|--------|-----------|----------------------|---------|-------|
| 1 | `price_daily` | yfinance | **validated** | `source_validation.py::test_yfinance()` | `prices` (Step 6+) | Daily 6pm ET | Free, no API key. `yfinance.download()` for OHLCV. |
| 2 | `ticker_master` | yfinance | **validated** | `source_validation.py::test_yfinance()` | `companies` | Weekly | `yfinance.Ticker.info` for sector, industry, market_cap. |
| 3 | `earnings_calendar` | yfinance | **validated** | `source_validation.py::test_yfinance()` | `checkpoints` | Daily | `yfinance.Ticker.calendar` for upcoming earnings dates. |
| 4 | `sec_10k` | SEC EDGAR | **validated** | `source_validation.py::test_sec_edgar()` | `documents`, `claims` | Daily | EDGAR full-text search API (`efts.sec.gov`). User-Agent required. |
| 5 | `sec_10q` | SEC EDGAR | **validated** | (same EDGAR connector as 10-K) | `documents`, `claims` | Daily | Same endpoint, different form type filter. |
| 6 | `sec_8k` | SEC EDGAR | **validated** | (same EDGAR connector as 10-K) | `documents`, `claims` | Daily | Same endpoint, different form type filter. Creates checkpoints. |
| 7 | `news_finnhub` | Finnhub | **validated** (with key) | `source_validation.py::test_finnhub()` | `documents`, `claims` | Every 4h | Requires `FINNHUB_API_KEY` env var. Free tier: 60 req/min, 1-year archive. Native ticker filtering via `/company-news`. |
| 8 | `news_google_rss` | Google News RSS | **validated** | `source_validation.py::test_google_news_rss()` | `documents`, `claims` | Every 4h | Free, no API key. RSS via `feedparser`. |
| 9 | `press_release_rss` | PR Newswire RSS | **validated** | `source_validation.py::test_prnewswire_rss()` | `documents`, `claims` | Every 6h | Free RSS feed. `feedparser` library. |
| 10 | `earnings_transcript_manual` | Manual upload | **manual-only** | Existing `document_loader.py` | `documents`, `claims` | On-demand | **v1 policy: manual upload only.** No automated scraping. User pastes transcript text or uploads file. See Transcript Policy below. |
| 11 | `news_manual` | Manual paste | **manual-only** | Existing `document_loader.py` | `documents`, `claims` | On-demand | For paywalled articles (FT, WSJ, Bloomberg). |
| 12 | `broker_report_manual` | Manual upload | **manual-only** | Existing `document_loader.py` | `documents`, `claims` | On-demand | **Not in v1 unless FactSet entitlement confirmed and connector tested.** Manual PDF upload as v1 workaround only. See Broker Report Policy below. |
| 13 | `investor_presentation_manual` | Manual upload | **manual-only** | Existing `document_loader.py` | `documents`, `claims` | On-demand | PDF slide decks. Requires PDF-to-text (PyMuPDF). |

---

## Transcript Policy (v1)

**Decision: Manual upload only.**

- No automated scraping of Seeking Alpha or other transcript providers in v1.
- Users paste transcript text or upload transcript files through the existing `document_loader.py` pipeline.
- Rationale: Seeking Alpha scraping is legally gray and brittle. Paid APIs (FactSet, Refinitiv) require $10k+/yr licenses not yet procured.
- Upgrade path (v2+): License a transcript API (FactSet/Refinitiv) and build an automated connector.

---

## Broker Report Policy (v1)

**Decision: Not in v1 unless FactSet entitlement confirmed and connector tested.**

- The `broker_report_manual` source exists for manual PDF uploads as a workaround.
- No automated broker report ingestion in v1 -- requires FactSet or Refinitiv data license ($10k+/yr).
- Manual upload flow: user uploads broker PDF -> PyMuPDF text extraction -> claim extraction pipeline.
- This source is classified as **manual-only**, not **validated**.

---

## Final v1 Go-Live Source List

These are the sources approved for automated pulling in v1:

| # | Source | Provider | Endpoint / Method | Destination Table(s) | Cadence | Env Vars Required |
|---|--------|----------|-------------------|----------------------|---------|-------------------|
| 1 | Daily prices | yfinance | `yfinance.download(tickers, period="2y")` | `prices` | Daily 6pm ET | None |
| 2 | Ticker master | yfinance | `yfinance.Ticker(t).info` | `companies` | Weekly | None |
| 3 | Earnings calendar | yfinance | `yfinance.Ticker(t).calendar` | `checkpoints` | Daily | None |
| 4 | SEC 10-K | SEC EDGAR | `GET efts.sec.gov/LATEST/search-index?q=...&forms=10-K` | `documents`, `claims` | Daily | None (User-Agent required) |
| 5 | SEC 10-Q | SEC EDGAR | `GET efts.sec.gov/LATEST/search-index?q=...&forms=10-Q` | `documents`, `claims` | Daily | None (User-Agent required) |
| 6 | SEC 8-K | SEC EDGAR | `GET efts.sec.gov/LATEST/search-index?q=...&forms=8-K` | `documents`, `claims` | Daily | None (User-Agent required) |
| 7 | News (Finnhub) | Finnhub | `GET finnhub.io/api/v1/company-news?symbol={ticker}` | `documents`, `claims` | Every 4h | `FINNHUB_API_KEY` |
| 8 | News (Google RSS) | Google News | `GET news.google.com/rss/search?q={ticker}` | `documents`, `claims` | Every 4h | None |
| 9 | Press releases | PR Newswire RSS | `GET prnewswire.com/rss/...` | `documents`, `claims` | Every 6h | None |

**Manual-only sources (no automated connector):**

| # | Source | Method | Destination Table(s) |
|---|--------|--------|----------------------|
| 10 | Earnings transcripts | User paste/upload | `documents`, `claims` |
| 11 | Paywalled news | User paste | `documents`, `claims` |
| 12 | Broker reports | User PDF upload | `documents`, `claims` |
| 13 | Investor presentations | User PDF upload | `documents`, `claims` |

---

## v2+ Sources (not in v1)

| Source | Provider | Blocker |
|--------|----------|---------|
| Broker reports (automated) | FactSet / Refinitiv | $10k+/yr license not procured |
| Earnings transcripts (automated) | FactSet / Refinitiv | $10k+/yr license not procured |
| Proxy statements (DEF 14A) | SEC EDGAR | Low priority; governance signals not in v1 |
| Real-time news | WebSocket providers | Infrastructure not built |
| XBRL structured data | SEC EDGAR | Parser not built |
| Bloomberg Terminal | Bloomberg API | $24k+/yr license |
