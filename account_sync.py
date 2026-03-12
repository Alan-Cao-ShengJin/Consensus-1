"""Account sync and reconciliation.

Pulls read-only broker/account state and reconciles it against internal
paper/live-intent expectations. Does not mutate broker state.

Produces reconciliation artifacts: matched positions, mismatches,
missing positions, cash differences, stale state warnings.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from broker_interface import AccountSnapshot, BrokerInterface

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Reconciliation data structures
# ---------------------------------------------------------------------------

@dataclass
class PositionDifference:
    """Difference between internal and broker position for one ticker."""
    ticker: str
    status: str  # "matched", "mismatch", "missing_internal", "missing_broker"
    internal_shares: Optional[float] = None
    broker_shares: Optional[float] = None
    shares_diff: Optional[float] = None
    internal_value: Optional[float] = None
    broker_value: Optional[float] = None
    value_diff: Optional[float] = None
    internal_weight: Optional[float] = None
    broker_weight: Optional[float] = None
    weight_diff: Optional[float] = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = {
            "ticker": self.ticker,
            "status": self.status,
            "notes": self.notes,
        }
        for f in ["internal_shares", "broker_shares", "shares_diff",
                   "internal_value", "broker_value", "value_diff",
                   "internal_weight", "broker_weight", "weight_diff"]:
            v = getattr(self, f)
            if v is not None:
                d[f] = round(v, 6)
        return d


@dataclass
class OrderConflict:
    """Potential conflict between a pending order and an intent."""
    ticker: str
    conflict_type: str  # "open_order_exists", "side_mismatch", etc.
    open_order_side: Optional[str] = None
    open_order_quantity: Optional[float] = None
    intent_side: Optional[str] = None
    intent_shares: Optional[float] = None
    message: str = ""

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "conflict_type": self.conflict_type,
            "open_order_side": self.open_order_side,
            "open_order_quantity": round(self.open_order_quantity, 6) if self.open_order_quantity else None,
            "intent_side": self.intent_side,
            "intent_shares": round(self.intent_shares, 6) if self.intent_shares else None,
            "message": self.message,
        }


@dataclass
class IntentFeasibility:
    """Feasibility check of a single intent against external state."""
    ticker: str
    action_type: str
    side: str
    feasible: bool = True
    issues: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "action_type": self.action_type,
            "side": self.side,
            "feasible": self.feasible,
            "issues": self.issues,
        }


@dataclass
class ReconciliationResult:
    """Full reconciliation output."""
    reconciled_at: str
    broker_name: str = ""
    account_id: str = ""

    # Cash
    internal_cash: Optional[float] = None
    broker_cash: Optional[float] = None
    cash_diff: Optional[float] = None
    cash_matched: bool = True

    # Positions
    position_diffs: list[PositionDifference] = field(default_factory=list)
    matched_count: int = 0
    mismatch_count: int = 0
    missing_internal_count: int = 0
    missing_broker_count: int = 0

    # Orders / conflicts
    order_conflicts: list[OrderConflict] = field(default_factory=list)

    # Intent feasibility
    intent_checks: list[IntentFeasibility] = field(default_factory=list)

    # Stale state warnings
    warnings: list[str] = field(default_factory=list)

    # Overall
    all_matched: bool = True
    unresolved_count: int = 0

    def to_dict(self) -> dict:
        return {
            "reconciled_at": self.reconciled_at,
            "broker_name": self.broker_name,
            "account_id": self.account_id,
            "cash": {
                "internal": round(self.internal_cash, 2) if self.internal_cash is not None else None,
                "broker": round(self.broker_cash, 2) if self.broker_cash is not None else None,
                "diff": round(self.cash_diff, 2) if self.cash_diff is not None else None,
                "matched": self.cash_matched,
            },
            "positions": {
                "matched": self.matched_count,
                "mismatches": self.mismatch_count,
                "missing_internal": self.missing_internal_count,
                "missing_broker": self.missing_broker_count,
                "details": [d.to_dict() for d in self.position_diffs],
            },
            "order_conflicts": [c.to_dict() for c in self.order_conflicts],
            "intent_feasibility": [i.to_dict() for i in self.intent_checks],
            "warnings": self.warnings,
            "all_matched": self.all_matched,
            "unresolved_count": self.unresolved_count,
        }


# ---------------------------------------------------------------------------
# Internal state representation (from paper portfolio or DB)
# ---------------------------------------------------------------------------

@dataclass
class InternalPosition:
    """Internal position state for reconciliation."""
    ticker: str
    shares: float
    market_value: float
    weight: float  # percentage


@dataclass
class InternalState:
    """Internal portfolio state for reconciliation."""
    cash: float
    total_value: float
    positions: list[InternalPosition] = field(default_factory=list)

    def get_position(self, ticker: str) -> Optional[InternalPosition]:
        for p in self.positions:
            if p.ticker == ticker:
                return p
        return None


# ---------------------------------------------------------------------------
# Core reconciliation
# ---------------------------------------------------------------------------

# Tolerance for considering values "matched"
CASH_TOLERANCE = 1.0  # $1
SHARES_TOLERANCE = 0.01  # 0.01 shares
WEIGHT_TOLERANCE = 0.5  # 0.5%


def reconcile(
    broker_snapshot: AccountSnapshot,
    internal_state: InternalState,
    order_intents: Optional[list] = None,
    cash_tolerance: float = CASH_TOLERANCE,
    shares_tolerance: float = SHARES_TOLERANCE,
) -> ReconciliationResult:
    """Reconcile broker account state against internal expectations.

    Args:
        broker_snapshot: Current broker account state
        internal_state: Internal portfolio state
        order_intents: Optional list of OrderIntent for feasibility checks
        cash_tolerance: Tolerance for cash matching ($)
        shares_tolerance: Tolerance for share count matching

    Returns:
        ReconciliationResult with full comparison
    """
    result = ReconciliationResult(
        reconciled_at=datetime.utcnow().isoformat(),
        broker_name=broker_snapshot.broker_name,
        account_id=broker_snapshot.account_id,
    )

    # --- Cash reconciliation ---
    result.internal_cash = internal_state.cash
    result.broker_cash = broker_snapshot.cash
    result.cash_diff = broker_snapshot.cash - internal_state.cash
    result.cash_matched = abs(result.cash_diff) <= cash_tolerance
    if not result.cash_matched:
        result.all_matched = False
        result.unresolved_count += 1

    # --- Position reconciliation ---
    broker_weights = broker_snapshot.get_weights()
    internal_tickers = {p.ticker for p in internal_state.positions}
    broker_tickers = {p.ticker for p in broker_snapshot.positions}
    all_tickers = internal_tickers | broker_tickers

    for ticker in sorted(all_tickers):
        int_pos = internal_state.get_position(ticker)
        brk_pos = broker_snapshot.get_position(ticker)

        if int_pos and brk_pos:
            # Both sides have this position
            shares_diff = brk_pos.shares - int_pos.shares
            value_diff = brk_pos.market_value - int_pos.market_value
            weight_diff = broker_weights.get(ticker, 0) - int_pos.weight

            if abs(shares_diff) <= shares_tolerance:
                diff = PositionDifference(
                    ticker=ticker, status="matched",
                    internal_shares=int_pos.shares,
                    broker_shares=brk_pos.shares,
                    shares_diff=shares_diff,
                    internal_value=int_pos.market_value,
                    broker_value=brk_pos.market_value,
                    value_diff=value_diff,
                    internal_weight=int_pos.weight,
                    broker_weight=broker_weights.get(ticker, 0),
                    weight_diff=weight_diff,
                )
                result.matched_count += 1
            else:
                notes = []
                if shares_diff > 0:
                    notes.append(f"Broker has {shares_diff:.2f} more shares")
                else:
                    notes.append(f"Internal has {-shares_diff:.2f} more shares")
                diff = PositionDifference(
                    ticker=ticker, status="mismatch",
                    internal_shares=int_pos.shares,
                    broker_shares=brk_pos.shares,
                    shares_diff=shares_diff,
                    internal_value=int_pos.market_value,
                    broker_value=brk_pos.market_value,
                    value_diff=value_diff,
                    internal_weight=int_pos.weight,
                    broker_weight=broker_weights.get(ticker, 0),
                    weight_diff=weight_diff,
                    notes=notes,
                )
                result.mismatch_count += 1
                result.all_matched = False
                result.unresolved_count += 1

            result.position_diffs.append(diff)

        elif int_pos and not brk_pos:
            # Internal has it, broker doesn't
            diff = PositionDifference(
                ticker=ticker, status="missing_broker",
                internal_shares=int_pos.shares,
                internal_value=int_pos.market_value,
                internal_weight=int_pos.weight,
                notes=["Position exists internally but not at broker"],
            )
            result.position_diffs.append(diff)
            result.missing_broker_count += 1
            result.all_matched = False
            result.unresolved_count += 1

        elif brk_pos and not int_pos:
            # Broker has it, internal doesn't
            diff = PositionDifference(
                ticker=ticker, status="missing_internal",
                broker_shares=brk_pos.shares,
                broker_value=brk_pos.market_value,
                broker_weight=broker_weights.get(ticker, 0),
                notes=["Position exists at broker but not internally"],
            )
            result.position_diffs.append(diff)
            result.missing_internal_count += 1
            result.all_matched = False
            result.unresolved_count += 1

    # --- Open order conflicts ---
    if order_intents:
        _check_order_conflicts(result, broker_snapshot, order_intents)
        _check_intent_feasibility(result, broker_snapshot, internal_state, order_intents)

    return result


def _check_order_conflicts(
    result: ReconciliationResult,
    snapshot: AccountSnapshot,
    intents: list,
) -> None:
    """Check for conflicts between open orders and new intents."""
    open_order_tickers = {}
    for o in snapshot.open_orders:
        if o.status == "open":
            open_order_tickers.setdefault(o.ticker, []).append(o)

    for intent in intents:
        ticker = intent.ticker
        if ticker in open_order_tickers:
            for existing in open_order_tickers[ticker]:
                conflict_type = "open_order_exists"
                if existing.side != intent.side:
                    conflict_type = "side_mismatch"

                result.order_conflicts.append(OrderConflict(
                    ticker=ticker,
                    conflict_type=conflict_type,
                    open_order_side=existing.side,
                    open_order_quantity=existing.quantity,
                    intent_side=intent.side,
                    intent_shares=intent.estimated_shares,
                    message=(
                        f"Open {existing.side} order for {existing.quantity} shares "
                        f"conflicts with {intent.side} intent"
                    ),
                ))
                result.all_matched = False
                result.unresolved_count += 1


def _check_intent_feasibility(
    result: ReconciliationResult,
    snapshot: AccountSnapshot,
    internal_state: InternalState,
    intents: list,
) -> None:
    """Check each intent against external account state."""
    for intent in intents:
        ticker = intent.ticker
        check = IntentFeasibility(
            ticker=ticker,
            action_type=str(intent.action_type) if hasattr(intent, 'action_type') else "",
            side=intent.side,
        )

        # Sell intent but broker has no position
        if intent.side == "sell":
            brk_pos = snapshot.get_position(ticker)
            if brk_pos is None:
                check.feasible = False
                check.issues.append("Broker shows no position to sell")
            elif intent.estimated_shares and brk_pos.shares < intent.estimated_shares:
                check.feasible = False
                check.issues.append(
                    f"Broker has {brk_pos.shares:.2f} shares, "
                    f"intent wants to sell {intent.estimated_shares:.2f}"
                )

        # Buy intent but insufficient cash
        if intent.side == "buy" and intent.notional_delta:
            if snapshot.cash < intent.notional_delta:
                check.feasible = False
                check.issues.append(
                    f"Broker cash ${snapshot.cash:.2f} < "
                    f"intent notional ${intent.notional_delta:.2f}"
                )

        # Internal vs broker position divergence
        int_pos = internal_state.get_position(ticker)
        brk_pos = snapshot.get_position(ticker)
        if int_pos and brk_pos:
            if abs(brk_pos.shares - int_pos.shares) > SHARES_TOLERANCE:
                check.issues.append(
                    f"Internal/broker share mismatch: "
                    f"{int_pos.shares:.2f} vs {brk_pos.shares:.2f}"
                )

        result.intent_checks.append(check)


# ---------------------------------------------------------------------------
# Sync and export
# ---------------------------------------------------------------------------

def run_account_sync(
    broker: BrokerInterface,
    internal_state: InternalState,
    order_intents: Optional[list] = None,
    output_dir: Optional[str] = None,
) -> ReconciliationResult:
    """Run full account sync: fetch broker state, reconcile, optionally export.

    Args:
        broker: Broker adapter (read-only)
        internal_state: Internal portfolio expectations
        order_intents: Optional intents for feasibility checks
        output_dir: If set, exports reconciliation artifacts

    Returns:
        ReconciliationResult
    """
    logger.info("Starting account sync...")

    # Fetch broker state
    snapshot = broker.get_account_snapshot()
    logger.info(
        "Broker snapshot: cash=$%.2f equity=$%.2f positions=%d",
        snapshot.cash, snapshot.total_equity, snapshot.position_count,
    )

    # Reconcile
    result = reconcile(snapshot, internal_state, order_intents)
    logger.info(
        "Reconciliation: matched=%d mismatches=%d missing_internal=%d missing_broker=%d",
        result.matched_count, result.mismatch_count,
        result.missing_internal_count, result.missing_broker_count,
    )

    # Export artifacts
    if output_dir:
        export_reconciliation(result, snapshot, output_dir)

    return result


def export_reconciliation(
    result: ReconciliationResult,
    snapshot: AccountSnapshot,
    output_dir: str,
) -> dict[str, str]:
    """Export reconciliation and snapshot artifacts to disk.

    Returns dict of {type: path}.
    """
    os.makedirs(output_dir, exist_ok=True)
    paths = {}

    # Account snapshot
    snap_path = os.path.join(output_dir, "account_snapshot.json")
    with open(snap_path, "w") as f:
        json.dump(snapshot.to_dict(), f, indent=2)
    paths["account_snapshot"] = snap_path

    # Reconciliation report
    recon_path = os.path.join(output_dir, "reconciliation_report.json")
    with open(recon_path, "w") as f:
        json.dump(result.to_dict(), f, indent=2)
    paths["reconciliation_report"] = recon_path

    logger.info("Reconciliation artifacts exported to %s", output_dir)
    return paths


# ---------------------------------------------------------------------------
# Text formatting
# ---------------------------------------------------------------------------

def format_reconciliation_text(result: ReconciliationResult) -> str:
    """Format reconciliation result as human-readable text."""
    lines = []
    lines.append("=" * 60)
    lines.append("ACCOUNT RECONCILIATION REPORT")
    lines.append("=" * 60)
    lines.append(f"Reconciled at: {result.reconciled_at}")
    lines.append(f"Broker: {result.broker_name} ({result.account_id})")
    lines.append("")

    verdict = "ALL MATCHED" if result.all_matched else f"UNRESOLVED: {result.unresolved_count}"
    lines.append(f"Overall: {verdict}")
    lines.append("")

    # Cash
    lines.append("--- Cash ---")
    if result.internal_cash is not None:
        lines.append(f"  Internal: ${result.internal_cash:,.2f}")
    if result.broker_cash is not None:
        lines.append(f"  Broker:   ${result.broker_cash:,.2f}")
    if result.cash_diff is not None:
        lines.append(f"  Diff:     ${result.cash_diff:,.2f} {'MATCH' if result.cash_matched else 'MISMATCH'}")
    lines.append("")

    # Positions
    lines.append("--- Positions ---")
    lines.append(f"  Matched:          {result.matched_count}")
    lines.append(f"  Mismatches:       {result.mismatch_count}")
    lines.append(f"  Missing internal: {result.missing_internal_count}")
    lines.append(f"  Missing broker:   {result.missing_broker_count}")
    lines.append("")

    for d in result.position_diffs:
        status_label = d.status.upper()
        line = f"  [{status_label}] {d.ticker}"
        if d.broker_shares is not None and d.internal_shares is not None:
            line += f" — broker: {d.broker_shares:.2f} / internal: {d.internal_shares:.2f}"
        elif d.broker_shares is not None:
            line += f" — broker: {d.broker_shares:.2f} / internal: N/A"
        elif d.internal_shares is not None:
            line += f" — broker: N/A / internal: {d.internal_shares:.2f}"
        lines.append(line)
        for n in d.notes:
            lines.append(f"    {n}")

    if result.order_conflicts:
        lines.append("")
        lines.append("--- Order Conflicts ---")
        for c in result.order_conflicts:
            lines.append(f"  [{c.conflict_type}] {c.ticker}: {c.message}")

    if result.intent_checks:
        lines.append("")
        lines.append("--- Intent Feasibility ---")
        for ic in result.intent_checks:
            status = "OK" if ic.feasible else "ISSUE"
            lines.append(f"  [{status}] {ic.ticker} ({ic.side})")
            for issue in ic.issues:
                lines.append(f"    {issue}")

    if result.warnings:
        lines.append("")
        lines.append("--- Warnings ---")
        for w in result.warnings:
            lines.append(f"  {w}")

    lines.append("")
    lines.append("=" * 60)
    return "\n".join(lines)
