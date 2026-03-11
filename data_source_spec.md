# Data Source Specification — Consensus-1 v1

## Overview

This document defines every data source the system pulls for our monitored universe
of ~50 names. For each source: what it is, how we get it, how often, how it maps
into the schema, and what level of automation applies in v1.

**Automation levels:**
- **automatic** — runs on a cron/scheduler, no human in the loop
- **semi-automatic** — triggered by a scheduler but requires human review/approval before ingestion
- **manual** — user uploads or pastes content; system parses and ingests

---

## 1. Source Matrix

### 1a. Market Data & Reference (non-document sources)

| # | source_type       | Provider         | Pull Method              | Frequency        | Backfill Depth | Source Tier | Dest Table(s)                  | Dedupe Key                         | Automation   | Feeds Claims? | Creates Checkpoints? | Notes |
|---|-------------------|------------------|--------------------------|------------------|----------------|-------------|--------------------------------|------------------------------------|--------------|---------------|----------------------|-------|
| 1 | price_data        | yfinance (Yahoo) | Python `yfinance` lib    | Daily 6pm ET     | 2 years        | —           | `prices` (new, Step 6+)        | (ticker, date)                     | automatic    | No            | No                   | OHLCV + adj close. Free, no API key. Rate-limit to 2 req/s. Used for zone/valuation, not claim extraction. |
| 2 | ticker_master     | yfinance / SEC EDGAR company search | `yfinance.Ticker.info` + manual CSV | Weekly / on-add  | One-time       | —           | `companies`                    | ticker (PK)                        | semi-automatic | No          | No                   | Sector, industry, market_cap_bucket, exchange. Enriched on first add, refreshed weekly. |
| 3 | earnings_calendar | yfinance / Nasdaq earnings calendar | `yfinance.Ticker.calendar` | Daily scan       | 90 days forward | —           | `checkpoints`                  | (ticker, checkpoint_type, date_expected) | automatic | No            | Yes                  | Creates checkpoint rows for upcoming earnings. `checkpoint_type = "earnings_release"`. |

### 1b. SEC Filings (Tier 1 — primary source)

| # | source_type       | Provider   | Pull Method                          | Frequency          | Backfill Depth | Source Tier | Dest Table(s)             | Dedupe Key        | Automation     | Feeds Claims? | Creates Checkpoints? | Notes |
|---|-------------------|------------|--------------------------------------|--------------------|----------------|-------------|---------------------------|--------------------|----------------|---------------|----------------------|-------|
| 4 | 10K               | SEC EDGAR  | EDGAR full-text search API (`efts`)  | On filing (daily)  | 3 years        | tier_1      | `documents`, `claims`     | EDGAR accession #  | automatic      | Yes           | No                   | Annual report. Parse XBRL for financials, full text for qualitative claims. Large docs — extract Management Discussion & Analysis (MD&A) section. |
| 5 | 10Q               | SEC EDGAR  | EDGAR full-text search API           | On filing (daily)  | 1 year         | tier_1      | `documents`, `claims`     | EDGAR accession #  | automatic      | Yes           | No                   | Quarterly report. Same approach as 10-K but shorter. |
| 6 | 8K                | SEC EDGAR  | EDGAR full-text search API           | On filing (daily)  | 1 year         | tier_1      | `documents`, `claims`     | EDGAR accession #  | automatic      | Yes           | Yes                  | Material events. Creates checkpoints for: management changes, M&A, guidance revisions. |
| 7 | proxy_def14a      | SEC EDGAR  | EDGAR full-text search API           | On filing (annual) | 1 year         | tier_1      | `documents`               | EDGAR accession #  | semi-automatic | No (v1)       | No                   | Proxy statements. Low priority for claim extraction in v1; useful for governance signals later. |

### 1c. Earnings Transcripts (Tier 1)

