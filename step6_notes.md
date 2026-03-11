# Step 6: Live Source Connectors + Scheduled Ingestion

## What Was Added

### Architecture: Two-Lane Pipeline
The pipeline has two distinct lanes sharing one orchestration runner:

1. **Document sources** → `Document` table → claim extraction → thesis update
2. **Non-document sources** → `prices`, `checkpoints`, `companies` (correct storage, not forced through `Document`)

### New Files

| File | Purpose |
|------|---------|
| `connectors/base.py` | `DocumentPayload` model, `DocumentConnector` / `NonDocumentUpdater` ABCs |
| `connectors/sec_edgar.py` | SEC EDGAR 10-K, 10-Q, 8-K filing connector |
| `connectors/google_rss.py` | Google News RSS connector |
| `connectors/pr_rss.py` | PR Newswire / GlobeNewswire RSS connector |
| `connectors/newsapi_connector.py` | NewsAPI connector (soft-fail if key absent) |
| `connectors/yfinance_prices.py` | Daily OHLCV → `prices` table |
| `connectors/yfinance_calendar.py` | Earnings dates → `checkpoints` table |
| `connectors/yfinance_ticker_info.py` | Company metadata → `companies` table |
| `price_service.py` | Upsert helper for `prices` table |
| `checkpoint_service.py` | Upsert helper for `checkpoints` (earnings) |
| `company_enrichment_service.py` | Upsert helper for company metadata |
| `dedupe.py` | Centralized dedupe: (source_key, external_id) → URL → content hash |
| `pipeline_runner.py` | Main orchestration: per-ticker runs with summary |
| `scripts/run_pipeline.py` | CLI: `--ticker NVDA`, `--all-active`, `--dry-run` |
| `scripts/backfill_ticker.py` | CLI: `--ticker NVDA --days 30` |
| `tests/test_pipeline.py` | 25+ tests covering all Step 6 requirements |
| `step6_notes.md` | This file |

### Schema Changes (migration `a1b2c3d4e5f6`)
- **New table: `prices`** — `(ticker, date, open, high, low, close, adj_close, volume, source)` with unique constraint on `(ticker, date)`
- **New columns on `documents`**: `source_key` (String 100), `external_id` (String 255) with unique constraint on `(source_key, external_id)`

## How to Run

### Daily pipeline (one ticker)
```bash
python scripts/run_pipeline.py --ticker NVDA
```

### Dry run (fetch + dedupe, no persistence)
```bash
python scripts/run_pipeline.py --ticker NVDA --dry-run
```

### All active tickers
```bash
python scripts/run_pipeline.py --all-active
```

### Filter by source
```bash
python scripts/run_pipeline.py --ticker NVDA --sources sec_edgar google_rss
```

### Backfill
```bash
python scripts/backfill_ticker.py --ticker NVDA --days 30
python scripts/backfill_ticker.py --ticker NVDA --days 30 --documents-only
python scripts/backfill_ticker.py --ticker NVDA --days 365 --sources sec_edgar
```

### With LLM claim extraction
```bash
python scripts/run_pipeline.py --ticker NVDA --use-llm
```

## Environment Variables

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `OPENAI_API_KEY` | For LLM mode | — | Claim extraction with GPT |
| `OPENAI_MODEL` | No | `gpt-4o-mini` | Override LLM model |
| `SEC_USER_AGENT` | No | `Consensus-1 Research Platform admin@example.com` | SEC EDGAR required header |
| `NEWSAPI_KEY` | No | — | NewsAPI connector (skips if absent) |
| `FINNHUB_API_KEY` | No | — | Finnhub connector (future) |
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
1. **(source_key, external_id)** — strongest signal. SEC uses accession numbers. If both match, it's a duplicate.
2. **URL** — works for RSS/news sources where URL is the natural key.
3. **Content hash** (SHA-256 of raw_text) — fallback when URL is absent or unreliable.

### Non-document dedupe:
- **Prices**: `(ticker, date)` — upserts on match, inserts on miss
- **Checkpoints**: `(ticker, checkpoint_type, date_expected)` — upserts on match
- **Company enrichment**: upserts by ticker identity

### Pipeline-level batching:
- One thesis update per ticker-run (not per document)
- All new claims from all new documents are batched into a single thesis update call
- This reduces noise and oscillation from individual document updates

## What Still Remains Manual in v1

- **Earnings transcripts**: must be manually uploaded (no free API for full transcripts)
- **Broker reports**: manually uploaded PDFs
- **Investor presentations**: manually uploaded
- **Paywalled news** (FT, WSJ, Bloomberg): manually pasted
- **Finnhub integration**: registered in source_registry but connector not yet built (uses same pattern as Google RSS)
- **Seeking Alpha transcripts**: v2+ (requires auth)
- **XBRL financial parsing**: v2+
- **Real-time websockets**: v2+
- **Cron scheduling**: the scripts are cron-friendly but no crontab is configured. Recommended:
  ```
  # Daily at 6am ET
  0 6 * * * cd /path/to/Consensus-1 && python scripts/run_pipeline.py --all-active
  # Weekly backfill
  0 2 * * 0 cd /path/to/Consensus-1 && python scripts/backfill_ticker.py --ticker NVDA --days 30
  ```
