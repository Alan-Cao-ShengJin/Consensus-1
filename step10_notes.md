# Step 10: Production Hardening & Operating Layer

## What Step 10 Adds

Step 10 turns the system from a working research/decision machine into a robust operating system that can run repeatedly, safely, and auditably. This is operational hardening — not new alpha logic, not live broker connectivity, not Graphiti.

### New files

| File | Purpose |
|------|---------|
| `config.py` | Central configuration: environment, universe, review cadence, execution policy, artifact paths, approval settings |
| `run_manager.py` | Run orchestration: lifecycle management, idempotency, failure handling, approval gates, artifact manifests |
| `scripts/run_system_cycle.py` | CLI entrypoint for production-style cycles |
| `tests/test_step10.py` | 40+ tests covering all Step 10 requirements |


## Run Lifecycle

Each system cycle follows a defined stage pipeline:

```
INGESTION → REVIEW → EXECUTION_INTENTS → GUARDRAIL_VALIDATION → PAPER_EXECUTION → ARTIFACT_EXPORT
```

### Stage statuses

| Status | Meaning |
|--------|---------|
| `PENDING` | Not yet started |
| `RUNNING` | Currently executing |
| `COMPLETED` | Finished successfully |
| `FAILED` | Error occurred |
| `SKIPPED` | Intentionally not run |

### Run statuses

| Status | Meaning |
|--------|---------|
| `STARTED` | Run in progress |
| `COMPLETED` | All stages passed |
| `FAILED` | A stage failed, no stages completed after |
| `PARTIAL` | Some stages completed, some failed |
| `SKIPPED` | Run not executed (e.g., duplicate detected) |

### Run metadata

Each run tracks:
- `run_id` (date + random suffix for uniqueness)
- Stage-level start/end timestamps
- Config snapshot (frozen at run start)
- Per-stage counts (docs, claims, decisions, orders, fills)
- Error summaries with tracebacks
- Artifact file locations
- Approval status


## Idempotency Rules

### Duplicate-run detection
- Before each run, the system checks `artifacts/<date>/*/run_manifest.json` for an existing COMPLETED run with the same environment.
- If found, the run is SKIPPED with a "Duplicate" message.
- Use `--force` to bypass this check.

### Ingestion deduplication
- The existing `is_duplicate_document()` in `dedupe.py` prevents re-inserting the same document.
- Claims are extracted only from newly inserted documents.
- Thesis updates only fire if there are net-new claims.

### Execution batch deduplication
- `check_batch_already_executed()` checks if paper execution has already completed for a given date.
- A second paper execution for the same review date is blocked unless `--force` is used.

### Paper fill deduplication
- Paper execution only runs if:
  1. `--paper-execute` flag is set
  2. No duplicate batch exists for this date
  3. Approval gate is satisfied (if required)


## Failure / Recovery Behavior

### Per-stage failure handling
- If a stage fails, the error and traceback are recorded in the stage result.
- Already-completed stages are preserved.
- Subsequent stages are SKIPPED (not attempted after a failure).
- The manifest is always saved, even on failure.

### Recovery
- Use `--resume-from <stage>` to restart from a specific stage.
- Earlier stages are SKIPPED when resuming.
- The system creates a new run_id for the recovery attempt.

### Stage-specific behavior

| Stage | On failure |
|-------|-----------|
| Ingestion | Per-ticker errors are recorded; other tickers continue |
| Review | Run halts; no intents generated |
| Execution intents | Run halts; no validation |
| Guardrail validation | Run halts; no paper execution |
| Paper execution | Run halts; intents/validation already saved |
| Artifact export | Run ends PARTIAL; earlier data preserved in memory |


## Approval Model

### When `require_approval=True`:
1. The pipeline runs through guardrail validation
2. Paper execution is SKIPPED with status `PENDING_APPROVAL`
3. An `approval_status.json` file is written to the artifact directory
4. A human reviews the order intents and validation results
5. `python scripts/run_system_cycle.py --approve-batch <batch_id>` marks the batch as APPROVED
6. Re-running the pipeline will detect the approval and proceed with paper execution