| # | source_type           | Provider              | Pull Method                         | Frequency       | Backfill Depth | Source Tier | Dest Table(s)             | Dedupe Key                  | Automation     | Feeds Claims? | Creates Checkpoints? | Notes |
|---|-----------------------|-----------------------|-------------------------------------|-----------------|----------------|-------------|---------------------------|-----------------------------|----------------|---------------|----------------------|-------|
| 8 | earnings_transcript   | Seeking Alpha (free)  | Web scrape + `requests`/`httpx`     | Post-earnings   | 4 quarters     | tier_1      | `documents`, `claims`     | (ticker, fiscal_quarter, year) | semi-automatic | Yes           | No                   | Highest-value text source. Q&A section especially rich for claims. May require rotating user-agents. Legal gray zone — plan migration to paid API (FactSet/Refinitiv) if scaling. |
| 9 | earnings_transcript   | Company IR page       | Manual download / paste             | Post-earnings   | 4 quarters     | tier_1      | `documents`, `claims`     | (ticker, fiscal_quarter, year) | manual         | Yes           | No                   | Fallback when scraping blocked. Many companies post transcripts on their IR page as PDF. |

### 1d. Press Releases & IR Pages (Tier 1-2)

| # | source_type       | Provider              | Pull Method                          | Frequency        | Backfill Depth | Source Tier | Dest Table(s)             | Dedupe Key          | Automation     | Feeds Claims? | Creates Checkpoints? | Notes |
|---|-------------------|-----------------------|--------------------------------------|------------------|----------------|-------------|---------------------------|----------------------|----------------|---------------|----------------------|-------|
| 10 | press_release    | Company IR / PR Newswire / GlobeNewswire | RSS feed polling + `feedparser` | Every 6 hours   | 90 days        | tier_1      | `documents`, `claims`     | URL                  | automatic      | Yes           | Sometimes            | Earnings releases, guidance updates, M&A announcements. tier_1 because it's the company's own words. Creates checkpoints for guidance revisions. |
| 11 | investor_presentation | Company IR page  | Manual download (PDF)                | Quarterly       | 2 quarters     | tier_2      | `documents`, `claims`     | URL or (ticker, title, date) | manual    | Yes           | No                   | Slide decks. Require PDF-to-text extraction (PyMuPDF/pdfplumber). Rich in forward-looking claims but noisy. |

### 1e. News (Tier 2-3)

| # | source_type | Provider                   | Pull Method                          | Frequency      | Backfill Depth | Source Tier | Dest Table(s)             | Dedupe Key | Automation     | Feeds Claims? | Creates Checkpoints? | Notes |
|---|-------------|----------------------------|--------------------------------------|----------------|----------------|-------------|---------------------------|------------|----------------|---------------|----------------------|-------|
| 12 | news       | NewsAPI.org                | REST API (`/everything` endpoint)    | Every 4 hours  | 30 days        | tier_2      | `documents`, `claims`     | URL        | automatic      | Yes           | No                   | Free tier: 100 req/day, 1-month archive. Covers Reuters, Bloomberg excerpts, CNBC, etc. Good for sentiment + event detection. Upgrade to paid ($449/mo) if needed. |
| 13 | news       | Google News RSS            | RSS via `feedparser`                 | Every 4 hours  | 7 days         | tier_3      | `documents`, `claims`     | URL        | automatic      | Yes           | No                   | Free, no API key. Lower quality, more noise. Good supplementary source. tier_3 because it aggregates without editorial filter. |
| 14 | news       | Financial Times / WSJ      | Manual paste                         | As encountered | N/A            | tier_2      | `documents`, `claims`     | URL        | manual         | Yes           | No                   | Paywalled. User pastes article text. High-quality analysis but can't automate without subscription API. |

### 1f. Broker Reports (Tier 1 — future)

