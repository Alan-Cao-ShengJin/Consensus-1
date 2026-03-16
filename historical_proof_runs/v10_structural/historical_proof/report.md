# Historical Proof Run: historical_proof
Generated: 2026-03-15 00:50 UTC

## Run Configuration
- **Mode**: regenerate
- **Backfill window**: 2024-06-01 to 2025-01-01
- **Eval window**: 2024-07-31 to 2025-01-01
- **Cadence**: 7 days
- **Initial cash**: $1,000,000
- **Universe**: 45 tickers
- **Extractor**: stub_heuristic
- **Memory**: enabled
- **Benchmark**: SPY

## Regeneration Summary
- Documents processed: 307
- Claims created: 312
- Thesis updates: 307
- State changes: 42
- State flips: 0

### Data Coverage
- Tickers with price data: 44/45
- Total price rows: 6468
- Total documents: 307
  - 10K: 8
  - 10Q: 80
  - 8K: 219

## Key Metrics
| Metric | Value |
|--------|-------|
| Total return | +6.64% |
| Annualized return | +16.46% |
| Max drawdown | 5.55% |
| Reviews | 23 |
| Purity | degraded |

## Benchmark Comparison
| Benchmark | Return |
|-----------|--------|
| Portfolio | +6.64% |
| SPY | +7.09% |
| Excess vs SPY | -0.45% |
| Equal-weight | +15.83% |
| Excess vs EW | -9.19% |

## Conviction Bucket Analysis
| Bucket | Actions | Avg Conviction | Avg 5D | Avg 20D | Avg 60D |
|--------|---------|----------------|--------|---------|---------|
| low | 0 | N/A | N/A | N/A | N/A |
| medium | 0 | N/A | N/A | N/A | N/A |
| high | 0 | N/A | N/A | N/A | N/A |

## Per-Name Usefulness Summary
| Ticker | Actions | Docs | Claims | Avg 5D | Avg 20D | Avg 60D | Price Cov |
|--------|---------|------|--------|--------|---------|---------|-----------|
| AAPL | 0 | 7 | 8 | — | — | — | 97% |
| ABNB | 0 | 5 | 5 | — | — | — | 97% |
| AMD | 0 | 8 | 8 | — | — | — | 97% |
| AMZN | 0 | 4 | 4 | — | — | — | 97% |
| AVGO | 0 | 9 | 9 | — | — | — | 97% |
| BRK-B | 0 | 5 | 5 | — | — | — | 97% |
| CEG | 0 | 7 | 7 | — | — | — | 97% |
| COIN | 0 | 6 | 6 | — | — | — | 97% |
| CRM | 0 | 8 | 8 | — | — | — | 97% |
| CRWD | 0 | 9 | 9 | — | — | — | 97% |
| DDOG | 0 | 7 | 7 | — | — | — | 97% |
| DIS | 0 | 6 | 6 | — | — | — | 97% |
| ENPH | 0 | 5 | 5 | — | — | — | 97% |
| FSLR | 0 | 5 | 5 | — | — | — | 97% |
| GD | 0 | 6 | 6 | — | — | — | 97% |
| GOOGL | 0 | 11 | 11 | — | — | — | 97% |
| GS | 0 | 0 | 0 | — | — | — | 97% |
| INTC | 0 | 10 | 11 | — | — | — | 97% |
| ISRG | 0 | 5 | 5 | — | — | — | 97% |
| JPM | 0 | 0 | 0 | — | — | — | 97% |
| LLY | 0 | 10 | 10 | — | — | — | 97% |
| LMT | 0 | 9 | 9 | — | — | — | 97% |
| MA | 0 | 7 | 7 | — | — | — | 97% |
| MDB | 0 | 8 | 8 | — | — | — | 97% |
| META | 0 | 6 | 6 | — | — | — | 97% |
| MRNA | 0 | 7 | 7 | — | — | — | 97% |
| MRVL | 0 | 9 | 9 | — | — | — | 97% |
| MSFT | 0 | 7 | 7 | — | — | — | 97% |
| MU | 0 | 10 | 10 | — | — | — | 97% |
| NET | 0 | 6 | 6 | — | — | — | 97% |
| NFLX | 0 | 6 | 6 | — | — | — | 97% |
| NOW | 0 | 5 | 5 | — | — | — | 97% |
| NVDA | 0 | 7 | 7 | — | — | — | 97% |
| PLTR | 0 | 6 | 6 | — | — | — | 97% |
| PYPL | 0 | 7 | 7 | — | — | — | 97% |
| QCOM | 0 | 7 | 9 | — | — | — | 97% |
| RBLX | 0 | 7 | 7 | — | — | — | 97% |
| RTX | 0 | 8 | 8 | — | — | — | 97% |
| SNOW | 0 | 7 | 7 | — | — | — | 97% |
| SQ | 0 | 0 | 0 | — | — | — | 0% |
| TSLA | 0 | 7 | 7 | — | — | — | 97% |
| UBER | 0 | 7 | 7 | — | — | — | 97% |
| V | 0 | 7 | 7 | — | — | — | 97% |
| VST | 0 | 18 | 18 | — | — | — | 97% |
| ZS | 0 | 6 | 7 | — | — | — | 97% |

## Source Coverage Diagnostics
- **Extractor mode**: stub_heuristic
- **Benchmark available**: yes
- **Tickers with prices**: 44
- **Tickers without prices**: 1
- **Total price rows**: 6468

### Documents by Source Type
| Source Type | Count |
|------------|-------|
| 10K | 8 |
| 10Q | 80 |
| 8K | 219 |

### Source Gaps
- **SQ**: No documents found for SQ in evaluation window
- **GS**: No documents found for GS in evaluation window
- **JPM**: No documents found for JPM in evaluation window
- **ALL**: No documents ingested in 2025-01

## Decision Summary
- Total actions: 961
- Recommendation changes: 0
- Change rate: 0.000 per review
- Short-hold exits (<30d): 0

### Action Mix
| Action | Count | % |
|--------|-------|---|
| no_action | 961 | 100.0% |

## Failure Analysis

### Degraded Run Flags
- Stub extraction: claims are heuristic, not LLM-generated

### Sparse Coverage Tickers
| Ticker | Issues | Docs | Claims | Price Cov |
|--------|--------|------|--------|-----------|
| GS | no documents; no claims extracted | 0 | 0 | 97.3% |
| JPM | no documents; no claims extracted | 0 | 0 | 97.3% |
| SQ | no documents; no claims extracted; price coverage 0% | 0 | 0 | 0.0% |

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
- No action outcomes generated — check data availability

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
