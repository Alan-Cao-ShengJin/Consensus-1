"""Run manager: orchestrate the end-to-end operating cycle.

Coordinates: ingestion -> thesis update -> portfolio review ->
execution intent generation -> guardrail validation -> optional paper execution
-> artifact export -> run summary.

Does not reimplement business logic. Orchestrates existing modules.

Key features:
  - Run lifecycle (STARTED -> COMPLETED / FAILED / PARTIAL)
  - Idempotency / duplicate-run protection
  - Failure handling with stage-level recovery
  - Human approval hooks
  - Environment separation (demo / paper / live)
  - Structured logging and artifact manifests
"""
from __future__ import annotations

import json
import logging
import os
import traceback
import uuid
from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from typing import Optional

from config import SystemConfig, Environment

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Run lifecycle
# ---------------------------------------------------------------------------

class RunStatus:
    STARTED = "STARTED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    PARTIAL = "PARTIAL"
    SKIPPED = "SKIPPED"


class StageStatus:
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class ApprovalStatus:
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    NOT_REQUIRED = "NOT_REQUIRED"


# ---------------------------------------------------------------------------
# Stage result
# ---------------------------------------------------------------------------

@dataclass
class StageResult:
    """Result of executing one pipeline stage."""
    stage: str
    status: str = StageStatus.PENDING
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    counts: dict = field(default_factory=dict)
    artifacts: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error: Optional[str] = None
    error_traceback: Optional[str] = None

    def mark_started(self):
        self.status = StageStatus.RUNNING
        self.started_at = datetime.utcnow().isoformat()

    def mark_completed(self):
        self.status = StageStatus.COMPLETED
        self.ended_at = datetime.utcnow().isoformat()

    def mark_failed(self, error: str, tb: Optional[str] = None):
        self.status = StageStatus.FAILED
        self.ended_at = datetime.utcnow().isoformat()
        self.error = error
        self.error_traceback = tb

    def mark_skipped(self, reason: str = ""):
        self.status = StageStatus.SKIPPED
        self.ended_at = datetime.utcnow().isoformat()
        if reason:
            self.warnings.append(f"Skipped: {reason}")


# ---------------------------------------------------------------------------
# Run manifest
# ---------------------------------------------------------------------------

@dataclass
class RunManifest:
    """Complete manifest for a system run."""
    run_id: str
    environment: str
    run_date: str
    started_at: str
    ended_at: Optional[str] = None
    status: str = RunStatus.STARTED
    config_snapshot: dict = field(default_factory=dict)
    stages: dict[str, StageResult] = field(default_factory=dict)
    artifact_dir: Optional[str] = None
    error_summary: Optional[str] = None
    warnings: list[str] = field(default_factory=list)
    approval_status: str = ApprovalStatus.NOT_REQUIRED
    batch_id: Optional[str] = None

    def to_dict(self) -> dict:
        d = {
            "run_id": self.run_id,
            "environment": self.environment,
            "run_date": self.run_date,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "status": self.status,
            "config_snapshot": self.config_snapshot,
            "artifact_dir": self.artifact_dir,
            "error_summary": self.error_summary,
            "warnings": self.warnings,
            "approval_status": self.approval_status,
            "batch_id": self.batch_id,
            "stages": {},
        }
        for name, sr in self.stages.items():
            d["stages"][name] = asdict(sr)
        return d

    def save(self, path: str):
        """Save manifest to JSON file."""
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def load(cls, path: str) -> RunManifest:
        """Load manifest from JSON file."""
        with open(path, "r") as f:
            d = json.load(f)
        manifest = cls(
            run_id=d["run_id"],
            environment=d["environment"],
            run_date=d["run_date"],
            started_at=d["started_at"],
            ended_at=d.get("ended_at"),
            status=d.get("status", RunStatus.STARTED),
            config_snapshot=d.get("config_snapshot", {}),
            artifact_dir=d.get("artifact_dir"),
            error_summary=d.get("error_summary"),
            warnings=d.get("warnings", []),
            approval_status=d.get("approval_status", ApprovalStatus.NOT_REQUIRED),
            batch_id=d.get("batch_id"),
        )
        for name, sr_dict in d.get("stages", {}).items():
            manifest.stages[name] = StageResult(**sr_dict)
        return manifest