| # | source_type    | Provider              | Pull Method            | Frequency        | Backfill Depth | Source Tier | Dest Table(s)             | Dedupe Key              | Automation     | Feeds Claims? | Creates Checkpoints? | Notes |
|---|----------------|-----------------------|------------------------|------------------|----------------|-------------|---------------------------|--------------------------|----------------|---------------|----------------------|-------|
| 15 | broker_report | FactSet / Refinitiv   | API (licensed)         | On publish       | 1 year         | tier_1      | `documents`, `claims`     | (provider_id, report_id) | automatic      | Yes           | No                   | **v2+ only.** Requires expensive data license ($10k+/yr). Highest quality — analyst models, price targets, estimate revisions. Placeholder for when/if licensed. |
| 16 | broker_report | Manual upload (PDF)   | User uploads PDF       | As encountered   | N/A            | tier_1      | `documents`, `claims`     | URL or hash              | manual         | Yes           | No                   | v1 workaround: user uploads broker PDFs. System extracts text and runs claim extraction. |

---

## 2. Field Mapping: Minimum Required Fields per Source

Every source must provide enough data to create a `Document` row. Below are the
minimum required fields and how each source populates them.

| Field                    | Required? | SEC Filings         | Earnings Transcript    | Press Release         | News                  | Broker Report        | Price/Calendar       |
|--------------------------|-----------|---------------------|------------------------|-----------------------|-----------------------|----------------------|----------------------|
| `source_type`            | Yes       | 10K/10Q/8K          | earnings_transcript    | press_release         | news                  | broker_report        | N/A (no Document)    |
| `source_tier`            | Yes       | tier_1              | tier_1                 | tier_1                | tier_2 or tier_3      | tier_1               | N/A                  |
| `title`                  | Yes       | Filing type + ticker | "Q{n} FY{yr} Earnings" | PR headline           | Article headline      | Report title         | N/A                  |
| `url`                    | Recommended | EDGAR filing URL  | Source URL or null     | PR URL                | Article URL           | null (manual)        | N/A                  |
| `published_at`           | Recommended | Filing date       | Call date              | PR date               | Article date          | Report date          | N/A                  |
| `publisher`              | Optional  | "SEC EDGAR"         | "Seeking Alpha" / IR   | PR Newswire / company | Publisher name        | Broker name          | N/A                  |
| `primary_company_ticker` | Yes       | From CIK lookup     | From search/filename   | From RSS tag          | From query ticker     | From filename        | N/A                  |
| `raw_text`               | Yes       | Full filing or MD&A  | Full transcript        | Full PR text          | Article body          | Report text          | N/A                  |
| `hash`                   | Recommended | SHA-256 of text   | SHA-256 of text        | SHA-256 of text       | SHA-256 of text       | SHA-256 of text      | N/A                  |

**Dedupe strategy:** Before ingestion, check `documents.url` (if present) OR `documents.hash`.
If either matches an existing row, skip ingestion and log as duplicate.

---

## 3. Processing Pipeline per Source

| Source Type           | Feeds Claim Extraction? | Creates Checkpoints?                     | Backfill vs Live         |
|-----------------------|-------------------------|------------------------------------------|--------------------------|
| price_data            | No                      | No                                       | Both (2yr backfill, daily live) |
| ticker_master         | No                      | No                                       | One-time + weekly refresh |
| earnings_calendar     | No                      | Yes — `earnings_release` checkpoint      | 90-day forward scan      |
| 10K                   | Yes                     | No                                       | Both (3yr backfill, daily live) |
| 10Q                   | Yes                     | No                                       | Both (1yr backfill, daily live) |
| 8K                    | Yes                     | Yes — management change, M&A, guidance   | Both (1yr backfill, daily live) |
| proxy_def14a          | No (v1)                 | No                                       | Backfill only (annual)   |
| earnings_transcript   | Yes                     | No                                       | Both (4Q backfill, post-earnings live) |
| press_release         | Yes                     | Sometimes (guidance revisions)           | Both (90d backfill, 6hr live) |
| investor_presentation | Yes                     | No                                       | Manual only              |
| news (NewsAPI)        | Yes                     | No                                       | Both (30d backfill, 4hr live) |
| news (Google RSS)     | Yes                     | No                                       | Live only (7d window)    |
| news (manual)         | Yes                     | No                                       | Manual only              |
| broker_report         | Yes                     | No                                       | Manual only (v1)         |

