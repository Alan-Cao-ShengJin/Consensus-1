# Historical Proof Run: full_llm_v7_momentum
Generated: 2026-03-14 18:34 UTC

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
| Total return | -3.01% |
| Annualized return | -5.17% |
| Max drawdown | 7.17% |
| Reviews | 31 |
| Purity | degraded |

## Benchmark Comparison
| Benchmark | Return |
|-----------|--------|
| Portfolio | -3.01% |
| SPY | +9.15% |
| Excess vs SPY | -12.16% |
| Equal-weight | -0.24% |
| Excess vs EW | -2.77% |

## Forward Returns by Action Type
| Action | Count | Avg 5D | Avg 20D | Avg 60D |
|--------|-------|--------|---------|---------|
| add | 10 | +1.11% | +1.07% | +1.22% |
| exit | 1 | +10.95% | +9.54% | N/A |
| hold | 83 | +0.21% | +0.69% | +0.51% |
| initiate | 6 | -0.19% | -3.13% | +9.86% |
| trim | 5 | +1.42% | +3.43% | +5.36% |

## Conviction Bucket Analysis
| Bucket | Actions | Avg Conviction | Avg 5D | Avg 20D | Avg 60D |
|--------|---------|----------------|--------|---------|---------|
| low | 0 | N/A | N/A | N/A | N/A |
| medium | 0 | N/A | N/A | N/A | N/A |
| high | 105 | 89 | +0.43% | +0.71% | +1.34% |

## Best Decisions (by 20D forward return)
| Date | Ticker | Action | Conviction | 5D | 20D | 60D |
|------|--------|--------|------------|-----|------|------|
| 2025-10-02 | AMD | add | 84.8 | +24.62% | +35.64% | +29.48% |
| 2025-11-20 | META | trim | 92.6 | +7.99% | +10.35% | +5.36% |
| 2026-02-05 | AMD | exit | 97.4 | +10.95% | +9.54% | — |
| 2026-01-08 | NVDA | add | 79.4 | +0.42% | +3.50% | — |
| 2026-01-29 | AAPL | add | 95.3 | +4.34% | +2.45% | — |
| 2026-02-05 | MSFT | trim | 96.7 | +4.98% | +1.99% | — |
| 2025-08-21 | META | initiate | 79.9 | +2.03% | +1.74% | -0.87% |
| 2025-08-21 | MSFT | initiate | 72.4 | -0.44% | -0.77% | +2.49% |
| 2026-01-01 | NVDA | add | 79.4 | +0.40% | -1.71% | -4.99% |
| 2026-02-12 | MSFT | trim | 96.7 | -1.24% | -2.04% | — |

## Worst Decisions (by 20D forward return)
| Date | Ticker | Action | Conviction | 5D | 20D | 60D |
|------|--------|--------|------------|-----|------|------|
| 2025-11-13 | AMD | add | 95.2 | -7.13% | -12.24% | -16.24% |
| 2026-01-01 | AAPL | initiate | 94.9 | -3.49% | -8.91% | -2.73% |
| 2026-01-15 | NVDA | add | 79.4 | -4.80% | -6.88% | — |
| 2025-11-27 | NVDA | initiate | 79.4 | +0.67% | -5.16% | +3.45% |
| 2025-12-25 | NVDA | add | 79.4 | -0.57% | -2.90% | +1.56% |
| 2025-08-21 | AMD | initiate | 82.0 | +1.78% | -2.55% | +46.94% |
| 2026-02-05 | META | add | 93.5 | +0.08% | -2.46% | — |
| 2025-12-18 | META | add | 92.6 | +0.07% | -2.37% | -3.71% |
| 2026-01-29 | NVDA | add | 86.6 | -6.32% | -2.35% | — |
| 2026-02-12 | MSFT | trim | 96.7 | -1.24% | -2.04% | — |

## Per-Name Usefulness Summary
| Ticker | Actions | Docs | Claims | Avg 5D | Avg 20D | Avg 60D | Price Cov |
|--------|---------|------|--------|--------|---------|---------|-----------|
| AAPL | 9 | 20 | 99 | +0.28% | +1.58% | -2.73% | 96% |
| AMD | 26 | 23 | 120 | +1.50% | +5.35% | +14.95% | 96% |
| META | 28 | 19 | 109 | -0.24% | -1.60% | -4.45% | 96% |
| MSFT | 28 | 18 | 99 | +0.13% | -1.76% | -6.45% | 96% |
| NVDA | 14 | 18 | 95 | +0.47% | +0.87% | +1.87% | 96% |

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
- Recommendation changes: 30
- Change rate: 0.968 per review
- Short-hold exits (<30d): 0

### Action Mix
| Action | Count | % |
|--------|-------|---|
| hold | 83 | 53.5% |
| no_action | 50 | 32.3% |
| add | 10 | 6.5% |
| initiate | 6 | 3.9% |
| trim | 5 | 3.2% |
| exit | 1 | 0.6% |

## Failure Analysis

### Action Types with Negative Forward Returns
- initiate actions have negative avg 20D return (-3.13%)

### Repeated Bad Recommendations
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
| Total exits | 1 |
| Premature exits (20D recovery >5%) | 1 |
| Premature exits (60D recovery >10%) | 0 |
| Avg forward 20D after exit | +9.54% |

### Exit Events
| Date | Ticker | Conviction | Prior Action | Probation? | 5D | 20D | 60D | Premature? |
|------|--------|------------|--------------|------------|-----|------|------|------------|
| 2026-02-05 | AMD | 97 | hold | no | +10.95% | +9.54% | - | YES |

## Enhanced Failure Analysis

### Premature Exits (stock recovered after exit)
- **AMD** exited 2026-02-05 at conviction 97.4, recovered N/A over 60D

### Repeatedly Negative Tickers
- **AMD**: 8 actions with >5% loss at 20D
- **META**: 7 actions with >5% loss at 20D
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
