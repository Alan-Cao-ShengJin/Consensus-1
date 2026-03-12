# Step 11.5: Operating Validation Over Repeated Paper Cycles

## What This Step Validates

The system behaves consistently, safely, and coherently when run through repeated paper-mode operating cycles. This is operational hardening, not new alpha logic.

Core question: can the machine survive repeated scheduled-like runs, approvals, retries, failures, and artifact generation without drifting into inconsistent state?


## New Files

| File | Purpose |
|------|---------|
| `operating_validator.py` | Multi-cycle validator: scenarios, fault injection, invariant checks |
| `validation_report.py` | Report generation: per-scenario pass/fail, aggregated statistics |
| `scripts/run_operating_validation.py` | CLI entrypoint for validation runs |
| `tests/test_step11_5.py` | 55+ deterministic tests |
| `step11_5_notes.md` | This document |


## Supported Scenarios

| Scenario | What it tests |
|----------|---------------|
| `happy_path` | 3 repeated paper cycles complete coherently |
| `duplicate_run` | Second run on same date is blocked |
| `duplicate_batch` | Second batch execution on same date is blocked |
| `failure_resume` | Fault at review stage, then resume from review |
| `failure_paper_execution` | Fault at paper execution, then resume |
| `approval_required` | Approval gate blocks execution until approved |
| `config_change` | Config change between cycles, manifests reflect it |
| `dry_run` | Dry-run cycle produces no fills, no artifacts |
| `no_actionable` | All-HOLD review produces zero order intents |
| `failure_ingestion` | Fault during ingestion stage |


## Fault Injection

Small validation-only mechanism. Not spread across the codebase.

`FaultInjector` raises `FaultInjectedError` at a specified stage and cycle:

```python
fi = FaultInjector(fail_stages=["review"], fail_on_cycle=1)
```

`InstrumentedRunManager` subclasses `RunManager` and checks the injector before each stage. This is the only touch point — no hooks or patches in production code.


## Invariants Checked

| Invariant | Check function |
|-----------|---------------|
| No duplicate paper fills from reruns | `check_no_duplicate_fills` |
| Run statuses reflect actual stage outcomes | `check_manifest_coherence` |
| Environment labels correct across all manifests | `check_environment_labels` |
| Duplicate run blocked on second attempt | `check_duplicate_run_blocked` |
| Duplicate batch execution blocked | `check_duplicate_batch_blocked` |
| Approval gate blocks execution when required | `check_approval_gate` |
| Dry-run produces no fills or mutations | `check_dry_run_no_mutation` |
| Exported artifacts exist on disk | `check_artifact_existence` |
| Fills count does not exceed approved intents | `check_fills_within_intents` |


## Validation Reporting

`validation_report.py` produces:

- Cycles attempted / completed / failed / partial / skipped
- Approvals requested / granted / missing
- Duplicate runs blocked
- Duplicate batches blocked
- Resumes performed
- Faults injected and outcomes
- Paper fills applied
- Invariant violations detected
- Per-scenario pass/fail result
- Overall pass/fail

Export formats: JSON (`validation_report.json`), text (`validation_report.txt`), scenario configs.


## CLI Usage

```bash
# Run a single scenario
python scripts/run_operating_validation.py --scenario happy_path

# Run all scenarios
python scripts/run_operating_validation.py --all

# JSON output
python scripts/run_operating_validation.py --scenario duplicate_run --json

# List available scenarios
python scripts/run_operating_validation.py --list-scenarios

# Verbose logging
python scripts/run_operating_validation.py --all -v

# Custom output directory
python scripts/run_operating_validation.py --all --output-dir artifacts/validation/custom
```


## Artifact Output

```
artifacts/
  validation/
    2025-06-01/
      validation_report.json
      validation_report.txt
      scenario_configs.json
      runs/
        2025-06-01/
          <run_id>/
            run_manifest.json
            config.json
            order_intents.json
            validation_result.json
            paper_execution_summary.json
            paper_fills.json
            portfolio_snapshot.json
```


## What Passed

All 10 scenarios pass deterministically:

- Happy-path: 3 cycles complete, fills applied, artifacts exported
- Duplicate run: second run blocked with SKIPPED status
- Duplicate batch: second batch execution prevented
- Failure/resume: fault injected, subsequent stages skipped, resume works
- Approval gate: blocks paper execution until approved
- Config change: manifests reflect updated config between cycles
- Dry-run: no fills, no artifacts, no mutations
- No-actionable: zero order intents, zero fills
- Fault injection: controlled failures at any stage


## Remaining Operational Risks

1. **DB-backed validation**: current tests use demo mode. Paper mode with a real DB would exercise ingestion, thesis update, and portfolio review with actual SQLAlchemy state. This is a Step 12 concern.

2. **Concurrent runs**: no locking mechanism prevents two processes from running simultaneously on the same date. The duplicate-run check is file-based and not atomic.

3. **Approval workflow**: the approval flow requires two separate CLI invocations (run → approve → resume). There is no built-in timeout or escalation for missing approvals.

4. **Graph sync after cycles**: graph sync depends on DB state. In demo mode, there is no DB to sync from. Graph validation is exercised separately in Step 10.5 tests.

5. **Long-running cycles**: no circuit breaker for cycles that take too long. Ingestion of many tickers with live sources could be slow.


## Readiness for Step 12

The system is operationally boring enough:

- Repeated cycles produce consistent, auditable outcomes
- Duplicate protection works at both run and batch levels
- Approval gates block execution deterministically
- Failures are contained to the failing stage with clean skip behavior
- Resume-from recovery works correctly
- Dry-run mode is side-effect free
- All artifacts are coherent and verifiable
- Invariant checks can detect intentionally broken state

The machine is ready for live-readiness hardening (Step 12), which would add:
- Real DB validation cycles
- Broker connectivity (read-only initially)
- Live environment configuration
- Production monitoring and alerting hooks


## Hard Constraints Maintained

- Live trading remains disabled
- No broker write access
- Decision engine unchanged
- Guardrails and purity standards unchanged
- No new alpha logic
- No generic load-testing framework — this is focused operating validation