---

## 4. Checkpoint Creation Rules

Checkpoints are forward-looking events that the system tracks. They are created from:

| Checkpoint Type       | Created By              | Fields Populated                          |
|-----------------------|-------------------------|-------------------------------------------|
| `earnings_release`    | earnings_calendar scan  | ticker, date_expected, importance=0.9      |
| `management_change`   | 8-K filing detection    | ticker, name from filing, importance=0.7   |
| `guidance_revision`   | 8-K or press_release    | ticker, date_expected=filing date, importance=0.85 |
| `regulatory_event`    | News or 8-K             | ticker, description, importance varies     |
| `product_launch`      | Press release or news   | ticker, date_expected, importance=0.6      |

---

## 5. Pull Frequency Summary

| Frequency    | Sources                                              |
|--------------|------------------------------------------------------|
| Real-time    | None (v1 — no websockets/streaming)                  |
| Daily        | SEC filings (EDGAR), earnings calendar, price data   |
| Every 4-6hr  | News (NewsAPI, Google RSS), press releases (RSS)     |
| Weekly       | Ticker master refresh                                |
| Post-event   | Earnings transcripts (after earnings call)           |
| On-demand    | Manual uploads (broker reports, FT/WSJ, presentations) |

---

## 6. v1 Scope vs v2+ Roadmap

### v1 (current sprint — implement now)
- SEC EDGAR connector (10-K, 10-Q, 8-K) — automatic
- NewsAPI connector — automatic
- Google News RSS — automatic
- Press release RSS poller — automatic
- Earnings calendar scanner (yfinance) — automatic
- Price data puller (yfinance) — automatic
- Manual upload endpoint for transcripts, broker reports, presentations
- Ticker master bootstrap from CSV + yfinance enrichment

### v2+ (future)
- Seeking Alpha transcript scraper (semi-automatic)
- FactSet/Refinitiv broker report API
- Bloomberg Terminal integration
- Real-time news via websockets
- PDF extraction pipeline for investor presentations
- XBRL structured data parsing from SEC filings

---

## 7. Rate Limits & API Keys

| Provider       | Rate Limit             | API Key Required? | Free Tier Limits              |
|----------------|------------------------|-------------------|-------------------------------|
| SEC EDGAR      | 10 req/s (with UA)     | No (User-Agent required) | Unlimited                |
| yfinance       | ~2 req/s (unofficial)  | No                | Unlimited (unofficial)        |
| NewsAPI        | 100 req/day (free)     | Yes               | 1-month archive, 100 req/day |
| Google News RSS| ~1 req/s               | No                | Unlimited                     |
| PR Newswire RSS| No known limit         | No                | Unlimited                     |

**SEC EDGAR requirement:** Must set `User-Agent` header to `"Consensus-1 admin@example.com"` per SEC fair access policy.

---

## 8. Dedupe & Idempotency

All connectors must be idempotent. Running the same pull twice must not create duplicate documents.

| Strategy           | Applied To                          | Implementation                        |
|--------------------|-------------------------------------|---------------------------------------|
| URL uniqueness     | News, press releases, SEC filings   | `documents.url` UNIQUE constraint     |
| Content hash       | All text documents                  | SHA-256 of `raw_text`, stored in `documents.hash` |
| Accession number   | SEC filings                         | Stored in `documents.url` as EDGAR URL |
| Calendar dedupe    | Earnings calendar checkpoints       | (ticker, checkpoint_type, date_expected) composite check |
| Price date dedupe  | Daily prices                        | (ticker, date) composite unique       |
