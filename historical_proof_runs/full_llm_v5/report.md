# Historical Proof Run: full_llm_v5
Generated: 2026-03-14 06:52 UTC

## Run Configuration
- **Mode**: usefulness_run
- **Backfill window**: 2025-06-01 to 2026-03-01
- **Eval window**: 2025-07-31 to 2026-03-01
- **Cadence**: 7 days
- **Initial cash**: $1,000,000
- **Universe**: 5 tickers
- **Extractor**: real_llm
- **Memory**: enabled
- **Benchmark**: SPY

## Regeneration Summary
- Documents processed: 98
- Claims created: 522
- Thesis updates: 94
- State changes: 12
- State flips: 4

### Data Coverage
- Tickers with price data: 5/5
- Total price rows: 890
- Total documents: 98
  - 10K: 5
  - 10Q: 25
  - 8K: 38
  - earnings_transcript: 30

## Key Metrics
| Metric | Value |
|--------|-------|
| Total return | -31.77% |
| Annualized return | -48.54% |
| Max drawdown | 32.49% |
| Reviews | 31 |
| Purity | degraded |

## Benchmark Comparison
| Benchmark | Return |
|-----------|--------|
| Portfolio | -31.77% |
| SPY | +9.15% |
| Excess vs SPY | -40.92% |
| Equal-weight | -0.24% |
| Excess vs EW | -31.53% |

## Forward Returns by Action Type
| Action | Count | Avg 5D | Avg 20D | Avg 60D |
|--------|-------|--------|---------|---------|
| add | 44 | -0.57% | -1.87% | +2.51% |
| hold | 90 | +0.99% | +1.92% | +2.30% |
| initiate | 6 | -1.18% | -0.91% | +2.06% |
| trim | 8 | +0.11% | +0.92% | +7.28% |

## Conviction Bucket Analysis
| Bucket | Actions | Avg Conviction | Avg 5D | Avg 20D | Avg 60D |
|--------|---------|----------------|--------|---------|---------|
| low | 8 | 37 | +0.11% | +0.92% | +7.28% |
| medium | 3 | 53 | -1.05% | +0.44% | +5.49% |
| high | 137 | 88 | +0.44% | +0.63% | +2.26% |

## Best Decisions (by 20D forward return)
| Date | Ticker | Action | Conviction | 5D | 20D | 60D |
|------|--------|--------|------------|-----|------|------|
| 2025-10-09 | AMD | add | 88.5 | -6.35% | +13.50% | -5.06% |
| 2026-02-05 | AMD | add | 97.4 | +10.95% | +9.54% | — |
| 2025-07-31 | AAPL | initiate | 57.9 | -2.24% | +9.01% | +22.71% |
| 2025-09-18 | NVDA | trim | 37.2 | +1.24% | +7.30% | +5.88% |
| 2025-09-11 | NVDA | trim | 37.2 | -1.29% | +5.68% | +12.35% |
| 2025-09-04 | AAPL | add | 81.5 | -2.26% | +5.23% | +12.21% |
| 2025-08-07 | AAPL | add | 81.5 | +4.49% | +4.87% | +16.79% |
| 2025-12-18 | AMD | add | 95.1 | +6.88% | +4.46% | +3.11% |
| 2025-10-09 | MSFT | add | 91.1 | -1.69% | +3.67% | -5.83% |
| 2025-09-04 | NVDA | trim | 37.2 | -0.52% | +3.10% | +20.52% |

## Worst Decisions (by 20D forward return)
| Date | Ticker | Action | Conviction | 5D | 20D | 60D |
|------|--------|--------|------------|-----|------|------|
| 2026-01-22 | AMD | add | 95.5 | -0.67% | -15.82% | — |
| 2026-01-29 | META | add | 93.5 | -6.31% | -12.88% | — |
| 2025-10-30 | AMD | add | 91.5 | -1.88% | -12.28% | -15.39% |
| 2025-10-30 | META | add | 90.9 | -5.87% | -11.43% | -1.09% |
| 2025-08-14 | AMD | add | 82.0 | -7.96% | -10.40% | +19.60% |
| 2025-11-06 | AMD | add | 95.2 | -0.08% | -9.87% | -6.99% |
| 2025-09-18 | META | add | 79.9 | -3.12% | -7.94% | -22.79% |
| 2026-01-29 | MSFT | add | 96.7 | -5.14% | -7.82% | — |
| 2025-10-30 | MSFT | add | 91.7 | -2.17% | -7.35% | -7.18% |
| 2025-07-31 | AMD | initiate | 50.0 | -1.13% | -6.30% | -8.48% |

## Per-Name Usefulness Summary
| Ticker | Actions | Docs | Claims | Avg 5D | Avg 20D | Avg 60D | Price Cov |
|--------|---------|------|--------|--------|---------|---------|-----------|
| AAPL | 31 | 20 | 99 | +0.74% | +2.37% | +5.65% | 96% |
| AMD | 31 | 23 | 120 | +1.14% | +3.83% | +14.27% | 96% |
| META | 31 | 19 | 109 | -0.26% | -1.81% | -4.67% | 96% |
| MSFT | 31 | 18 | 99 | +0.05% | -1.96% | -5.75% | 96% |
| NVDA | 24 | 18 | 95 | +0.26% | +0.82% | +4.68% | 96% |

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
| earnings_transcript | 30 |

### Source Gaps
- **ALL**: No documents ingested in 2025-06
- **ALL**: No documents ingested in 2026-03

## Decision Summary
- Total actions: 155
- Recommendation changes: 57
- Change rate: 1.839 per review
- Short-hold exits (<30d): 0

### Action Mix
| Action | Count | % |
|--------|-------|---|
| hold | 90 | 58.1% |
| add | 44 | 28.4% |
| trim | 8 | 5.2% |
| no_action | 7 | 4.5% |
| initiate | 6 | 3.9% |

## Failure Analysis

### Action Types with Negative Forward Returns
- add actions have negative avg 20D return (-1.87%)
- initiate actions have negative avg 20D return (-0.91%)

### Non-Differentiating Conviction Buckets
- Conviction buckets do not meaningfully differentiate outcomes (spread: 0.48%)

### Repeated Bad Recommendations
- MSFT had 3 initiate/add actions followed by >5% loss at 20D
- AMD had 6 initiate/add actions followed by >5% loss at 20D
- META had 4 initiate/add actions followed by >5% loss at 20D

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
- **AMD**: 10 actions with >5% loss at 20D
- **META**: 8 actions with >5% loss at 20D
- **MSFT**: 7 actions with >5% loss at 20D
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