### When `require_approval=False` (default):
- Paper execution runs immediately after guardrail validation
- No approval gate

### Approval file format
```json
{
  "batch_id": "batch_2025-10-01_abc12345",
  "status": "PENDING_APPROVAL",
  "updated_at": "2025-10-01T12:00:00"
}
```


## Environment Separation

| Environment | Behavior |
|-------------|----------|
| `demo` | Synthetic data, no DB access, no ingestion, safe for testing |
| `paper` | Real DB, paper fills only, no live trading |
| `live` | **Not implemented** — raises error immediately |

### How separation is enforced
- Config validation rejects `environment=live`
- All manifests record the environment
- Artifact directories are labeled with the environment in the config snapshot
- Demo mode uses synthetic TickerDecisions; paper mode reads from the real database


## Artifact Layout

```
artifacts/
  2025-10-01/
    2025-10-01_a1b2c3d4/
      run_manifest.json          # Full run metadata
      config.json                # Frozen config snapshot
      order_intents.json         # Execution batch
      validation_result.json     # Guardrail results
      paper_execution_summary.json  # Fill summary
      paper_fills.json           # Individual fills
      portfolio_snapshot.json    # Portfolio state after execution
      approval_status.json       # (if approval required)
      ingestion_summaries.json   # (if ingestion ran)
```


## Configuration

### Central config (`config.py`)

All tunable parameters in one place:

| Category | Parameters |
|----------|-----------|
| Environment | `environment` (demo/paper/live) |
| Universe | `tickers`, `source_filter` |
| Ingestion | `ingestion_days`, `use_llm` |
| Review | `review_type`, `review_persist` |
| Decision engine | conviction thresholds, position limits, turnover caps |
| Execution policy | initiation/add/trim sizing, transaction costs |
| Paper execution | `portfolio_value`, `paper_execute` |
| Approval | `require_approval` |
| Artifacts | `artifact_base_dir` |
| Flags | `dry_run` |

### Loading config
```python
# From defaults
config = get_default_config("paper")

# From file
config = SystemConfig.from_file("config.json")

# With overrides
config = config.merge({"tickers": ["NVDA"], "dry_run": True})
```

### JSON config file example
```json
{
  "environment": "paper",
  "tickers": ["NVDA", "MSFT", "AAPL"],
  "portfolio_value": 500000,
  "paper_execute": true,
  "require_approval": true,
  "transaction_cost_bps": 15.0
}
```


## CLI Usage

```bash
# Demo mode (synthetic data, no DB)
python scripts/run_system_cycle.py --demo

# Demo with paper execution
python scripts/run_system_cycle.py --demo --paper-execute

# Paper mode with specific tickers
python scripts/run_system_cycle.py --paper --tickers NVDA MSFT

# Paper mode with paper execution
python scripts/run_system_cycle.py --paper --paper-execute

# Dry run (no files, no DB writes)
python scripts/run_system_cycle.py --paper --dry-run

# With approval gate
python scripts/run_system_cycle.py --paper --paper-execute --require-approval

# Approve a pending batch
python scripts/run_system_cycle.py --approve-batch batch_2025-10-01_abc12345

# Resume from a specific stage
python scripts/run_system_cycle.py --paper --resume-from execution_intents

# Load config from file
python scripts/run_system_cycle.py --paper --config config.json

# JSON output
python scripts/run_system_cycle.py --demo --json
```


## What Still Remains Before Real-Money Deployment

1. **Real broker connectivity** — API integration for live order submission
2. **Fill confirmation loop** — poll/receive actual fills and reconcile vs intents
3. **Live portfolio state mutation** — update PortfolioPosition records after confirmed fills
4. **Slippage modeling** — market impact, limit orders, partial fills
5. **Scheduled execution** — cron/scheduler integration for automated weekly cycles
6. **Alerting** — notify on blocked orders, execution failures, or significant drift
7. **Multi-user approval** — role-based approval workflow
8. **Audit trail persistence** — DB-backed run records (currently file-based)
9. **Monitoring dashboard** — real-time visibility into system health
10. **Disaster recovery** — backup/restore procedures for portfolio state
