# Historical Proof Run: usefulness_run
Generated: 2026-03-15 10:59 UTC

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
- Documents processed: 104
- Claims created: 261
- Thesis updates: 95
- State changes: 28
- State flips: 10

### Data Coverage
- Tickers with price data: 15/15
- Total price rows: 2205
- Total documents: 104
  - 10K: 2
  - 10Q: 26
  - 8K: 76

## Key Metrics
| Metric | Value |
|--------|-------|
| Total return | +15.33% |
| Annualized return | +40.22% |
| Max drawdown | 6.14% |
| Reviews | 23 |
| Purity | degraded |

## Benchmark Comparison
| Benchmark | Return |
|-----------|--------|
| Portfolio | +15.33% |
| SPY | +7.09% |
| Excess vs SPY | +8.24% |
| Equal-weight | +27.11% |
| Excess vs EW | -11.78% |

## Forward Returns by Action Type
| Action | Count | Avg 5D | Avg 20D | Avg 60D |
|--------|-------|--------|---------|---------|
| add | 8 | +2.36% | -0.14% | +8.84% |
| exit | 1 | N/A | N/A | N/A |
| hold | 195 | +1.11% | +4.53% | +13.37% |
| initiate | 10 | +0.93% | +9.88% | +17.76% |

## Conviction Bucket Analysis
| Bucket | Actions | Avg Conviction | Avg 5D | Avg 20D | Avg 60D |
|--------|---------|----------------|--------|---------|---------|
| low | 0 | N/A | N/A | N/A | N/A |
| medium | 96 | 59 | +1.47% | +5.92% | +19.86% |
| high | 118 | 71 | +0.88% | +3.44% | +5.96% |

## Best Decisions (by 20D forward return)
| Date | Ticker | Action | Conviction | 5D | 20D | 60D |
|------|--------|--------|------------|-----|------|------|
| 2024-08-28 | PLTR | initiate | 56.9 | +3.69% | +20.06% | +47.76% |
| 2024-07-31 | LLY | initiate | 45.1 | -3.61% | +18.28% | +9.29% |
| 2024-08-07 | AMD | initiate | 61.9 | +6.30% | +16.97% | +32.82% |
| 2024-09-04 | TSLA | add | 64.6 | -1.43% | +15.89% | +13.48% |
| 2024-09-18 | AVGO | add | 68.0 | +7.32% | +12.16% | +2.30% |
| 2024-09-04 | META | initiate | 63.2 | -1.55% | +9.97% | +10.72% |
| 2024-08-07 | HD | initiate | 57.2 | +1.00% | +8.99% | +19.99% |
| 2024-07-31 | NVDA | initiate | 68.8 | -14.16% | +8.74% | +3.75% |
| 2024-08-07 | CAT | initiate | 58.5 | +3.14% | +7.77% | +21.88% |
| 2024-07-31 | COST | initiate | 58.6 | -2.45% | +6.59% | +7.74% |

## Worst Decisions (by 20D forward return)
| Date | Ticker | Action | Conviction | 5D | 20D | 60D |
|------|--------|--------|------------|-----|------|------|
| 2024-08-21 | NVDA | add | 68.8 | -1.59% | -15.88% | +7.40% |
| 2024-08-21 | AMD | add | 65.0 | -4.96% | -9.49% | -1.17% |
| 2024-08-14 | NVDA | add | 68.8 | +10.09% | -8.54% | +14.17% |
| 2024-08-14 | AVGO | initiate | 72.2 | +6.35% | -3.11% | +15.47% |
| 2024-08-14 | AMD | add | 61.9 | +10.32% | -2.71% | +19.28% |
| 2024-08-21 | TSLA | add | 64.6 | -4.51% | +1.30% | -1.15% |
| 2024-08-14 | TSLA | initiate | 64.6 | +10.60% | +4.58% | +8.15% |
| 2024-09-11 | AVGO | add | 68.0 | +3.63% | +6.16% | +16.41% |
| 2024-07-31 | COST | initiate | 58.6 | -2.45% | +6.59% | +7.74% |
| 2024-08-07 | CAT | initiate | 58.5 | +3.14% | +7.77% | +21.88% |