# ---------------------------------------------------------------------------
# Idempotency: duplicate-run detection
# ---------------------------------------------------------------------------

def _find_existing_manifests(artifact_base: str, run_date: str) -> list[str]:
    """Find all manifest files for a given date."""
    date_dir = os.path.join(artifact_base, run_date)
    if not os.path.isdir(date_dir):
        return []
    manifests = []
    for run_dir in sorted(os.listdir(date_dir)):
        manifest_path = os.path.join(date_dir, run_dir, "run_manifest.json")
        if os.path.exists(manifest_path):
            manifests.append(manifest_path)
    return manifests


def check_duplicate_run(
    artifact_base: str,
    run_date: str,
    config: SystemConfig,
) -> Optional[RunManifest]:
    """Check if a completed run already exists for this date and config.

    Returns the existing manifest if a duplicate is found, None otherwise.
    """
    for path in _find_existing_manifests(artifact_base, run_date):
        try:
            manifest = RunManifest.load(path)
            if manifest.status == RunStatus.COMPLETED:
                if manifest.environment == config.environment:
                    return manifest
        except Exception:
            continue
    return None


def check_batch_already_executed(
    artifact_base: str,
    run_date: str,
    review_date: str,
) -> bool:
    """Check if paper execution has already been applied for a review date."""
    for path in _find_existing_manifests(artifact_base, run_date):
        try:
            manifest = RunManifest.load(path)
            paper_stage = manifest.stages.get("paper_execution")
            if paper_stage and paper_stage.status == StageStatus.COMPLETED:
                return True
        except Exception:
            continue
    return False


# ---------------------------------------------------------------------------
# Approval gate
# ---------------------------------------------------------------------------

def _approval_file_path(artifact_dir: str) -> str:
    return os.path.join(artifact_dir, "approval_status.json")


def save_approval_state(artifact_dir: str, status: str, batch_id: str):
    """Save approval state to the run's artifact directory."""
    os.makedirs(artifact_dir, exist_ok=True)
    state = {
        "batch_id": batch_id,
        "status": status,
        "updated_at": datetime.utcnow().isoformat(),
    }
    with open(_approval_file_path(artifact_dir), "w") as f:
        json.dump(state, f, indent=2)


def load_approval_state(artifact_dir: str) -> Optional[dict]:
    """Load approval state from the run's artifact directory."""
    path = _approval_file_path(artifact_dir)
    if not os.path.exists(path):
        return None
    with open(path, "r") as f:
        return json.load(f)


def approve_batch(artifact_dir: str, batch_id: str) -> bool:
    """Approve a pending batch for paper execution.

    Returns True if approval was successful, False if batch_id mismatch.
    """
    state = load_approval_state(artifact_dir)
    if state is None:
        return False
    if state.get("batch_id") != batch_id:
        return False
    save_approval_state(artifact_dir, ApprovalStatus.APPROVED, batch_id)
    return True


# ---------------------------------------------------------------------------
# Run manager: main orchestration
# ---------------------------------------------------------------------------

