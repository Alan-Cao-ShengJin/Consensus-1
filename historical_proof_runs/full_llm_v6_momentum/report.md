# Historical Proof Run: full_llm_v6_momentum
Generated: 2026-03-14 18:27 UTC

## Run Configuration
- **Mode**: evaluate_only
- **Backfill window**: 2025-06-01 to 2026-03-01
- **Eval window**: 2025-07-31 to 2026-03-01
- **Cadence**: 7 days
- **Initial cash**: $1,000,000
- **Universe**: 5 tickers
- **Extractor**: real_llm
- **Memory**: enabled
- **Benchmark**: SPY

## Key Metrics
| Metric | Value |
|--------|-------|
| Total return | -9.35% |
| Annualized return | -15.69% |
| Max drawdown | 11.33% |
| Reviews | 31 |
| Purity | degraded |

## Benchmark Comparison
| Benchmark | Return |
|-----------|--------|
| Portfolio | -9.35% |
| SPY | +9.15% |
| Excess vs SPY | -18.50% |
| Equal-weight | -0.24% |
| Excess vs EW | -9.11% |

## Forward Returns by Action Type
| Action | Count | Avg 5D | Avg 20D | Avg 60D |
|--------|-------|--------|---------|---------|
| add | 36 | -1.16% | -2.30% | -0.62% |
| exit | 5 | +3.50% | +8.73% | +7.82% |
| hold | 71 | +0.99% | +2.01% | +3.63% |
| initiate | 11 | +0.01% | -2.56% | +2.68% |
| trim | 23 | +0.34% | +0.81% | +4.69% |

## Conviction Bucket Analysis
| Bucket | Actions | Avg Conviction | Avg 5D | Avg 20D | Avg 60D |
|--------|---------|----------------|--------|---------|---------|
| low | 8 | 37 | +0.11% | +0.92% | +7.28% |
| medium | 3 | 53 | -1.05% | +0.44% | +5.49% |
| high | 135 | 88 | +0.42% | +0.62% | +2.25% |

## Best Decisions (by 20D forward return)
| Date | Ticker | Action | Conviction | 5D | 20D | 60D |
|------|--------|--------|------------|-----|------|------|
| 2026-01-08 | AMD | exit | 95.1 | +7.96% | +23.48% | — |
| 2025-10-09 | AMD | add | 88.5 | -6.35% | +13.50% | -5.06% |
| 2026-01-22 | AAPL | exit | 95.3 | +3.99% | +11.04% | — |
| 2025-11-20 | META | trim | 92.6 | +7.99% | +10.35% | +5.36% |
| 2025-10-23 | AMD | add | 88.5 | +9.80% | +10.17% | -8.53% |
| 2026-02-05 | AMD | trim | 97.4 | +10.95% | +9.54% | — |
| 2025-10-16 | AMD | add | 88.5 | +1.48% | +9.28% | -11.50% |
| 2025-07-31 | AAPL | initiate | 57.9 | -2.24% | +9.01% | +22.71% |
| 2025-11-20 | AMD | exit | 95.2 | +0.05% | +7.48% | +12.53% |
| 2025-09-18 | NVDA | trim | 37.2 | +1.24% | +7.30% | +5.88% |

## Worst Decisions (by 20D forward return)
| Date | Ticker | Action | Conviction | 5D | 20D | 60D |
|------|--------|--------|------------|-----|------|------|
| 2026-01-29 | AMD | add | 95.5 | -3.99% | -20.64% | — |
| 2026-01-22 | AMD | add | 95.5 | -0.67% | -15.82% | — |
| 2026-01-29 | META | add | 93.5 | -6.31% | -12.88% | — |
| 2025-10-30 | AMD | add | 91.5 | -1.88% | -12.28% | -15.39% |
| 2025-11-13 | AMD | add | 95.2 | -7.13% | -12.24% | -16.24% |
| 2026-01-15 | AMD | initiate | 95.1 | +1.76% | -12.17% | — |
| 2025-08-14 | AMD | add | 82.0 | -7.96% | -10.40% | +19.60% |
| 2026-01-01 | AAPL | trim | 94.9 | -3.49% | -8.91% | -2.73% |
| 2025-09-18 | META | add | 79.9 | -3.12% | -7.94% | -22.79% |
| 2026-01-29 | MSFT | trim | 96.7 | -5.14% | -7.82% | — |

## Per-Name Usefulness Summary
| Ticker | Actions | Docs | Claims | Avg 5D | Avg 20D | Avg 60D | Price Cov |
|--------|---------|------|--------|--------|---------|---------|-----------|
| AAPL | 31 | 20 | 99 | +0.74% | +2.37% | +5.65% | 96% |
| AMD | 30 | 23 | 120 | +1.00% | +3.83% | +14.27% | 96% |
| META | 31 | 19 | 109 | -0.26% | -1.81% | -4.67% | 96% |
| MSFT | 31 | 18 | 99 | +0.05% | -1.96% | -5.75% | 96% |
| NVDA | 23 | 18 | 95 | +0.34% | +0.78% | +4.78% | 96% |

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
- Recommendation changes: 56
- Change rate: 1.806 per review
- Short-hold exits (<30d): 3

### Action Mix
| Action | Count | % |
|--------|-------|---|
| hold | 71 | 45.8% |
| add | 36 | 23.2% |
| trim | 23 | 14.8% |
| initiate | 11 | 7.1% |
| no_action | 9 | 5.8% |
| exit | 5 | 3.2% |

## Failure Analysis

### Action Types with Negative Forward Returns
- add actions have negative avg 20D return (-2.30%)
- initiate actions have negative avg 20D return (-2.56%)

### Non-Differentiating Conviction Buckets
- Conviction buckets do not meaningfully differentiate outcomes (spread: 0.48%)

### Repeated Bad Recommendations
- MSFT had 2 initiate/add actions followed by >5% loss at 20D
- AMD had 8 initiate/add actions followed by >5% loss at 20D
- META had 3 initiate/add actions followed by >5% loss at 20D
- NVDA had 2 initiate/add actions followed by >5% loss at 20D

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
| Total exits | 5 |
| Premature exits (20D recovery >5%) | 3 |
| Premature exits (60D recovery >10%) | 1 |
| Avg forward 20D after exit | +8.73% |

### Exit Events
| Date | Ticker | Conviction | Prior Action | Probation? | 5D | 20D | 60D | Premature? |
|------|--------|------------|--------------|------------|-----|------|------|------------|
| 2026-01-22 | AAPL | 95 | trim | no | +3.99% | +11.04% | - | YES |
| 2025-11-20 | AMD | 95 | add | no | +0.05% | +7.48% | +12.53% | YES |
| 2025-12-18 | AMD | 95 | add | no | +6.88% | +4.46% | +3.11% |  |
| 2026-01-08 | AMD | 95 | hold | no | +7.96% | +23.48% | - | YES |
| 2026-02-12 | AMD | 97 | trim | no | -1.39% | -2.78% | - |  |

## Enhanced Failure Analysis

### Premature Exits (stock recovered after exit)
- **AAPL** exited 2026-01-22 at conviction 95.3, recovered N/A over 60D
- **AMD** exited 2025-11-20 at conviction 95.2, recovered +12.53% over 60D
- **AMD** exited 2026-01-08 at conviction 95.1, recovered N/A over 60D

### Repeatedly Negative Tickers
- **AMD**: 10 actions with >5% loss at 20D
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
