# Historical Proof Run: usefulness_finnhub_v1
Generated: 2026-03-13 23:31 UTC

## Run Configuration
- **Mode**: usefulness_run
- **Backfill window**: 2025-09-01 to 2026-03-01
- **Eval window**: 2025-10-01 to 2026-03-01
- **Cadence**: 7 days
- **Initial cash**: $1,000,000
- **Universe**: 5 tickers
- **Extractor**: stub_heuristic
- **Memory**: enabled
- **Benchmark**: SPY

## Degraded Run Warnings
- **DEGRADED: Running usefulness test with stub extractor. Results reflect heuristic claim extraction, not real LLM analysis. Pass --use-llm for real extraction.**

## Regeneration Summary
- Documents processed: 36
- Claims created: 38
- Thesis updates: 36
- State changes: 5
- State flips: 0

### Data Coverage
- Tickers with price data: 5/5
- Total price rows: 620
- Total documents: 36
  - 10K: 4
  - 10Q: 6
  - 8K: 26

## Key Metrics
| Metric | Value |
|--------|-------|
| Total return | -0.47% |
| Annualized return | -1.18% |
| Max drawdown | 1.37% |
| Reviews | 22 |
| Purity | degraded |

## Benchmark Comparison
| Benchmark | Return |
|-----------|--------|
| Portfolio | -0.47% |
| SPY | +2.93% |
| Excess vs SPY | -3.40% |
| Equal-weight | -2.67% |
| Excess vs EW | +2.20% |

## Forward Returns by Action Type
| Action | Count | Avg 5D | Avg 20D | Avg 60D |
|--------|-------|--------|---------|---------|
| hold | 88 | -0.01% | -0.87% | -3.84% |
| initiate | 5 | -4.78% | -1.91% | -4.81% |

## Conviction Bucket Analysis
| Bucket | Actions | Avg Conviction | Avg 5D | Avg 20D | Avg 60D |
|--------|---------|----------------|--------|---------|---------|
| low | 0 | N/A | N/A | N/A | N/A |
| medium | 93 | 50 | -0.27% | -0.93% | -3.93% |
| high | 0 | N/A | N/A | N/A | N/A |

## Best Decisions (by 20D forward return)
| Date | Ticker | Action | Conviction | 5D | 20D | 60D |
|------|--------|--------|------------|-----|------|------|
| 2025-10-08 | AMD | initiate | 50.0 | -8.13% | +9.53% | -7.47% |
| 2025-11-05 | AAPL | initiate | 50.0 | -0.17% | +2.63% | +0.42% |
| 2025-10-01 | MSFT | initiate | 50.0 | +1.70% | -0.39% | -5.15% |
| 2025-11-19 | NVDA | initiate | 50.0 | -2.13% | -0.83% | -0.15% |
| 2025-10-29 | META | initiate | 50.0 | -15.16% | -20.49% | -11.69% |

## Worst Decisions (by 20D forward return)
| Date | Ticker | Action | Conviction | 5D | 20D | 60D |
|------|--------|--------|------------|-----|------|------|
| 2025-10-29 | META | initiate | 50.0 | -15.16% | -20.49% | -11.69% |
| 2025-11-19 | NVDA | initiate | 50.0 | -2.13% | -0.83% | -0.15% |
| 2025-10-01 | MSFT | initiate | 50.0 | +1.70% | -0.39% | -5.15% |
| 2025-11-05 | AAPL | initiate | 50.0 | -0.17% | +2.63% | +0.42% |
| 2025-10-08 | AMD | initiate | 50.0 | -8.13% | +9.53% | -7.47% |

## Per-Name Usefulness Summary
| Ticker | Actions | Docs | Claims | Avg 5D | Avg 20D | Avg 60D | Price Cov |
|--------|---------|------|--------|--------|---------|---------|-----------|
| AAPL | 17 | 7 | 8 | -0.44% | -0.22% | -4.55% | 95% |
| AMD | 21 | 10 | 11 | -0.16% | -1.32% | -4.64% | 95% |
| META | 18 | 8 | 8 | +0.14% | +0.55% | +1.61% | 95% |
| MSFT | 22 | 6 | 6 | -0.80% | -3.39% | -9.77% | 95% |
| NVDA | 15 | 5 | 5 | +0.06% | +0.79% | +1.98% | 95% |

## Source Coverage Diagnostics
- **Extractor mode**: stub_heuristic
- **Benchmark available**: yes
- **Tickers with prices**: 5
- **Tickers without prices**: 0
- **Total price rows**: 620

### Documents by Source Type
| Source Type | Count |
|------------|-------|
| 10K | 4 |
| 10Q | 6 |
| 8K | 26 |

### Source Gaps
- **ALL**: No documents ingested in 2026-03

## Decision Summary
- Total actions: 93
- Recommendation changes: 5
- Change rate: 0.227 per review
- Short-hold exits (<30d): 0

### Action Mix
| Action | Count | % |
|--------|-------|---|
| hold | 88 | 94.6% |
| initiate | 5 | 5.4% |

## Failure Analysis

### Degraded Run Flags
- Stub extraction: claims are heuristic, not LLM-generated

### Action Types with Negative Forward Returns
- hold actions have negative avg 20D return (-0.87%)
- initiate actions have negative avg 20D return (-1.91%)

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
- **AMD**: 6 actions with >5% loss at 20D
- **META**: 3 actions with >5% loss at 20D
- **MSFT**: 7 actions with >5% loss at 20D

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
