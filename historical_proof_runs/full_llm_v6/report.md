# Historical Proof Run: full_llm_v6
Generated: 2026-03-14 14:57 UTC

## Run Configuration
- **Mode**: usefulness_run
- **Backfill window**: 2024-06-01 to 2025-01-01
- **Eval window**: 2024-07-31 to 2025-01-01
- **Cadence**: 7 days
- **Initial cash**: $1,000,000
- **Universe**: 15 tickers
- **Extractor**: real_llm
- **Memory**: enabled
- **Benchmark**: SPY

## Regeneration Summary
- Documents processed: 0
- Claims created: 0
- Thesis updates: 0
- State changes: 0
- State flips: 0

## Key Metrics
| Metric | Value |
|--------|-------|
| Total return | +0.00% |
| Annualized return | +0.00% |
| Max drawdown | 0.00% |
| Reviews | 23 |
| Purity | strict |

## Benchmark Comparison
| Benchmark | Return |
|-----------|--------|
| Portfolio | +0.00% |

## Conviction Bucket Analysis
| Bucket | Actions | Avg Conviction | Avg 5D | Avg 20D | Avg 60D |
|--------|---------|----------------|--------|---------|---------|
| low | 0 | N/A | N/A | N/A | N/A |
| medium | 0 | N/A | N/A | N/A | N/A |
| high | 0 | N/A | N/A | N/A | N/A |

## Per-Name Usefulness Summary
| Ticker | Actions | Docs | Claims | Avg 5D | Avg 20D | Avg 60D | Price Cov |
|--------|---------|------|--------|--------|---------|---------|-----------|
| AAPL | 0 | 0 | 0 | — | — | — | 0% |
| AMD | 0 | 0 | 0 | — | — | — | 0% |
| AMZN | 0 | 0 | 0 | — | — | — | 0% |
| AVGO | 0 | 0 | 0 | — | — | — | 0% |
| CRM | 0 | 0 | 0 | — | — | — | 0% |
| CRWD | 0 | 0 | 0 | — | — | — | 0% |
| GOOGL | 0 | 0 | 0 | — | — | — | 0% |
| INTC | 0 | 0 | 0 | — | — | — | 0% |
| META | 0 | 0 | 0 | — | — | — | 0% |
| MSFT | 0 | 0 | 0 | — | — | — | 0% |
| NOW | 0 | 0 | 0 | — | — | — | 0% |
| NVDA | 0 | 0 | 0 | — | — | — | 0% |
| PLTR | 0 | 0 | 0 | — | — | — | 0% |
| QCOM | 0 | 0 | 0 | — | — | — | 0% |
| TSLA | 0 | 0 | 0 | — | — | — | 0% |

## Source Coverage Diagnostics
- **Extractor mode**: real_llm
- **Benchmark available**: no
- **Tickers with prices**: 0
- **Tickers without prices**: 15
- **Total price rows**: 0

### Source Gaps
- **NVDA**: No documents found for NVDA in evaluation window
- **AMD**: No documents found for AMD in evaluation window
- **AVGO**: No documents found for AVGO in evaluation window
- **QCOM**: No documents found for QCOM in evaluation window
- **INTC**: No documents found for INTC in evaluation window
- **MSFT**: No documents found for MSFT in evaluation window
- **GOOGL**: No documents found for GOOGL in evaluation window
- **AMZN**: No documents found for AMZN in evaluation window
- **META**: No documents found for META in evaluation window
- **CRM**: No documents found for CRM in evaluation window
- **PLTR**: No documents found for PLTR in evaluation window
- **NOW**: No documents found for NOW in evaluation window
- **CRWD**: No documents found for CRWD in evaluation window
- **AAPL**: No documents found for AAPL in evaluation window
- **TSLA**: No documents found for TSLA in evaluation window

## Decision Summary
- Total actions: 0
- Recommendation changes: 0
- Change rate: 0.000 per review
- Short-hold exits (<30d): 0

## Failure Analysis

### Sparse Coverage Tickers
| Ticker | Issues | Docs | Claims | Price Cov |
|--------|--------|------|--------|-----------|
| AAPL | no documents; no claims extracted; price coverage 0% | 0 | 0 | 0.0% |
| AMD | no documents; no claims extracted; price coverage 0% | 0 | 0 | 0.0% |
| AMZN | no documents; no claims extracted; price coverage 0% | 0 | 0 | 0.0% |
| AVGO | no documents; no claims extracted; price coverage 0% | 0 | 0 | 0.0% |
| CRM | no documents; no claims extracted; price coverage 0% | 0 | 0 | 0.0% |
| CRWD | no documents; no claims extracted; price coverage 0% | 0 | 0 | 0.0% |
| GOOGL | no documents; no claims extracted; price coverage 0% | 0 | 0 | 0.0% |
| INTC | no documents; no claims extracted; price coverage 0% | 0 | 0 | 0.0% |
| META | no documents; no claims extracted; price coverage 0% | 0 | 0 | 0.0% |
| MSFT | no documents; no claims extracted; price coverage 0% | 0 | 0 | 0.0% |
| NOW | no documents; no claims extracted; price coverage 0% | 0 | 0 | 0.0% |
| NVDA | no documents; no claims extracted; price coverage 0% | 0 | 0 | 0.0% |
| PLTR | no documents; no claims extracted; price coverage 0% | 0 | 0 | 0.0% |
| QCOM | no documents; no claims extracted; price coverage 0% | 0 | 0 | 0.0% |
| TSLA | no documents; no claims extracted; price coverage 0% | 0 | 0 | 0.0% |

## Probation/Exit Diagnostics

### Summary
| Metric | Value |
|--------|-------|
| Total probations | 0 |
| Probation -> exit | 0 |
| Probation resolved (improvement) | 0 |
| Probation false alarms | 0 |
| Total exits | 0 |
| Premature exits (20D recovery >5%) | 0 |
| Premature exits (60D recovery >10%) | 0 |

## Warnings
- No documents found in source DB for tickers ['NVDA', 'AMD', 'AVGO', 'QCOM', 'INTC']... between 2024-06-01 and 2025-01-01
- No action outcomes generated — check data availability

## Limitations
- Returns are not statistically significant over short replay windows
- No earnings transcript backfill (manual source only)
- News coverage degrades rapidly for periods >90 days ago
- Equal-weight baseline assumes no transaction costs
- Forward returns assume execution at close price on decision date
- No sector-level attribution (sector data not versioned historically)

## Artifact Index
| File | Description |
|------|-------------|
| manifest.json | Run manifest with metadata and degraded flags |
| summary.json | Machine-readable full report |
| report.md | This report |
| decisions.csv | Per-review-date decisions |
| action_outcomes.csv | Per-action forward returns |
| best_decisions.csv | Top decisions by forward return |
| worst_decisions.csv | Bottom decisions by forward return |
| per_name_summary.csv | Per-ticker usefulness summary |
| coverage_diagnostics.csv | Source coverage by ticker |
| coverage_by_month.csv | Source coverage by month |
| benchmark.csv | Benchmark comparison |
| conviction_buckets.csv | Conviction bucket summary |
| probation_events.csv | Probation event diagnostics |
| exit_events.csv | Exit event diagnostics |
