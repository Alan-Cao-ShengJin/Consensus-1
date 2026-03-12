# Step 9: Execution Wrapper & Paper-Trading Layer

## What Step 9 Adds

Step 9 introduces the boundary between recommendations and execution. Prior steps produce portfolio review decisions (INITIATE, ADD, TRIM, EXIT, HOLD, PROBATION, NO_ACTION). Step 9 converts the trading actions into structured, validated **order intents** and provides a **paper execution engine** to simulate fills without touching real capital.

### New files

| File | Purpose |
|------|---------|
| `execution_wrapper.py` | `OrderIntent` model + `build_execution_batch()` to convert `PortfolioReviewResult` into order intents |
| `execution_policy.py` | Deterministic sizing rules (target weights, notional deltas, share estimation, transaction costs) |
| `execution_guardrails.py` | Pre-trade validation: blocks invalid, conflicting, or policy-violating intents |
| `paper_execution_engine.py` | `PaperPortfolio` + `paper_execute()` for deterministic paper fills + file-based artifact export |
| `scripts/run_execution_wrapper.py` | CLI: `--demo`, `--latest-review`, `--validate-only`, `--paper-execute`, `--json`, `--dry-run` |
| `tests/test_step9.py` | 30+ tests covering all 9 required areas |

### Modified files

| File | Change |
|------|--------|
| `models.py` | Added `ExecutionIntentRecord`, `PaperFillRecord`, `PaperPortfolioSnapshotRecord` tables |


## Order Intent Model

Each `OrderIntent` contains:

- **ticker, side** (buy/sell), **action_type** (INITIATE/ADD/TRIM/EXIT)
- **target_weight_before / after**, **current_weight**
- **notional_delta** (estimated $ change)
- **estimated_shares** (if reference price available)
- **reference_price**
- **reason_codes** (from decision engine)
- **linked_funding_ticker** (if funded pairing)
- **review_date, review_id** (audit linkage)
- **dry_run / paper_trade** flags
- **is_validated, is_blocked, block_reasons** (set by guardrails)


## Guardrails

The pre-trade validation layer checks every intent against:

1. **No trade for non-trading actions** — HOLD/PROBATION/NO_ACTION must not produce orders
2. **No duplicate conflicting orders** — can't buy and sell the same ticker in one batch
3. **Funded pairs reconcile** — if intent references a funding ticker, the corresponding sell must exist
4. **No negative target weights**
5. **No target weight above position cap** (default 10%)
6. **No total gross exposure above max** (default 100%)
7. **No order without a reference price**
8. **No order from blocked recommendation** (defense in depth)
9. **Cooldown restrictions** — tickers on cooldown cannot be bought
10. **Probation restrictions** — tickers on probation cannot be added to
11. **Turnover cap** — total weight change cannot exceed weekly limit

Failed intents are **blocked with recorded reasons**, never silently fixed.


## Paper Execution Assumptions

- **Fill model (v1):** Fill at provided price (typically next-close). No slippage.
- **Execution order:** Sells first, then buys (to free capital for funded pairings).
- **Transaction cost:** Configurable basis points (default 10 bps).
- **Cash management:** Buys deducted from cash + cost; sells credited to cash - cost.
- **Position removal:** Positions with <= 0.001 shares are removed (float precision).
- **No broker connectivity.** Paper fills only.


## Recommendation vs Execution Boundary

This is a critical design boundary:

- **Generating order intents** does NOT mutate any live portfolio state (no DB writes to `portfolio_positions`, no side effects on `PortfolioReviewResult`).
- **Paper execution** mutates only `PaperPortfolio` state (an in-memory object).
- **No live position** is marked as executed unless a future real execution layer confirms it.
- The `was_executed` flag on `PortfolioDecision` remains `False` unless a future step sets it after real execution.


## Execution Artifacts

Step 9 uses **file-based output** (JSON) as the primary persistence for v1. This is simpler and more auditable than adding heavy ORM persistence at this stage.

Artifacts per execution run:
- `{date}_order_intents.json` — full batch of intents
- `{date}_paper_fills.json` — executed fills
- `{date}_execution_summary.json` — summary statistics
- `{date}_portfolio_snapshot.json` — portfolio state after execution

DB models (`ExecutionIntentRecord`, `PaperFillRecord`, `PaperPortfolioSnapshotRecord`) are defined for future use but not written to in the default paper execution path. A future step can persist to DB if needed.


## What Remains for Step 10

- **Real broker connectivity** — connect to a broker API for live order submission
- **Fill confirmation loop** — poll/receive actual fills and reconcile vs intents
- **Live portfolio state mutation** — update `PortfolioPosition` records after confirmed fills
- **Slippage modeling** — market impact, limit orders, partial fills
- **Scheduled execution** — cron/scheduler integration for automated weekly cycles
- **Alerting** — notify on blocked orders, execution failures, or significant drift
