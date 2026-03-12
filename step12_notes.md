# Step 12: Live-Readiness Layer

## What This Step Adds

Read-only broker/account synchronization, reconciliation, hardened approval controls, and live-readiness checks. The system can now compare its internal state against real external account data without placing any orders.

Core principle: the machine may read real account state, but it must not place live orders.


## New Files

| File | Purpose |
|------|---------|
| `broker_interface.py` | Abstract broker interface — read-only data structures and contract |
| `broker_readonly_adapter.py` | Mock and file-based broker adapters |
| `account_sync.py` | Reconciliation engine: internal vs broker state comparison |
| `approval_hardened.py` | Hardened approval model with state machine, expiry, identity |
| `live_readiness_checks.py` | Pre-trade readiness checks — 7 checks that gate any future live action |
| `scripts/run_account_sync.py` | CLI entrypoint for account sync and readiness checks |
| `tests/test_step12.py` | 87 deterministic tests |
| `step12_notes.md` | This document |


## Modified Files

| File | Change |
|------|--------|
| `config.py` | Added `LIVE_READONLY` and `LIVE_DISABLED` environments, default configs |


## Broker Abstraction

`BrokerInterface` (abstract base class) defines read-only operations:

| Method | Returns |
|--------|---------|
| `get_account_snapshot()` | Full account state |
| `get_cash()` | Available cash |
| `get_positions()` | Current holdings |
| `get_open_orders()` | Pending orders |
| `get_recent_fills()` | Recent executions |
| `get_reference_price(ticker)` | Single ticker price |
| `get_reference_prices(tickers)` | Multiple ticker prices |

Write methods (`submit_order`, `cancel_order`, `modify_order`) raise `NotImplementedError` unconditionally.

### Adapters

| Adapter | Purpose |
|---------|---------|
| `MockBrokerAdapter` | Deterministic mock for testing/demo — configurable positions, cash, orders, fills, prices |
| `FileBrokerAdapter` | Loads account snapshot from JSON file — useful for replaying known states |

Factory: `create_broker_adapter(mode="mock"|"file", **kwargs)`


## Reconciliation

`account_sync.reconcile()` compares broker and internal state:

| Output | What it detects |
|--------|----------------|
| `cash_matched` / `cash_diff` | Cash difference between internal and broker |
| `matched_count` | Positions that match on shares |
| `mismatch_count` | Positions with share count differences |
| `missing_broker_count` | Positions in internal but not at broker |
| `missing_internal_count` | Positions at broker but not internally |
| `order_conflicts` | Open orders that conflict with new intents |
| `intent_checks` | Per-intent feasibility against external state |

### Intent feasibility checks

| Check | Detects |
|-------|---------|
| Sell intent, no broker position | Internal trim/exit but broker has nothing |
| Buy intent, insufficient cash | Internal initiate but broker can't fund it |
| Open order side mismatch | Existing buy order vs new sell intent |
| Internal/broker divergence | Share counts differ between systems |

Tolerances: cash ±$1, shares ±0.01, weights ±0.5%


## Approval Hardening

`approval_hardened.py` replaces the basic approval gate with a state machine:

```
PENDING → APPROVED  (requires approver_id)
PENDING → REJECTED  (requires approver_id + reason)
PENDING → EXPIRED   (automatic, past expiry window)
```

Fields captured in approval artifact:

| Field | Purpose |
|-------|---------|
| `approver_id` | Who approved/rejected |
| `approver_name` | Human-readable approver name |
| `created_at` / `updated_at` | Timestamps |
| `expires_at` | Auto-expiry deadline (default: 24 hours) |
| `rejection_reason` | Why rejected |
| `environment` / `run_id` | Context |
| `intents_count` | How many intents in the batch |

Terminal states cannot be changed. Expired approvals cannot be approved.


## Environment Model

| Environment | Broker sync | Reviews/intents | Order submission | Approval required |
|-------------|-------------|-----------------|------------------|-------------------|
| `DEMO` | No | Synthetic | No | No |
| `PAPER` | No | Real DB | Paper only | Optional |
| `LIVE_READONLY` | Yes (read-only) | Yes | **No** | **Yes** |
| `LIVE_DISABLED` | Blocked | Blocked | **No** | **Yes** |
| `LIVE` | — | — | Raises error | — |

`LIVE_READONLY` is the new mode for Step 12: sync broker state, generate reviews and intents, run readiness checks, but never submit orders.

`LIVE_DISABLED` is the protective default: everything broker-facing is blocked.


## Live-Readiness Checks

`live_readiness_checks.py` runs 7 pre-trade checks:

| Check | What it validates |
|-------|-------------------|
| `environment` | Must be `live_readonly` |
| `no_live_order_path` | Confirms no order submission possible |
| `sync_freshness` | Broker sync is recent enough (default: 60 min) |
| `reconciliation_clean` | No unresolved mismatches, cash within threshold |
| `approval_current` | Approval exists, is APPROVED, not expired |
| `intents_consistent` | No infeasible intents or order conflicts |
| `no_duplicate_batch` | Batch ID is unique |

All checks produce a `ReadinessReport` with per-check pass/fail, error/warning counts, and overall verdict.


## CLI Usage

```bash
# Account sync with mock broker
python scripts/run_account_sync.py --broker mock --mode live-readonly

# Sync from a saved broker snapshot
python scripts/run_account_sync.py --broker file --snapshot path/to/snapshot.json

# JSON output
python scripts/run_account_sync.py --broker mock --json

# Readiness checks only (skip broker sync)
python scripts/run_account_sync.py --readiness-only --mode live-readonly

# With approval verification
python scripts/run_account_sync.py --approval-dir artifacts/runs/2025-06-01/run_id/

# Verbose logging
python scripts/run_account_sync.py -v
```


## Artifact Output

```
artifacts/
  live_readiness/
    2025-06-01/
      account_snapshot.json
      reconciliation_report.json
      readiness_report.json
```


## What Passed

All 87 Step 12 tests pass deterministically:

- Broker read-only contract: write methods raise NotImplementedError
- Mock adapter: cash, positions, prices, orders, fills, snapshots
- File adapter: JSON loading, reference prices
- Reconciliation: full match, cash mismatch, share mismatch, missing positions
- Intent feasibility: sell with no position, buy with insufficient cash, order conflicts
- Approval state machine: create, approve, reject, expire, persistence
- Live-readiness checks: all 7 checks with pass and fail cases
- Environment configs: live_readonly, live_disabled, demo/paper unchanged
- No live order path: all adapters block submit/cancel/modify


## What Remains Before Real Live Execution

1. **Real broker adapter**: Connect to an actual broker API (e.g., IBKR, Alpaca). The `BrokerInterface` contract is ready.

2. **Order routing**: A future step must explicitly implement `submit_order` in a live adapter. This is intentionally gated.

3. **Position synchronization**: Currently reconciliation is a point-in-time comparison. Continuous sync with event-driven updates would be needed for production.

4. **Risk limits**: Pre-trade checks could be extended with position-level risk limits, sector exposure caps, and drawdown triggers.

5. **Monitoring/alerting**: Production would need real-time monitoring of reconciliation drift, approval expiry, and sync failures.

6. **Multi-account support**: Current model is single-account. Production may need multi-account or sub-account support.


## Hard Constraints Maintained

- No live order placement
- No broker write access
- Write methods raise NotImplementedError unconditionally
- Approval required in live-readiness mode
- Demo and paper environments unchanged
- Decision engine unchanged
- No new alpha logic
- No weakened guardrails
