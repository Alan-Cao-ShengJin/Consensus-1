"""Hardened approval model with state machine, expiry, and audit trail.

Extends the basic approval gate from run_manager with:
  - State machine: PENDING -> APPROVED / REJECTED / EXPIRED
  - Approver identity and timestamp capture
  - Expiry: approvals become stale after a configurable window
  - Rejection with reason
  - Full audit trail in approval artifact
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Approval states
# ---------------------------------------------------------------------------

class HardenedApprovalStatus:
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"

    VALID = frozenset({PENDING, APPROVED, REJECTED, EXPIRED})
    TERMINAL = frozenset({APPROVED, REJECTED, EXPIRED})


# ---------------------------------------------------------------------------
# Approval record
# ---------------------------------------------------------------------------

@dataclass
class ApprovalRecord:
    """Full approval state with audit trail."""
    batch_id: str
    status: str = HardenedApprovalStatus.PENDING
    created_at: str = ""
    updated_at: str = ""
    expires_at: Optional[str] = None
    approver_id: Optional[str] = None
    approver_name: Optional[str] = None
    rejection_reason: Optional[str] = None
    environment: str = ""
    run_id: str = ""
    intents_count: int = 0
    notes: list[str] = field(default_factory=list)

    def __post_init__(self):
        now = datetime.utcnow().isoformat()
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now

    @property
    def is_terminal(self) -> bool:
        return self.status in HardenedApprovalStatus.TERMINAL

    @property
    def is_approved(self) -> bool:
        return self.status == HardenedApprovalStatus.APPROVED

    @property
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        try:
            exp = datetime.fromisoformat(self.expires_at)
            return datetime.utcnow() > exp
        except (ValueError, TypeError):
            return False

    def to_dict(self) -> dict:
        return {
            "batch_id": self.batch_id,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "expires_at": self.expires_at,
            "approver_id": self.approver_id,
            "approver_name": self.approver_name,
            "rejection_reason": self.rejection_reason,
            "environment": self.environment,
            "run_id": self.run_id,
            "intents_count": self.intents_count,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, d: dict) -> ApprovalRecord:
        return cls(
            batch_id=d["batch_id"],
            status=d.get("status", HardenedApprovalStatus.PENDING),
            created_at=d.get("created_at", ""),
            updated_at=d.get("updated_at", ""),
            expires_at=d.get("expires_at"),
            approver_id=d.get("approver_id"),
            approver_name=d.get("approver_name"),
            rejection_reason=d.get("rejection_reason"),
            environment=d.get("environment", ""),
            run_id=d.get("run_id", ""),
            intents_count=d.get("intents_count", 0),
            notes=d.get("notes", []),
        )


# ---------------------------------------------------------------------------
# Default expiry window
# ---------------------------------------------------------------------------

DEFAULT_EXPIRY_HOURS = 24


# ---------------------------------------------------------------------------
# State machine transitions
# ---------------------------------------------------------------------------

def create_approval(
    batch_id: str,
    run_id: str = "",
    environment: str = "",
    intents_count: int = 0,
    expiry_hours: int = DEFAULT_EXPIRY_HOURS,
) -> ApprovalRecord:
    """Create a new pending approval record."""
    now = datetime.utcnow()
    return ApprovalRecord(
        batch_id=batch_id,
        status=HardenedApprovalStatus.PENDING,
        created_at=now.isoformat(),
        updated_at=now.isoformat(),
        expires_at=(now + timedelta(hours=expiry_hours)).isoformat(),
        environment=environment,
        run_id=run_id,
        intents_count=intents_count,
    )


def approve(
    record: ApprovalRecord,
    approver_id: str,
    approver_name: str = "",
    notes: str = "",
) -> ApprovalRecord:
    """Transition approval from PENDING to APPROVED.

    Raises ValueError if not in PENDING state or if expired.
    """
    _check_expiry(record)

    if record.status != HardenedApprovalStatus.PENDING:
        raise ValueError(
            f"Cannot approve batch {record.batch_id}: "
            f"current status is {record.status}, expected PENDING"
        )

    record.status = HardenedApprovalStatus.APPROVED
    record.updated_at = datetime.utcnow().isoformat()
    record.approver_id = approver_id
    record.approver_name = approver_name
    if notes:
        record.notes.append(notes)
    return record


def reject(
    record: ApprovalRecord,
    approver_id: str,
    reason: str,
    approver_name: str = "",
) -> ApprovalRecord:
    """Transition approval from PENDING to REJECTED.

    Raises ValueError if not in PENDING state.
    """
    if record.status != HardenedApprovalStatus.PENDING:
        raise ValueError(
            f"Cannot reject batch {record.batch_id}: "
            f"current status is {record.status}, expected PENDING"
        )

    record.status = HardenedApprovalStatus.REJECTED
    record.updated_at = datetime.utcnow().isoformat()
    record.approver_id = approver_id
    record.approver_name = approver_name
    record.rejection_reason = reason
    return record


def check_and_expire(record: ApprovalRecord) -> ApprovalRecord:
    """If PENDING and past expiry, transition to EXPIRED."""
    if record.status == HardenedApprovalStatus.PENDING and record.is_expired:
        record.status = HardenedApprovalStatus.EXPIRED
        record.updated_at = datetime.utcnow().isoformat()
        record.notes.append("Auto-expired: past expiry window")
    return record


def _check_expiry(record: ApprovalRecord) -> None:
    """Raise if record is expired."""
    if record.status == HardenedApprovalStatus.PENDING and record.is_expired:
        record.status = HardenedApprovalStatus.EXPIRED
        record.updated_at = datetime.utcnow().isoformat()
        record.notes.append("Auto-expired: past expiry window")
        raise ValueError(
            f"Approval for batch {record.batch_id} has expired "
            f"(expiry was {record.expires_at})"
        )


# ---------------------------------------------------------------------------
# Persistence (file-based, like existing approval gate)
# ---------------------------------------------------------------------------

def _approval_path(artifact_dir: str) -> str:
    return os.path.join(artifact_dir, "approval_hardened.json")


def save_approval(record: ApprovalRecord, artifact_dir: str) -> str:
    """Save approval record to artifact directory. Returns file path."""
    os.makedirs(artifact_dir, exist_ok=True)
    path = _approval_path(artifact_dir)
    with open(path, "w") as f:
        json.dump(record.to_dict(), f, indent=2)
    return path


def load_approval(artifact_dir: str) -> Optional[ApprovalRecord]:
    """Load approval record from artifact directory."""
    path = _approval_path(artifact_dir)
    if not os.path.exists(path):
        return None
    with open(path, "r") as f:
        data = json.load(f)
    return ApprovalRecord.from_dict(data)


def approve_batch_hardened(
    artifact_dir: str,
    batch_id: str,
    approver_id: str,
    approver_name: str = "",
) -> ApprovalRecord:
    """Load, approve, and save approval record.

    Raises ValueError on batch_id mismatch, wrong state, or expiry.
    """
    record = load_approval(artifact_dir)
    if record is None:
        raise ValueError(f"No approval record found in {artifact_dir}")
    if record.batch_id != batch_id:
        raise ValueError(
            f"Batch ID mismatch: expected {record.batch_id}, got {batch_id}"
        )
    approve(record, approver_id=approver_id, approver_name=approver_name)
    save_approval(record, artifact_dir)
    return record


def reject_batch_hardened(
    artifact_dir: str,
    batch_id: str,
    approver_id: str,
    reason: str,
    approver_name: str = "",
) -> ApprovalRecord:
    """Load, reject, and save approval record."""
    record = load_approval(artifact_dir)
    if record is None:
        raise ValueError(f"No approval record found in {artifact_dir}")
    if record.batch_id != batch_id:
        raise ValueError(
            f"Batch ID mismatch: expected {record.batch_id}, got {batch_id}"
        )
    reject(record, approver_id=approver_id, reason=reason, approver_name=approver_name)
    save_approval(record, artifact_dir)
    return record
