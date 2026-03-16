# Historical Proof Run: full_llm_v3
Generated: 2026-03-14 03:17 UTC

## Run Configuration
- **Mode**: usefulness_run
- **Backfill window**: 2025-06-01 to 2026-03-01
- **Eval window**: 2025-09-01 to 2026-03-01
- **Cadence**: 7 days
- **Initial cash**: $1,000,000
- **Universe**: 5 tickers
- **Extractor**: real_llm
- **Memory**: enabled
- **Benchmark**: SPY

## Regeneration Summary
- Documents processed: 68
- Claims created: 316
- Thesis updates: 64
- State changes: 12
- State flips: 1

### Data Coverage
- Tickers with price data: 5/5
- Total price rows: 890
- Total documents: 68
  - 10K: 5
  - 10Q: 25
  - 8K: 38

## Key Metrics
| Metric | Value |
|--------|-------|
| Total return | +0.42% |
| Annualized return | +0.88% |
| Max drawdown | 2.78% |
| Reviews | 26 |
| Purity | degraded |

## Benchmark Comparison
| Benchmark | Return |
|-----------|--------|
| Portfolio | +0.42% |
| SPY | +7.76% |
| Excess vs SPY | -7.33% |
| Equal-weight | +1.74% |
| Excess vs EW | -1.32% |

## Forward Returns by Action Type
| Action | Count | Avg 5D | Avg 20D | Avg 60D |
|--------|-------|--------|---------|---------|
| hold | 125 | -0.60% | -0.48% | -1.00% |
| initiate | 5 | -1.67% | +2.31% | +16.05% |

## Conviction Bucket Analysis
| Bucket | Actions | Avg Conviction | Avg 5D | Avg 20D | Avg 60D |
|--------|---------|----------------|--------|---------|---------|
| low | 0 | N/A | N/A | N/A | N/A |
| medium | 30 | 55 | -0.84% | -0.83% | -1.03% |
| high | 100 | 80 | -0.59% | -0.21% | +0.43% |

## Best Decisions (by 20D forward return)
| Date | Ticker | Action | Conviction | 5D | 20D | 60D |
|------|--------|--------|------------|-----|------|------|
| 2025-09-01 | AAPL | initiate | 59.9 | +3.25% | +5.76% | +16.47% |
| 2025-09-01 | META | initiate | 50.0 | +1.86% | +5.37% | -12.17% |
| 2025-09-01 | MSFT | initiate | 66.2 | -2.31% | +2.22% | +2.19% |
| 2025-09-01 | NVDA | initiate | 55.3 | -4.11% | +1.44% | +16.26% |
| 2025-09-01 | AMD | initiate | 65.3 | -7.07% | -3.22% | +57.49% |

## Worst Decisions (by 20D forward return)
| Date | Ticker | Action | Conviction | 5D | 20D | 60D |
|------|--------|--------|------------|-----|------|------|
| 2025-09-01 | AMD | initiate | 65.3 | -7.07% | -3.22% | +57.49% |
| 2025-09-01 | NVDA | initiate | 55.3 | -4.11% | +1.44% | +16.26% |
| 2025-09-01 | MSFT | initiate | 66.2 | -2.31% | +2.22% | +2.19% |
| 2025-09-01 | META | initiate | 50.0 | +1.86% | +5.37% | -12.17% |
| 2025-09-01 | AAPL | initiate | 59.9 | +3.25% | +5.76% | +16.47% |

## Per-Name Usefulness Summary
| Ticker | Actions | Docs | Claims | Avg 5D | Avg 20D | Avg 60D | Price Cov |
|--------|---------|------|--------|--------|---------|---------|-----------|
| AAPL | 26 | 14 | 66 | -0.03% | +0.87% | +2.77% | 96% |
| AMD | 26 | 17 | 80 | -0.74% | +2.33% | +9.86% | 96% |
| META | 26 | 13 | 59 | -0.60% | -1.83% | -5.48% | 96% |
| MSFT | 26 | 12 | 59 | -1.15% | -3.16% | -8.18% | 96% |
| NVDA | 26 | 12 | 52 | -0.72% | -0.05% | +0.77% | 96% |

## Source Coverage Diagnostics
- **Extractor mode**: real_llm
- **Benchmark available**: yes
- **Tickers with prices**: 5
- **Tickers without prices**: 0
- **Total price rows**: 890

### Documents by Source Type
| Source Type | Count |
|------------|-------|
| 10K | 5 |
| 10Q | 25 |
| 8K | 38 |

### Source Gaps
- **ALL**: No documents ingested in 2025-06
- **ALL**: No documents ingested in 2026-03

## Decision Summary
- Total actions: 130
- Recommendation changes: 5
- Change rate: 0.192 per review
- Short-hold exits (<30d): 0

### Action Mix
| Action | Count | % |
|--------|-------|---|
| hold | 125 | 96.2% |
| initiate | 5 | 3.8% |

## Failure Analysis

### Action Types with Negative Forward Returns
- hold actions have negative avg 20D return (-0.48%)
- initiate actions have negative avg 5D return (-1.67%)

### Non-Differentiating Conviction Buckets
- Conviction buckets do not meaningfully differentiate outcomes (spread: 0.62%)

### Low Evidence Periods
- Only 1 document(s) in 2025-09

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
- **AAPL**: 2 actions with >5% loss at 20D
- **AMD**: 8 actions with >5% loss at 20D
- **META**: 8 actions with >5% loss at 20D
- **MSFT**: 6 actions with >5% loss at 20D
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
