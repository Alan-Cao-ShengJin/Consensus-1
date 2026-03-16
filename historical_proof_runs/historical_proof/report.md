# Historical Proof Run: historical_proof
Generated: 2026-03-14 19:47 UTC

## Run Configuration
- **Mode**: evaluate_only
- **Backfill window**: 2024-06-01 to 2025-01-01
- **Eval window**: 2024-07-31 to 2025-01-01
- **Cadence**: 7 days
- **Initial cash**: $1,000,000
- **Universe**: 45 tickers
- **Extractor**: stub_heuristic
- **Memory**: enabled
- **Benchmark**: SPY

## Degraded Run Warnings
- **DEGRADED: Running usefulness test with stub extractor. Results reflect heuristic claim extraction, not real LLM analysis. Pass --use-llm for real extraction.**
- **Universe has 45 tickers — consider narrowing for inspectable results**

## Key Metrics
| Metric | Value |
|--------|-------|
| Total return | -95.09% |
| Annualized return | -99.92% |
| Max drawdown | 0.00% |
| Reviews | 23 |
| Purity | strict |

## Benchmark Comparison
| Benchmark | Return |
|-----------|--------|
| Portfolio | -95.09% |

## Conviction Bucket Analysis
| Bucket | Actions | Avg Conviction | Avg 5D | Avg 20D | Avg 60D |
|--------|---------|----------------|--------|---------|---------|
| low | 0 | N/A | N/A | N/A | N/A |
| medium | 0 | N/A | N/A | N/A | N/A |
| high | 0 | N/A | N/A | N/A | N/A |

## Per-Name Usefulness Summary
| Ticker | Actions | Docs | Claims | Avg 5D | Avg 20D | Avg 60D | Price Cov |
|--------|---------|------|--------|--------|---------|---------|-----------|
| AAPL | 0 | 3 | 7 | — | — | — | 0% |
| ABNB | 0 | 0 | 0 | — | — | — | 0% |
| AMD | 0 | 6 | 20 | — | — | — | 0% |
| AMZN | 0 | 3 | 8 | — | — | — | 0% |
| AVGO | 0 | 7 | 25 | — | — | — | 0% |
| BRK-B | 0 | 0 | 0 | — | — | — | 0% |
| CEG | 0 | 0 | 0 | — | — | — | 0% |
| COIN | 0 | 0 | 0 | — | — | — | 0% |
| CRM | 0 | 6 | 16 | — | — | — | 0% |
| CRWD | 0 | 5 | 18 | — | — | — | 0% |
| DDOG | 0 | 0 | 0 | — | — | — | 0% |
| DIS | 0 | 0 | 0 | — | — | — | 0% |
| ENPH | 0 | 0 | 0 | — | — | — | 0% |
| FSLR | 0 | 0 | 0 | — | — | — | 0% |
| GD | 0 | 0 | 0 | — | — | — | 0% |
| GOOGL | 0 | 5 | 14 | — | — | — | 0% |
| GS | 0 | 0 | 0 | — | — | — | 0% |
| INTC | 0 | 13 | 28 | — | — | — | 0% |
| ISRG | 0 | 0 | 0 | — | — | — | 0% |
| JPM | 0 | 0 | 0 | — | — | — | 0% |
| LLY | 0 | 0 | 0 | — | — | — | 0% |
| LMT | 0 | 0 | 0 | — | — | — | 0% |
| MA | 0 | 0 | 0 | — | — | — | 0% |
| MDB | 0 | 0 | 0 | — | — | — | 0% |
| META | 0 | 5 | 14 | — | — | — | 0% |
| MRNA | 0 | 0 | 0 | — | — | — | 0% |
| MRVL | 0 | 0 | 0 | — | — | — | 0% |
| MSFT | 0 | 4 | 11 | — | — | — | 0% |
| MU | 0 | 0 | 0 | — | — | — | 0% |
| NET | 0 | 0 | 0 | — | — | — | 0% |
| NFLX | 0 | 0 | 0 | — | — | — | 0% |
| NOW | 0 | 6 | 10 | — | — | — | 0% |
| NVDA | 0 | 4 | 8 | — | — | — | 0% |
| PLTR | 0 | 2 | 6 | — | — | — | 0% |
| PYPL | 0 | 0 | 0 | — | — | — | 0% |
| QCOM | 0 | 6 | 12 | — | — | — | 0% |
| RBLX | 0 | 0 | 0 | — | — | — | 0% |
| RTX | 0 | 0 | 0 | — | — | — | 0% |
| SNOW | 0 | 0 | 0 | — | — | — | 0% |
| SQ | 0 | 0 | 0 | — | — | — | 0% |
| TSLA | 0 | 5 | 16 | — | — | — | 0% |
| UBER | 0 | 0 | 0 | — | — | — | 0% |
| V | 0 | 0 | 0 | — | — | — | 0% |
| VST | 0 | 0 | 0 | — | — | — | 0% |
| ZS | 0 | 0 | 0 | — | — | — | 0% |

## Source Coverage Diagnostics
- **Extractor mode**: stub_heuristic
- **Benchmark available**: yes
- **Tickers with prices**: 15
- **Tickers without prices**: 30
- **Total price rows**: 1500

### Documents by Source Type
| Source Type | Count |
|------------|-------|
| 10K | 3 |
| 10Q | 16 |
| 8K | 61 |

