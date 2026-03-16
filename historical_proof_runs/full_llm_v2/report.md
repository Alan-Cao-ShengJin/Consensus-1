# Historical Proof Run: full_llm_v2
Generated: 2026-03-13 23:55 UTC

## Run Configuration
- **Mode**: usefulness_run
- **Backfill window**: 2025-06-01 to 2026-03-01
- **Eval window**: 2025-09-01 to 2026-03-01
- **Cadence**: 7 days
- **Initial cash**: $1,000,000
- **Universe**: 1 tickers
- **Extractor**: real_llm
- **Memory**: enabled
- **Benchmark**: SPY

## Regeneration Summary
- Documents processed: 12
- Claims created: 58
- Thesis updates: 11
- State changes: 2
- State flips: 0

### Data Coverage
- Tickers with price data: 1/1
- Total price rows: 178
- Total documents: 12
  - 10K: 1
  - 10Q: 5
  - 8K: 6

## Key Metrics
| Metric | Value |
|--------|-------|
| Total return | +0.41% |
| Annualized return | +0.86% |
| Max drawdown | 0.60% |
| Reviews | 26 |
| Purity | degraded |

## Benchmark Comparison
| Benchmark | Return |
|-----------|--------|
| Portfolio | +0.41% |
| SPY | +7.76% |
| Excess vs SPY | -7.34% |
| Equal-weight | +3.77% |
| Excess vs EW | -3.35% |

## Forward Returns by Action Type
| Action | Count | Avg 5D | Avg 20D | Avg 60D |
|--------|-------|--------|---------|---------|
| hold | 25 | -0.58% | -0.11% | -0.15% |
| initiate | 1 | -4.11% | +1.44% | +16.26% |

## Conviction Bucket Analysis
| Bucket | Actions | Avg Conviction | Avg 5D | Avg 20D | Avg 60D |
|--------|---------|----------------|--------|---------|---------|
| low | 0 | N/A | N/A | N/A | N/A |
| medium | 12 | 63 | -1.06% | -0.27% | +0.30% |
| high | 14 | 74 | -0.42% | +0.17% | +1.69% |

## Best Decisions (by 20D forward return)
| Date | Ticker | Action | Conviction | 5D | 20D | 60D |
|------|--------|--------|------------|-----|------|------|
| 2025-09-01 | NVDA | initiate | 62.6 | -4.11% | +1.44% | +16.26% |

## Worst Decisions (by 20D forward return)
| Date | Ticker | Action | Conviction | 5D | 20D | 60D |
|------|--------|--------|------------|-----|------|------|
| 2025-09-01 | NVDA | initiate | 62.6 | -4.11% | +1.44% | +16.26% |

## Per-Name Usefulness Summary
| Ticker | Actions | Docs | Claims | Avg 5D | Avg 20D | Avg 60D | Price Cov |
|--------|---------|------|--------|--------|---------|---------|-----------|
| NVDA | 26 | 12 | 58 | -0.72% | -0.05% | +0.77% | 96% |

## Source Coverage Diagnostics
- **Extractor mode**: real_llm
- **Benchmark available**: yes
- **Tickers with prices**: 1
- **Tickers without prices**: 0
- **Total price rows**: 178

### Documents by Source Type
| Source Type | Count |
|------------|-------|
| 10K | 1 |
| 10Q | 5 |
| 8K | 6 |

### Source Gaps
- **ALL**: No documents ingested in 2025-06
- **ALL**: No documents ingested in 2025-09
- **ALL**: No documents ingested in 2025-10
- **ALL**: No documents ingested in 2025-12
- **ALL**: No documents ingested in 2026-03

## Decision Summary
- Total actions: 26
- Recommendation changes: 1
- Change rate: 0.038 per review
- Short-hold exits (<30d): 0

### Action Mix
| Action | Count | % |
|--------|-------|---|
| hold | 25 | 96.2% |
| initiate | 1 | 3.8% |

## Failure Analysis

### Action Types with Negative Forward Returns
- hold actions have negative avg 20D return (-0.11%)

### Non-Differentiating Conviction Buckets
- Conviction buckets do not meaningfully differentiate outcomes (spread: 0.44%)

### Low Evidence Periods
- Only 1 document(s) in 2025-07
- Only 1 document(s) in 2026-01

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

## Enhanced Failure Analysis

### Repeatedly Negative Tickers
- **NVDA**: 3 actions with >5% loss at 20D

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
