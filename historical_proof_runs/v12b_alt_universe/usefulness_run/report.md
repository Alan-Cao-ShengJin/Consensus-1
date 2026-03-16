# Historical Proof Run: usefulness_run
Generated: 2026-03-15 10:16 UTC

## Run Configuration
- **Mode**: usefulness_run
- **Backfill window**: 2024-06-01 to 2025-01-01
- **Eval window**: 2024-07-31 to 2025-01-01
- **Cadence**: 7 days
- **Initial cash**: $1,000,000
- **Universe**: 15 tickers
- **Extractor**: stub_heuristic
- **Memory**: enabled
- **Benchmark**: SPY

## Degraded Run Warnings
- **DEGRADED: Running usefulness test with stub extractor. Results reflect heuristic claim extraction, not real LLM analysis. Pass --use-llm for real extraction.**

## Regeneration Summary
- Documents processed: 104
- Claims created: 106
- Thesis updates: 104
- State changes: 13
- State flips: 0

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
| Total return | +11.88% |
| Annualized return | +30.49% |
| Max drawdown | 6.00% |
| Reviews | 23 |
| Purity | degraded |

## Benchmark Comparison
| Benchmark | Return |
|-----------|--------|
| Portfolio | +11.88% |
| SPY | +7.09% |
| Excess vs SPY | +4.79% |
| Equal-weight | +27.11% |
| Excess vs EW | -15.23% |

## Forward Returns by Action Type
| Action | Count | Avg 5D | Avg 20D | Avg 60D |
|--------|-------|--------|---------|---------|
| exit | 1 | N/A | N/A | N/A |
| hold | 203 | +1.16% | +4.31% | +13.08% |
| initiate | 10 | +0.93% | +9.88% | +17.76% |

## Conviction Bucket Analysis
| Bucket | Actions | Avg Conviction | Avg 5D | Avg 20D | Avg 60D |
|--------|---------|----------------|--------|---------|---------|
| low | 0 | N/A | N/A | N/A | N/A |
| medium | 214 | 50 | +1.15% | +4.62% | +13.43% |
| high | 0 | N/A | N/A | N/A | N/A |

## Best Decisions (by 20D forward return)
| Date | Ticker | Action | Conviction | 5D | 20D | 60D |
|------|--------|--------|------------|-----|------|------|
| 2024-08-28 | PLTR | initiate | 50.0 | +3.69% | +20.06% | +47.76% |
| 2024-07-31 | LLY | initiate | 50.0 | -3.61% | +18.28% | +9.29% |
| 2024-08-07 | AMD | initiate | 50.0 | +6.30% | +16.97% | +32.82% |
| 2024-09-04 | META | initiate | 50.0 | -1.55% | +9.97% | +10.72% |
| 2024-08-07 | HD | initiate | 50.0 | +1.00% | +8.99% | +19.99% |
| 2024-07-31 | NVDA | initiate | 50.0 | -14.16% | +8.74% | +3.75% |
| 2024-08-07 | CAT | initiate | 50.0 | +3.14% | +7.77% | +21.88% |
| 2024-07-31 | COST | initiate | 50.0 | -2.45% | +6.59% | +7.74% |
| 2024-08-14 | TSLA | initiate | 50.0 | +10.60% | +4.58% | +8.15% |
| 2024-08-14 | AVGO | initiate | 50.0 | +6.35% | -3.11% | +15.47% |

## Worst Decisions (by 20D forward return)
| Date | Ticker | Action | Conviction | 5D | 20D | 60D |
|------|--------|--------|------------|-----|------|------|
| 2024-08-14 | AVGO | initiate | 50.0 | +6.35% | -3.11% | +15.47% |
| 2024-08-14 | TSLA | initiate | 50.0 | +10.60% | +4.58% | +8.15% |
| 2024-07-31 | COST | initiate | 50.0 | -2.45% | +6.59% | +7.74% |
| 2024-08-07 | CAT | initiate | 50.0 | +3.14% | +7.77% | +21.88% |
| 2024-07-31 | NVDA | initiate | 50.0 | -14.16% | +8.74% | +3.75% |
| 2024-08-07 | HD | initiate | 50.0 | +1.00% | +8.99% | +19.99% |
| 2024-09-04 | META | initiate | 50.0 | -1.55% | +9.97% | +10.72% |
| 2024-08-07 | AMD | initiate | 50.0 | +6.30% | +16.97% | +32.82% |
| 2024-07-31 | LLY | initiate | 50.0 | -3.61% | +18.28% | +9.29% |
| 2024-08-28 | PLTR | initiate | 50.0 | +3.69% | +20.06% | +47.76% |

## Per-Name Usefulness Summary
| Ticker | Actions | Docs | Claims | Avg 5D | Avg 20D | Avg 60D | Price Cov |
|--------|---------|------|--------|--------|---------|---------|-----------|
| AMD | 22 | 8 | 8 | +0.94% | -1.36% | -5.21% | 97% |
| AVGO | 21 | 9 | 9 | +2.37% | +7.14% | +12.99% | 97% |
| CAT | 22 | 7 | 7 | +0.88% | +1.57% | +6.48% | 97% |
| COST | 23 | 9 | 11 | +0.34% | +2.04% | +5.31% | 97% |
| CRM | 0 | 8 | 8 | — | — | — | 97% |
| GS | 0 | 0 | 0 | — | — | — | 97% |
| HD | 22 | 9 | 9 | +0.80% | +2.34% | +6.82% | 97% |
| JPM | 0 | 0 | 0 | — | — | — | 97% |
| LLY | 23 | 10 | 10 | -0.25% | -0.32% | -6.76% | 97% |
| META | 18 | 6 | 6 | +0.33% | +3.48% | +4.86% | 97% |
| NVDA | 23 | 7 | 7 | +0.20% | +2.89% | +11.20% | 97% |
| PLTR | 19 | 6 | 6 | +3.38% | +17.70% | +68.20% | 97% |
| TSLA | 21 | 7 | 7 | +2.99% | +13.60% | +44.02% | 97% |
| UNH | 0 | 9 | 9 | — | — | — | 97% |
| XOM | 0 | 9 | 9 | — | — | — | 97% |

## Source Coverage Diagnostics
- **Extractor mode**: stub_heuristic
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
- Recommendation changes: 18
- Change rate: 0.783 per review
- Short-hold exits (<30d): 0

### Action Mix
| Action | Count | % |
|--------|-------|---|
| hold | 203 | 67.9% |
| no_action | 85 | 28.4% |
| initiate | 10 | 3.3% |
| exit | 1 | 0.3% |

## Failure Analysis

### Degraded Run Flags
- Stub extraction: claims are heuristic, not LLM-generated

### Sparse Coverage Tickers
| Ticker | Issues | Docs | Claims | Price Cov |
|--------|--------|------|--------|-----------|
| GS | no documents; no claims extracted | 0 | 0 | 97.3% |
| JPM | no documents; no claims extracted | 0 | 0 | 97.3% |

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
| 2025-01-01 | AMD | 50 | hold | no | - | - | - |  |

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
- **Stub LLM mode**: claim extraction uses deterministic stub, not real LLM
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