class RunManager:
    """Orchestrate a full system cycle.

    Usage:
        manager = RunManager(config)
        manifest = manager.run()
    """

    STAGES = [
        "ingestion",
        "review",
        "execution_intents",
        "guardrail_validation",
        "paper_execution",
        "artifact_export",
    ]

    def __init__(self, config: SystemConfig, run_date: Optional[date] = None, force: bool = False):
        self.config = config
        self.run_date = run_date or date.today()
        self.force = force
        self.run_id = f"{self.run_date.isoformat()}_{uuid.uuid4().hex[:8]}"
        self.artifact_dir = os.path.join(
            config.artifact_base_dir,
            self.run_date.isoformat(),
            self.run_id,
        )
        self.manifest = RunManifest(
            run_id=self.run_id,
            environment=config.environment,
            run_date=self.run_date.isoformat(),
            started_at=datetime.utcnow().isoformat(),
            config_snapshot=config.to_dict(),
            artifact_dir=self.artifact_dir,
        )
        # Initialize stage results
        for stage in self.STAGES:
            self.manifest.stages[stage] = StageResult(stage=stage)

        # Internal state passed between stages
        self._ingestion_summaries = []
        self._review_result = None
        self._review_id = None
        self._execution_batch = None
        self._validation_result = None
        self._paper_summary = None

    def run(self, resume_from: Optional[str] = None) -> RunManifest:
        """Execute the full pipeline.

        Args:
            resume_from: If set, skip stages before this one (for recovery).
        """
        logger.info(
            "=== System cycle START: run_id=%s env=%s date=%s ===",
            self.run_id, self.config.environment, self.run_date,
        )

        # Duplicate-run check
        if not self.config.dry_run and not self.force:
            existing = check_duplicate_run(
                self.config.artifact_base_dir,
                self.run_date.isoformat(),
                self.config,
            )
            if existing:
                logger.warning(
                    "Duplicate run detected: %s (status=%s). Use --force to override.",
                    existing.run_id, existing.status,
                )
                self.manifest.status = RunStatus.SKIPPED
                self.manifest.error_summary = f"Duplicate of completed run {existing.run_id}"
                self.manifest.ended_at = datetime.utcnow().isoformat()
                return self.manifest

        # Determine which stages to run
        skip_until_found = resume_from is not None
        any_failed = False
        any_completed = False

        for stage_name in self.STAGES:
            if skip_until_found:
                if stage_name == resume_from:
                    skip_until_found = False
                else:
                    self.manifest.stages[stage_name].mark_skipped("resumed past this stage")
                    continue

            if any_failed:
                self.manifest.stages[stage_name].mark_skipped("prior stage failed")
                continue

            try:
                self._run_stage(stage_name)
                if self.manifest.stages[stage_name].status == StageStatus.COMPLETED:
                    any_completed = True
                elif self.manifest.stages[stage_name].status == StageStatus.FAILED:
                    any_failed = True
            except Exception as e:
                tb = traceback.format_exc()
                self.manifest.stages[stage_name].mark_failed(str(e), tb)
                logger.error("Stage %s failed: %s", stage_name, e)
                any_failed = True

        # Determine overall status
        if any_failed and any_completed:
            self.manifest.status = RunStatus.PARTIAL
            self.manifest.error_summary = "Some stages failed"
        elif any_failed:
            self.manifest.status = RunStatus.FAILED
            failed_stages = [
                s for s, sr in self.manifest.stages.items()
                if sr.status == StageStatus.FAILED
            ]
            self.manifest.error_summary = f"Failed at: {', '.join(failed_stages)}"
        else:
            self.manifest.status = RunStatus.COMPLETED

        self.manifest.ended_at = datetime.utcnow().isoformat()

        # Save manifest
        if not self.config.dry_run:
            manifest_path = os.path.join(self.artifact_dir, "run_manifest.json")
            self.manifest.save(manifest_path)
            logger.info("Manifest saved: %s", manifest_path)

        logger.info(
            "=== System cycle END: run_id=%s status=%s ===",
            self.run_id, self.manifest.status,
        )
        return self.manifest

    # -----------------------------------------------------------------------
    # Stage dispatch
    # -----------------------------------------------------------------------

    def _run_stage(self, stage_name: str):
        dispatch = {
            "ingestion": self._stage_ingestion,
            "review": self._stage_review,
            "execution_intents": self._stage_execution_intents,
            "guardrail_validation": self._stage_guardrail_validation,
            "paper_execution": self._stage_paper_execution,
            "artifact_export": self._stage_artifact_export,
        }
        handler = dispatch.get(stage_name)
        if handler:
            handler()

    # -----------------------------------------------------------------------
    # Stage: Ingestion
    # -----------------------------------------------------------------------

    def _stage_ingestion(self):
        sr = self.manifest.stages["ingestion"]
        sr.mark_started()
        logger.info("--- Stage: ingestion ---")

        if self.config.environment == Environment.DEMO:
            sr.mark_skipped("demo mode — no ingestion")
            return

        if not self.config.tickers:
            sr.mark_skipped("no tickers configured")
            return

        from db import get_session
        from pipeline_runner import run_ticker_pipeline

        total_docs = 0
        total_claims = 0
        total_errors = []

        with get_session() as session:
            for ticker in self.config.tickers:
                logger.info("Ingesting %s", ticker)
                try:
                    summary = run_ticker_pipeline(
                        session,
                        ticker,
                        days=self.config.ingestion_days,
                        dry_run=self.config.dry_run,
                        source_filter=self.config.source_filter,
                        use_llm=self.config.use_llm,
                    )
                    self._ingestion_summaries.append(summary)
                    total_docs += summary.total_docs_inserted
                    total_claims += summary.total_claims_extracted
                    if summary.errors:
                        total_errors.extend(summary.errors)
                except Exception as e:
                    logger.error("Ingestion failed for %s: %s", ticker, e)
                    total_errors.append(f"{ticker}: {e}")

        sr.counts = {
            "tickers_processed": len(self.config.tickers),
            "docs_inserted": total_docs,
            "claims_extracted": total_claims,
            "errors": len(total_errors),
        }
        if total_errors:
            sr.warnings.extend(total_errors)

        sr.mark_completed()
        logger.info(
            "Ingestion complete: %d tickers, %d docs, %d claims",
            len(self.config.tickers), total_docs, total_claims,
        )

    # -----------------------------------------------------------------------
    # Stage: Portfolio Review
    # -----------------------------------------------------------------------

    def _stage_review(self):
        sr = self.manifest.stages["review"]
        sr.mark_started()
        logger.info("--- Stage: review ---")

        if self.config.environment == Environment.DEMO:
            self._build_demo_review()
            sr.counts = {
                "decisions": len(self._review_result.decisions) if self._review_result else 0,
            }
            sr.mark_completed()
            return

        from db import get_session
        from portfolio_review_service import run_portfolio_review

        with get_session() as session:
            result = run_portfolio_review(
                session,
                as_of=self.run_date,
                review_type=self.config.review_type,
                persist=self.config.review_persist and not self.config.dry_run,
            )
            self._review_result = result

            # Get review_id from the DB if persisted
            if self.config.review_persist and not self.config.dry_run:
                from sqlalchemy import select
                from models import PortfolioReview
                latest = session.execute(
                    select(PortfolioReview)
                    .order_by(PortfolioReview.id.desc())
                    .limit(1)
                ).scalar_one_or_none()
                if latest:
                    self._review_id = latest.id

        sr.counts = {
            "decisions": len(result.decisions),
            "initiations": len(result.initiations),
            "adds": len(result.adds),
            "trims": len(result.trims),
            "exits": len(result.exits),
            "holds": len(result.holds),
            "probations": len(result.probations),
        }
        sr.mark_completed()
        logger.info(
            "Review complete: %d decisions",
            len(result.decisions),
        )

    # -----------------------------------------------------------------------
    # Stage: Execution Intents
    # -----------------------------------------------------------------------

    def _stage_execution_intents(self):
        sr = self.manifest.stages["execution_intents"]
        sr.mark_started()
        logger.info("--- Stage: execution_intents ---")

        if self._review_result is None:
            sr.mark_skipped("no review result available")
            return

        from execution_wrapper import build_execution_batch

        current_weights = self._get_current_weights()
        reference_prices = self._get_reference_prices()

        batch = build_execution_batch(
            review_result=self._review_result,
            current_weights=current_weights,
            portfolio_value=self.config.portfolio_value,
            reference_prices=reference_prices,
            review_id=self._review_id,
            dry_run=self.config.dry_run,
            paper_trade=(self.config.environment == Environment.PAPER),
        )
        self._execution_batch = batch

        # Generate batch_id for approval tracking
        batch_id = f"batch_{self.run_id}"
        self.manifest.batch_id = batch_id

        sr.counts = {
            "order_intents": len(batch.order_intents),
            "skipped_non_trading": len(batch.skipped_non_trading),
            "skipped_blocked": len(batch.skipped_blocked),
        }
        sr.mark_completed()
        logger.info(
            "Execution intents: %d orders, %d skipped",
            len(batch.order_intents),
            len(batch.skipped_non_trading) + len(batch.skipped_blocked),
        )

    # -----------------------------------------------------------------------
    # Stage: Guardrail Validation
    # -----------------------------------------------------------------------

    def _stage_guardrail_validation(self):
        sr = self.manifest.stages["guardrail_validation"]
        sr.mark_started()
        logger.info("--- Stage: guardrail_validation ---")

        if self._execution_batch is None:
            sr.mark_skipped("no execution batch available")
            return

        from execution_guardrails import validate_execution_batch
        from execution_policy import ExecutionPolicyConfig

        policy = ExecutionPolicyConfig(
            max_single_position_weight_pct=self.config.max_position_weight_pct,
            max_gross_exposure_pct=self.config.max_gross_exposure_pct,
            max_weekly_turnover_pct=self.config.weekly_turnover_cap_pct,
            transaction_cost_bps=self.config.transaction_cost_bps,
        )

        current_weights = self._get_current_weights()
        validation = validate_execution_batch(
            batch=self._execution_batch,
            current_weights=current_weights,
            config=policy,
        )
        self._validation_result = validation

        sr.counts = {
            "approved": len(validation.approved_intents),
            "blocked": len(validation.blocked_intents),
            "batch_violations": len(validation.batch_violations),
            "all_passed": validation.all_passed,
        }
        if validation.batch_violations:
            sr.warnings.extend(validation.batch_violations)

        sr.mark_completed()
        logger.info(
            "Guardrails: %d approved, %d blocked",
            len(validation.approved_intents),
            len(validation.blocked_intents),
        )

    # -----------------------------------------------------------------------
    # Stage: Paper Execution
    # -----------------------------------------------------------------------

    def _stage_paper_execution(self):
        sr = self.manifest.stages["paper_execution"]
        sr.mark_started()
        logger.info("--- Stage: paper_execution ---")

        if self._validation_result is None:
            sr.mark_skipped("no validation result available")
            return

        if not self.config.paper_execute:
            sr.mark_skipped("paper execution not requested")
            return

        if self.config.dry_run:
            sr.mark_skipped("dry-run mode — no paper execution")
            return

        # Duplicate batch execution check
        if check_batch_already_executed(
            self.config.artifact_base_dir,
            self.run_date.isoformat(),
            self._execution_batch.review_date if self._execution_batch else "",
        ):
            sr.mark_skipped("batch already executed for this date")
            sr.warnings.append("Duplicate batch execution prevented")
            return

        # Approval gate
        if self.config.require_approval:
            batch_id = self.manifest.batch_id or f"batch_{self.run_id}"
            # Save pending approval state
            save_approval_state(
                self.artifact_dir,
                ApprovalStatus.PENDING_APPROVAL,
                batch_id,
            )
            self.manifest.approval_status = ApprovalStatus.PENDING_APPROVAL

            # Check if already approved
            state = load_approval_state(self.artifact_dir)
            if state and state.get("status") != ApprovalStatus.APPROVED:
                sr.mark_skipped("awaiting human approval")
                sr.warnings.append(
                    f"Batch {batch_id} requires approval. "
                    f"Use --approve-batch {batch_id} to approve."
                )
                return

            self.manifest.approval_status = ApprovalStatus.APPROVED

        from paper_execution_engine import (
            PaperPortfolio, paper_execute,
        )
        from execution_policy import ExecutionPolicyConfig

        policy = ExecutionPolicyConfig(
            transaction_cost_bps=self.config.transaction_cost_bps,
        )

        portfolio = PaperPortfolio(
            initial_cash=self.config.portfolio_value,
            transaction_cost_bps=self.config.transaction_cost_bps,
        )

        reference_prices = self._get_reference_prices()
        current_weights = self._get_current_weights()

        # Seed existing positions
        for ticker, weight in current_weights.items():
            if weight > 0 and ticker in reference_prices:
                notional = (weight / 100.0) * self.config.portfolio_value
                shares = notional / reference_prices[ticker]
                portfolio.execute_buy(
                    ticker=ticker,
                    shares=shares,
                    price=reference_prices[ticker],
                    action_type="seed",
                    trade_date=self.run_date,
                )

        # Reset cash for seeded positions
        portfolio.cash = self.config.portfolio_value - sum(
            (w / 100.0) * self.config.portfolio_value
            for w in current_weights.values() if w > 0
        )

        summary = paper_execute(
            portfolio=portfolio,
            approved_intents=self._validation_result.approved_intents,
            blocked_intents=self._validation_result.blocked_intents,
            execution_date=self.run_date,
            fill_prices=reference_prices,
            config=policy,
        )
        self._paper_summary = summary

        sr.counts = {
            "fills_executed": summary.fills_executed,
            "total_buy_notional": round(summary.total_buy_notional, 2),
            "total_sell_notional": round(summary.total_sell_notional, 2),
            "total_transaction_cost": round(summary.total_transaction_cost, 2),
        }
        sr.mark_completed()
        logger.info(
            "Paper execution: %d fills, buy=$%.2f, sell=$%.2f",
            summary.fills_executed,
            summary.total_buy_notional,
            summary.total_sell_notional,
        )

    # -----------------------------------------------------------------------
    # Stage: Artifact Export
    # -----------------------------------------------------------------------

    def _stage_artifact_export(self):
        sr = self.manifest.stages["artifact_export"]
        sr.mark_started()
        logger.info("--- Stage: artifact_export ---")

        if self.config.dry_run:
            sr.mark_skipped("dry-run mode — no artifact export")
            return

        os.makedirs(self.artifact_dir, exist_ok=True)
        exported_files = []

        # Save config snapshot
        config_path = os.path.join(self.artifact_dir, "config.json")
        with open(config_path, "w") as f:
            json.dump(self.config.to_dict(), f, indent=2)
        exported_files.append(config_path)

        # Save execution batch
        if self._execution_batch:
            batch_path = os.path.join(self.artifact_dir, "order_intents.json")
            with open(batch_path, "w") as f:
                json.dump(self._execution_batch.to_dict(), f, indent=2)
            exported_files.append(batch_path)

        # Save validation result
        if self._validation_result:
            val_path = os.path.join(self.artifact_dir, "validation_result.json")
            with open(val_path, "w") as f:
                json.dump(self._validation_result.to_dict(), f, indent=2)
            exported_files.append(val_path)

        # Save paper execution summary
        if self._paper_summary:
            summary_path = os.path.join(self.artifact_dir, "paper_execution_summary.json")
            with open(summary_path, "w") as f:
                json.dump(self._paper_summary.to_dict(), f, indent=2)
            exported_files.append(summary_path)

            # Save portfolio snapshot
            if self._paper_summary.portfolio_snapshot:
                snap_path = os.path.join(self.artifact_dir, "portfolio_snapshot.json")
                with open(snap_path, "w") as f:
                    json.dump(self._paper_summary.portfolio_snapshot.to_dict(), f, indent=2)
                exported_files.append(snap_path)

            # Save paper fills
            fills_path = os.path.join(self.artifact_dir, "paper_fills.json")
            with open(fills_path, "w") as f:
                json.dump([fill.to_dict() for fill in self._paper_summary.fills], f, indent=2)
            exported_files.append(fills_path)

        # Save ingestion summaries
        if self._ingestion_summaries:
            ing_path = os.path.join(self.artifact_dir, "ingestion_summaries.json")
            with open(ing_path, "w") as f:
                json.dump([s.to_dict() for s in self._ingestion_summaries], f, indent=2)
            exported_files.append(ing_path)

        sr.counts = {"files_exported": len(exported_files)}
        sr.artifacts = exported_files
        sr.mark_completed()
        logger.info("Artifacts exported: %d files to %s", len(exported_files), self.artifact_dir)

    # -----------------------------------------------------------------------
    # Helpers: current weights and reference prices
    # -----------------------------------------------------------------------

    def _get_current_weights(self) -> dict[str, float]:
        """Get current portfolio weights. Demo uses synthetic data."""
        if self.config.environment == Environment.DEMO:
            return self._demo_weights

        from db import get_session
        from sqlalchemy import select
        from models import PortfolioPosition, PositionStatus

        with get_session() as session:
            positions = session.scalars(
                select(PortfolioPosition)
                .where(PortfolioPosition.status == PositionStatus.ACTIVE)
            ).all()
            return {p.ticker: p.current_weight for p in positions}

    def _get_reference_prices(self) -> dict[str, float]:
        """Get reference prices. Demo uses synthetic data."""
        if self.config.environment == Environment.DEMO:
            return self._demo_prices

        from db import get_session
        from sqlalchemy import select
        from models import Price

        prices = {}
        with get_session() as session:
            tickers = set()
            if self._review_result:
                tickers = {d.ticker for d in self._review_result.decisions}
            for ticker in tickers:
                row = session.scalars(
                    select(Price.close)
                    .where(Price.ticker == ticker, Price.date <= self.run_date)
                    .order_by(Price.date.desc())
                    .limit(1)
                ).first()
                if row:
                    prices[ticker] = row
                else:
                    prices[ticker] = 100.0  # fallback
        return prices

    # -----------------------------------------------------------------------
    # Demo mode helpers
    # -----------------------------------------------------------------------

    _demo_weights: dict[str, float] = {}
    _demo_prices: dict[str, float] = {}

    def _build_demo_review(self):
        """Build synthetic review data for demo mode."""
        from models import ActionType
        from portfolio_decision_engine import (
            TickerDecision, PortfolioReviewResult, ReasonCode,
            PRIORITY_FORCED_EXIT, PRIORITY_DEFENSIVE,
            PRIORITY_GROWTH, PRIORITY_NEUTRAL,
        )

        decisions = [
            TickerDecision(
                ticker="BRKN", action=ActionType.EXIT, action_score=100.0,
                recommendation_priority=PRIORITY_FORCED_EXIT,
                target_weight_change=-5.0, suggested_weight=0.0,
                reason_codes=[ReasonCode.THESIS_BROKEN],
                rationale="Thesis broken — forced exit",
            ),
            TickerDecision(
                ticker="STRCH", action=ActionType.TRIM, action_score=70.0,
                recommendation_priority=PRIORITY_DEFENSIVE,
                target_weight_change=-2.0, suggested_weight=4.0,
                reason_codes=[ReasonCode.VALUATION_STRETCHED],
                rationale="Valuation stretched — trim",
            ),
            TickerDecision(
                ticker="NEWCO", action=ActionType.INITIATE, action_score=65.0,
                recommendation_priority=PRIORITY_GROWTH,
                target_weight_change=3.0, suggested_weight=3.0,
                reason_codes=[ReasonCode.VALUATION_ATTRACTIVE, ReasonCode.SUFFICIENT_NOVEL_EVIDENCE],
                rationale="All entry gates passed — initiate",
            ),
            TickerDecision(
                ticker="WINR", action=ActionType.ADD, action_score=55.0,
                recommendation_priority=PRIORITY_GROWTH,
                target_weight_change=1.5, suggested_weight=6.5,
                reason_codes=[ReasonCode.ADD_TO_WINNER, ReasonCode.VALUATION_ATTRACTIVE],
                rationale="Winner with strong conviction — add",
            ),
            TickerDecision(
                ticker="STDY", action=ActionType.HOLD, action_score=0.0,
                recommendation_priority=PRIORITY_NEUTRAL,
                reason_codes=[ReasonCode.VALUATION_NEUTRAL],
                rationale="Hold — thesis stable",
            ),
        ]

        self._review_result = PortfolioReviewResult(
            review_date=self.run_date,
            decisions=decisions,
            turnover_pct_planned=11.5,
            turnover_pct_cap=20.0,
        )

        self._demo_weights = {
            "BRKN": 5.0, "STRCH": 6.0, "WINR": 5.0, "STDY": 4.0,
        }
        self._demo_prices = {
            "BRKN": 45.0, "STRCH": 120.0, "NEWCO": 85.0,
            "WINR": 200.0, "STDY": 150.0,
        }


# ---------------------------------------------------------------------------
# Convenience: run a full cycle
# ---------------------------------------------------------------------------

def run_system_cycle(
    config: SystemConfig,
    run_date: Optional[date] = None,
    resume_from: Optional[str] = None,
    force: bool = False,
) -> RunManifest:
    """Run a full system cycle.

    Args:
        config: System configuration.
        run_date: Date for this run (default: today).
        resume_from: Stage name to resume from (for recovery).
        force: If True, skip duplicate-run check.
    """
    manager = RunManager(config, run_date=run_date, force=force)
    return manager.run(resume_from=resume_from)