### Source Gaps
- **MRVL**: No documents found for MRVL in evaluation window
- **MU**: No documents found for MU in evaluation window
- **SNOW**: No documents found for SNOW in evaluation window
- **DDOG**: No documents found for DDOG in evaluation window
- **NET**: No documents found for NET in evaluation window
- **MDB**: No documents found for MDB in evaluation window
- **V**: No documents found for V in evaluation window
- **MA**: No documents found for MA in evaluation window
- **SQ**: No documents found for SQ in evaluation window
- **PYPL**: No documents found for PYPL in evaluation window
- **COIN**: No documents found for COIN in evaluation window
- **NFLX**: No documents found for NFLX in evaluation window
- **DIS**: No documents found for DIS in evaluation window
- **RBLX**: No documents found for RBLX in evaluation window
- **LLY**: No documents found for LLY in evaluation window
- **MRNA**: No documents found for MRNA in evaluation window
- **ISRG**: No documents found for ISRG in evaluation window
- **ENPH**: No documents found for ENPH in evaluation window
- **FSLR**: No documents found for FSLR in evaluation window
- **CEG**: No documents found for CEG in evaluation window

## Decision Summary
- Total actions: 0
- Recommendation changes: 0
- Change rate: 0.000 per review
- Short-hold exits (<30d): 0

## Failure Analysis

### Degraded Run Flags
- Stub extraction: claims are heuristic, not LLM-generated

### Sparse Coverage Tickers
| Ticker | Issues | Docs | Claims | Price Cov |
|--------|--------|------|--------|-----------|
| AAPL | price coverage 0% | 3 | 7 | 0.0% |
| ABNB | no documents; no claims extracted; price coverage 0% | 0 | 0 | 0.0% |
| AMD | price coverage 0% | 6 | 20 | 0.0% |
| AMZN | price coverage 0% | 3 | 8 | 0.0% |
| AVGO | price coverage 0% | 7 | 25 | 0.0% |
| BRK-B | no documents; no claims extracted; price coverage 0% | 0 | 0 | 0.0% |
| CEG | no documents; no claims extracted; price coverage 0% | 0 | 0 | 0.0% |
| COIN | no documents; no claims extracted; price coverage 0% | 0 | 0 | 0.0% |
| CRM | price coverage 0% | 6 | 16 | 0.0% |
| CRWD | price coverage 0% | 5 | 18 | 0.0% |
| DDOG | no documents; no claims extracted; price coverage 0% | 0 | 0 | 0.0% |
| DIS | no documents; no claims extracted; price coverage 0% | 0 | 0 | 0.0% |
| ENPH | no documents; no claims extracted; price coverage 0% | 0 | 0 | 0.0% |
| FSLR | no documents; no claims extracted; price coverage 0% | 0 | 0 | 0.0% |
| GD | no documents; no claims extracted; price coverage 0% | 0 | 0 | 0.0% |
| GOOGL | price coverage 0% | 5 | 14 | 0.0% |
| GS | no documents; no claims extracted; price coverage 0% | 0 | 0 | 0.0% |
| INTC | price coverage 0% | 13 | 28 | 0.0% |
| ISRG | no documents; no claims extracted; price coverage 0% | 0 | 0 | 0.0% |
| JPM | no documents; no claims extracted; price coverage 0% | 0 | 0 | 0.0% |
| LLY | no documents; no claims extracted; price coverage 0% | 0 | 0 | 0.0% |
| LMT | no documents; no claims extracted; price coverage 0% | 0 | 0 | 0.0% |
| MA | no documents; no claims extracted; price coverage 0% | 0 | 0 | 0.0% |
| MDB | no documents; no claims extracted; price coverage 0% | 0 | 0 | 0.0% |
| META | price coverage 0% | 5 | 14 | 0.0% |
| MRNA | no documents; no claims extracted; price coverage 0% | 0 | 0 | 0.0% |
| MRVL | no documents; no claims extracted; price coverage 0% | 0 | 0 | 0.0% |
| MSFT | price coverage 0% | 4 | 11 | 0.0% |
| MU | no documents; no claims extracted; price coverage 0% | 0 | 0 | 0.0% |
| NET | no documents; no claims extracted; price coverage 0% | 0 | 0 | 0.0% |
| NFLX | no documents; no claims extracted; price coverage 0% | 0 | 0 | 0.0% |
| NOW | price coverage 0% | 6 | 10 | 0.0% |
| NVDA | price coverage 0% | 4 | 8 | 0.0% |
| PLTR | only 2 documents; price coverage 0% | 2 | 6 | 0.0% |
| PYPL | no documents; no claims extracted; price coverage 0% | 0 | 0 | 0.0% |
| QCOM | price coverage 0% | 6 | 12 | 0.0% |
| RBLX | no documents; no claims extracted; price coverage 0% | 0 | 0 | 0.0% |
| RTX | no documents; no claims extracted; price coverage 0% | 0 | 0 | 0.0% |
| SNOW | no documents; no claims extracted; price coverage 0% | 0 | 0 | 0.0% |
| SQ | no documents; no claims extracted; price coverage 0% | 0 | 0 | 0.0% |
| TSLA | price coverage 0% | 5 | 16 | 0.0% |
| UBER | no documents; no claims extracted; price coverage 0% | 0 | 0 | 0.0% |
| V | no documents; no claims extracted; price coverage 0% | 0 | 0 | 0.0% |
| VST | no documents; no claims extracted; price coverage 0% | 0 | 0 | 0.0% |
| ZS | no documents; no claims extracted; price coverage 0% | 0 | 0 | 0.0% |

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
