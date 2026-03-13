# Evaluation Framework — Consensus-1

This document defines how the system should be judged. The evaluation framework is specific to the monitored-universe public-equity intelligence use case: ~45 US large-cap names, concentrated portfolio of 8–15 positions, thesis-driven decision-making with deterministic scoring.

The system is a decision-support tool, not an autonomous trading agent. Evaluation must test whether the machinery produces *useful* outputs — not just correct ones.

---

## Layer A: Mechanistic Correctness

These tests verify that the system behaves as specified. They are prerequisites for trusting any higher-level evaluation.

| Test | What it proves | How to measure |
|------|---------------|----------------|
| **Replay determinism** | Same DB state + config → same outputs | Run replay twice with identical inputs, assert byte-identical results |
| **No future leakage** | Replay never uses data published after review date | Strict mode excludes candidates/checkpoints/valuations without temporal provenance; purity flags track every fallback |
| **Event clustering stability** | Same claims → same cluster assignments | Ingestion-time clustering produces stable `event_cluster_id`; thesis update consumes persisted state |
| **Evidence scoring determinism** | Same claim + same context → same evidence weight | `score_evidence()` is pure function of tier, freshness, novelty, cluster position, contradiction |
| **Conviction update bounds** | Per-document cap (±15), dampening at extremes | Unit tests on `apply_conviction_update()` |
| **State transition guardrails** | Score ≤15 → broken, ≤30 → probation, flip inertia | Unit tests on `resolve_state()` |
| **Memory retrieval determinism** | Same thesis + DB state → same memory snapshot | Deterministic SQL ordering (published_at DESC, id DESC) |

**Existing coverage:** replay purity tests, evidence pipeline tests, decision engine tests, memory retrieval tests.

---

## Layer B: Memory Usefulness

These tests measure whether the memory/evidence layer materially improves thesis updates.

| Metric | What it reveals | How to measure |
|--------|----------------|----------------|
| **Score stability (memory ON vs OFF)** | Memory reduces noise from individual documents | Compare avg absolute conviction delta per update |
| **State-flip frequency** | Memory provides inertia against oscillation | Count bullish↔bearish state transitions per run |
| **Repeated evidence downweighting** | Novelty classification works in practice | Track avg evidence weight for repetitive vs new claims |
| **Contradiction handling** | Contradictions are detected and affect scoring | Count contradicted claims; verify evidence weight reflects contradiction |
| **Thesis update count** | Memory doesn't suppress legitimate updates | Compare number of non-trivial state changes (memory ON vs OFF) |
| **Recommendation stability** | Memory reduces recommendation churn | Compare recommendation change frequency between modes |
| **Conviction volatility** | Memory dampens score volatility | Compare std dev of conviction scores across updates |

**Key evaluation:** Run the same replay window with memory enabled vs disabled. The memory-enabled run should show lower score volatility, fewer state flips, and similar or better final conviction alignment — without suppressing legitimate updates.

---

## Layer C: Decision Quality

These tests measure whether the portfolio decision engine produces sensible recommendations.

| Metric | What it reveals | How to measure |
|--------|----------------|----------------|
| **Recommendation mix** | System isn't degenerate (all holds, all exits) | Distribution of initiate/add/hold/trim/exit/probation/no_action over time |
| **Recommendation change frequency** | Decisions are responsive but not noisy | Track changes per ticker per review period |
| **Candidate ranking** | Higher-conviction candidates rank higher | Verify ordering in `evaluate_candidate()` output |
| **Action attribution** | Know *why* each decision was made | Categorize decisions by primary driver: valuation, evidence, checkpoint, deterioration |
| **Conviction at initiation** | System initiates at reasonable conviction levels | Distribution of conviction scores at initiation |
| **Probation → exit rate** | Discipline pipeline works | Fraction of probation entries that eventually exit |
| **Turnover cap effectiveness** | Cap prevents excessive trading | Count blocked actions from turnover cap |
| **Sector/name concentration** | Decisions aren't biased toward one name/sector | Action distribution by ticker |
| **False positive patterns** | Initiations followed by rapid exits | Track initiation → exit sequences with short holding periods |

**Decision attribution categories:**
- **Valuation-driven**: Zone is BUY or FULL_EXIT with conviction above floor
- **Evidence-driven**: Recent novel claims shifted conviction by ≥3 points
- **Checkpoint-driven**: Has upcoming checkpoint influencing hold/wait behavior
- **Deterioration-driven**: Conviction dropped below threshold (probation/exit)

---

## Layer D: Portfolio Outcome

These metrics measure portfolio-level results from replay. They require price data and completed shadow trades.

