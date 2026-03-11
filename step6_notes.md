# Step 6: Live Source Connectors + Scheduled Ingestion

## Architecture: Two-Lane Pipeline

The pipeline has two distinct lanes sharing one orchestration runner (`pipeline_runner.py`):

1. **Document sources** → `document_ingestion_service.py` → `Document` table → claim extraction → thesis update
2. **Non-document sources** → dedicated services → `prices`, `checkpoints`, `companies` tables (never create `Document` rows)

One thesis update per ticker-run, batching all new claims to reduce oscillation.

## Files

| File | Purpose |
|------|---------|
| `connectors/base.py` | `DocumentPayload` model, `DocumentConnector` / `NonDocumentUpdater` ABCs |
| `connectors/sec_edgar.py` | SEC EDGAR 10-K, 10-Q, 8-K filing connector |
| `connectors/google_rss.py` | Google News RSS connector |
| `connectors/pr_rss.py` | PR Newswire / GlobeNewswire RSS connector |
| `connectors/newsapi_connector.py` | NewsAPI connector (activates only when `NEWSAPI_KEY` is set) |
| `connectors/yfinance_prices.py` | Daily OHLCV → `prices` table |
| `connectors/yfinance_calendar.py` | Earnings dates → `checkpoints` table |
| `connectors/yfinance_ticker_info.py` | Company metadata → `companies` table |
| `document_ingestion_service.py` | Canonical ingestion: payload → document insert → claim extraction → linking → novelty |
| `pipeline_runner.py` | Orchestration: connector loop, dedupe, ingestion service calls, thesis update |
| `price_service.py` | Upsert helper for `prices` table |
| `checkpoint_service.py` | Upsert helper for `checkpoints` (earnings) |
| `company_enrichment_service.py` | Upsert helper for company metadata |
| `dedupe.py` | Centralized dedupe: (source_key, external_id) → URL → content hash |
| `scripts/run_pipeline.py` | CLI: `--ticker NVDA`, `--all-active`, `--dry-run` |
| `scripts/backfill_ticker.py` | CLI: `--ticker NVDA --days 30` |
| `tests/test_pipeline.py` | Tests covering connectors, dedupe, dry-run, end-to-end, batching |

### Automatic document sources (built)

| Source key | Connector | Notes |
|-----------|-----------|-------|
| `sec_edgar` | `SECEdgarConnector` | 10-K, 10-Q, 8-K via EDGAR API. External ID = accession number. |
| `news_google_rss` | `GoogleRSSConnector` | Google News RSS. Tier 3. No API key needed. |
| `press_release_rss` | `PRRSSConnector` | PR Newswire / GlobeNewswire RSS. Tier 1. |
| `newsapi` | `NewsAPIConnector` | Requires `NEWSAPI_KEY`. Skips silently if absent. |

### Automatic non-document sources (built)

| Source key | Updater | Target table |
|-----------|---------|-------------|
| `price_daily` | `YFinancePriceUpdater` | `prices` |
| `earnings_calendar` | `YFinanceCalendarUpdater` | `checkpoints` |
| `ticker_master` | `YFinanceTickerInfoUpdater` | `companies` |

### Registered but not built

| Source key | Status |
|-----------|--------|
| `news_finnhub` | Registered in `source_registry.py` with `enabled=False`. No connector yet. |

### Schema Changes (migration `a1b2c3d4e5f6`)
- **New table: `prices`** — `(ticker, date, open, high, low, close, adj_close, volume, source)` with unique constraint on `(ticker, date)`
- **New columns on `documents`**: `source_key` (String 100), `external_id` (String 255) with unique constraint on `(source_key, external_id)`

## How to Run

```bash
# Daily pipeline (one ticker)
python scripts/run_pipeline.py --ticker NVDA

# Dry run (fetch + dedupe, no persistence)
python scripts/run_pipeline.py --ticker NVDA --dry-run

# All active tickers
python scripts/run_pipeline.py --all-active

# Filter by source
python scripts/run_pipeline.py --ticker NVDA --sources sec_edgar news_google_rss

# Backfill
python scripts/backfill_ticker.py --ticker NVDA --days 30
python scripts/backfill_ticker.py --ticker NVDA --days 30 --documents-only
python scripts/backfill_ticker.py --ticker NVDA --days 365 --sources sec_edgar

# With LLM claim extraction
python scripts/run_pipeline.py --ticker NVDA --use-llm
```

## Environment Variables

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `OPENAI_API_KEY` | For `--use-llm` | — | Claim extraction with GPT |
| `OPENAI_MODEL` | No | `gpt-4o-mini` | Override LLM model |
| `SEC_USER_AGENT` | No | `Consensus-1 Research Platform admin@example.com` | SEC EDGAR required header |
| `NEWSAPI_KEY` | No | — | NewsAPI connector (skips if absent) |
| `DATABASE_URL` | No | `sqlite:///consensus.db` | Database connection |

## How Dry Run Works

When `--dry-run` is passed:
1. All connectors **fetch** data from external sources normally
2. Dedupe checks run against the DB to identify what's new
3. **No documents, claims, prices, or checkpoints are persisted**
4. Non-document updaters skip their write step
5. The summary reports what *would* have been inserted
6. No thesis updates are triggered

## How Dedupe Works

### Document dedupe (checked in order):
1. **(source_key, external_id)** — strongest signal. SEC uses accession numbers.
2. **URL** — works for RSS/news sources where URL is the natural key.
3. **Content hash** (SHA-256 of raw_text) — fallback when URL is absent or unreliable.

### Non-document dedupe:
- **Prices**: `(ticker, date)` — upserts on match, inserts on miss
- **Checkpoints**: `(ticker, checkpoint_type, date_expected)` — upserts on match
- **Company enrichment**: upserts by ticker identity

## What Remains Manual in v1

- **Earnings transcripts**: manually uploaded (no free API for full transcripts)
- **Broker reports**: manually uploaded PDFs
- **Investor presentations**: manually uploaded
- **Paywalled news** (FT, WSJ, Bloomberg): manually pasted
- These manual sources use `ingest.py` / `ingest_runner.py`, which is a separate ingestion path from the connector pipeline