## Per-Name Usefulness Summary
| Ticker | Actions | Docs | Claims | Avg 5D | Avg 20D | Avg 60D | Price Cov |
|--------|---------|------|--------|--------|---------|---------|-----------|
| AMD | 22 | 8 | 28 | +0.94% | -1.36% | -5.21% | 97% |
| AVGO | 21 | 9 | 31 | +2.37% | +7.14% | +12.99% | 97% |
| CAT | 22 | 7 | 15 | +0.88% | +1.57% | +6.48% | 97% |
| COST | 23 | 9 | 18 | +0.34% | +2.04% | +5.31% | 97% |
| CRM | 0 | 8 | 23 | — | — | — | 97% |
| GS | 0 | 0 | 0 | — | — | — | 97% |
| HD | 22 | 9 | 29 | +0.80% | +2.34% | +6.82% | 97% |
| JPM | 0 | 0 | 0 | — | — | — | 97% |
| LLY | 23 | 10 | 15 | -0.25% | -0.32% | -6.76% | 97% |
| META | 18 | 6 | 18 | +0.33% | +3.48% | +4.86% | 97% |
| NVDA | 23 | 7 | 12 | +0.20% | +2.89% | +11.20% | 97% |
| PLTR | 19 | 6 | 16 | +3.38% | +17.70% | +68.20% | 97% |
| TSLA | 21 | 7 | 18 | +2.99% | +13.60% | +44.02% | 97% |
| UNH | 0 | 9 | 23 | — | — | — | 97% |
| XOM | 0 | 9 | 15 | — | — | — | 97% |

## Source Coverage Diagnostics
- **Extractor mode**: real_llm
- **Benchmark available**: yes
- **Tickers with prices**: 15
- **Tickers without prices**: 0
- **Total price rows**: 2205

### Documents by Source Type
| Source Type | Count |
|------------|-------|
| 10K | 2 |
| 10Q | 26 |
| 8K | 76 |

### Source Gaps
- **JPM**: No documents found for JPM in evaluation window
- **GS**: No documents found for GS in evaluation window
- **ALL**: No documents ingested in 2025-01

## Decision Summary
- Total actions: 299
- Recommendation changes: 26
- Change rate: 1.130 per review
- Short-hold exits (<30d): 0

### Action Mix
| Action | Count | % |
|--------|-------|---|
| hold | 195 | 65.2% |
| no_action | 85 | 28.4% |
| initiate | 10 | 3.3% |
| add | 8 | 2.7% |
| exit | 1 | 0.3% |

## Failure Analysis

### Sparse Coverage Tickers
| Ticker | Issues | Docs | Claims | Price Cov |
|--------|--------|------|--------|-----------|
| GS | no documents; no claims extracted | 0 | 0 | 97.3% |
| JPM | no documents; no claims extracted | 0 | 0 | 97.3% |

### Action Types with Negative Forward Returns
- add actions have negative avg 20D return (-0.14%)

### Repeated Bad Recommendations
- NVDA had 2 initiate/add actions followed by >5% loss at 20D

## Probation/Exit Diagnostics

### Summary
| Metric | Value |
|--------|-------|
| Total probations | 0 |
| Probation -> exit | 0 |
| Probation resolved (improvement) | 0 |
| Probation false alarms | 0 |
| Total exits | 1 |
| Premature exits (20D recovery >5%) | 0 |
| Premature exits (60D recovery >10%) | 0 |

### Exit Events
| Date | Ticker | Conviction | Prior Action | Probation? | 5D | 20D | 60D | Premature? |
|------|--------|------------|--------------|------------|-----|------|------|------------|
| 2025-01-01 | AMD | 70 | hold | no | - | - | - |  |

## Enhanced Failure Analysis

### Repeatedly Negative Tickers
- **AMD**: 9 actions with >5% loss at 20D
- **AVGO**: 3 actions with >5% loss at 20D
- **CAT**: 3 actions with >5% loss at 20D
- **HD**: 3 actions with >5% loss at 20D
- **LLY**: 4 actions with >5% loss at 20D
- **META**: 2 actions with >5% loss at 20D
- **NVDA**: 5 actions with >5% loss at 20D
- **TSLA**: 2 actions with >5% loss at 20D

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