| Metric | What it reveals | How to measure |
|--------|----------------|----------------|
| **Total return** | Raw portfolio performance | (final value - initial) / initial |
| **Annualized return** | Time-adjusted performance | Geometric annualization from total return and holding period |
| **Max drawdown** | Worst peak-to-trough decline | Track running peak, compute largest decline |
| **Benchmark comparison** | Performance vs passive index (SPY) | Compare portfolio return to benchmark return over same window |
| **Equal-weight baseline** | Performance vs naive monitored-universe strategy | Equal-weight all monitored names, rebalance at same cadence |
| **Hit rate** | Fraction of exits with positive realized PnL | Positive exits / total exits |
| **Turnover** | Portfolio churn rate | Sum of absolute weight changes / number of reviews |
| **Cash exposure** | Investment efficiency | Average cash as % of total portfolio |
| **Holding period** | How long positions are held | Average days from initiation to exit |
| **Concentration** | Position sizing discipline | Max single-position weight, Herfindahl index |

### What these metrics do NOT tell us

- **Alpha significance**: With a short replay window and small universe, returns are not statistically significant. Report them honestly but don't overclaim.
- **Regime robustness**: Single-window replay doesn't prove the system works in all market conditions. Multiple windows or regime-tagged analysis is needed for that.
- **Causal attribution**: Portfolio return is driven by price movements in held names. A good return doesn't prove the decision engine is good — the names might have risen regardless.

---

## Evaluation Modes

### Standard replay
Run the decision engine through historical time with all features enabled. This is the baseline evaluation.

### Memory ablation
Run thesis updates with memory retrieval bypassed. Compare against standard replay to quantify memory's contribution.

### Strict vs non-strict replay
Compare strict replay (skip impure inputs) against non-strict (use fallbacks). Measures how much decision quality depends on data provenance completeness.

### Evidence feature ablation
Optionally disable contradiction metadata or evidence downweighting to measure their marginal contribution.

---

## Evaluation Artifacts

Each evaluation run produces a structured report containing:

1. **Run metadata**: Config, date range, mode, seed
2. **Mechanistic checks**: Purity level, leakage flags, fallback counts
3. **Decision summary**: Action counts, recommendation mix, conviction stats
4. **Portfolio summary**: Return, drawdown, turnover, cash exposure
5. **Benchmark comparison**: vs SPY, vs equal-weight baseline
6. **Memory comparison** (if ablation run): side-by-side metrics
7. **Diagnostics**: Warnings, missing data, degraded conditions

Reports are saved as JSON for machine consumption and as markdown for human review.

---

## Layer E: Historical Proof Runs

Historical proof runs go beyond replay evaluation by reconstructing thesis state from scratch using historical data, then measuring decision quality against actual forward returns.

See [docs/historical_proof_run.md](historical_proof_run.md) for the full contract.

### What a historical proof run adds over replay evaluation

| Capability | Replay evaluation | Historical proof run |
|-----------|-------------------|---------------------|
| Thesis state source | Pre-existing DB state | Rebuilt from scratch chronologically |
| Forward returns | Not measured | 5D / 20D / 60D per decision |
| Conviction bucket analysis | Not available | Low / medium / high |
| Data coverage reporting | Basic purity flags | Full source coverage stats |
| Memory ablation level | Same thesis state, different decision behavior | Different thesis evolution paths |
| Output format | JSON + markdown | Full proof pack (JSON + markdown + CSV tables) |

### Running a historical proof run

```bash
# Full proof run
python scripts/run_historical_proof.py --start 2024-06-01 --end 2025-01-01

# Backfill only
python scripts/run_historical_proof.py --start 2024-06-01 --end 2025-01-01 --backfill-only

# Evaluate on existing regeneration DB
python scripts/run_historical_proof.py --evaluate-only --regen-db path/to/regen.db

# Memory ablation
python scripts/run_historical_proof.py --start 2024-06-01 --end 2025-01-01 --memory-ablation

# Subset of tickers
python scripts/run_historical_proof.py --start 2024-06-01 --end 2025-01-01 --tickers AAPL,MSFT,NVDA
```

### Proof pack output

A valid proof run produces an output directory containing:
- `summary.json` — machine-readable full report
- `report.md` — human-readable markdown report
- `decisions.csv` — per-review-date decisions
- `action_outcomes.csv` — per-action forward returns
- `benchmark.csv` — benchmark comparison
- `conviction_buckets.csv` — conviction bucket summary
- `memory_comparison.csv` — memory ON vs OFF (if ablation run)

---

## Limitations (v1)

1. **No ground truth labels**: We cannot score thesis predictions against actual outcomes without forward price data and defined success criteria. Decision quality metrics are behavioral, not accuracy-based.
2. **Small universe, short windows**: Statistical significance of portfolio outcomes is low. Treat return metrics as directional indicators, not proof of alpha.
3. **No regime tagging**: Performance is not broken down by market regime (bull/bear/sideways). This requires external regime classification data.
4. **No sector-level analysis**: Sector attribution requires sector classification per ticker, which is not yet in the schema.
5. **Stub LLM mode**: Most evaluations use the stub classifier. LLM-mode evaluation requires API access and is not deterministic across runs.
6. **Single portfolio configuration**: Evaluation uses fixed initial cash, transaction costs, and position sizing. Sensitivity to these parameters is not tested.
