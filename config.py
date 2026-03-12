"""Central configuration for the Consensus system.

All tunable parameters live here. No scattered magic numbers.
Supports loading from YAML/JSON config files with environment-aware defaults.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field, asdict
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Environment enum
# ---------------------------------------------------------------------------

class Environment:
    DEMO = "demo"
    PAPER = "paper"
    LIVE = "live"
    LIVE_READONLY = "live_readonly"
    LIVE_DISABLED = "live_disabled"

    VALID = frozenset({DEMO, PAPER, LIVE, LIVE_READONLY, LIVE_DISABLED})


# ---------------------------------------------------------------------------
# System configuration
# ---------------------------------------------------------------------------

@dataclass
class SystemConfig:
    """Top-level configuration for a Consensus system run."""

    # --- Environment ---
    environment: str = Environment.PAPER

    # --- Universe ---
    tickers: list[str] = field(default_factory=list)

    # --- Ingestion ---
    ingestion_days: int = 7
    source_filter: Optional[list[str]] = None
    use_llm: bool = False

    # --- Review ---
    review_type: str = "weekly"
    review_persist: bool = True

    # --- Decision engine ---
    initiation_conviction_floor: float = 55.0
    exit_conviction_ceiling: float = 25.0
    probation_conviction_ceiling: float = 35.0
    max_position_weight_pct: float = 10.0
    weekly_turnover_cap_pct: float = 20.0

    # --- Execution policy ---
    default_initiation_weight_pct: float = 3.0
    min_initiation_weight_pct: float = 2.0
    max_initiation_weight_pct: float = 5.0
    default_add_increment_pct: float = 1.5
    default_trim_decrement_pct: float = 2.0
    trim_floor_weight_pct: float = 1.0
    max_gross_exposure_pct: float = 100.0
    transaction_cost_bps: float = 10.0

    # --- Paper execution ---
    portfolio_value: float = 1_000_000.0
    paper_execute: bool = False

    # --- Approval ---
    require_approval: bool = False

    # --- Artifacts ---
    artifact_base_dir: str = "artifacts"

    # --- Dry run ---
    dry_run: bool = False

    # --- Database ---
    database_url: str = ""

    def __post_init__(self):
        if self.environment not in Environment.VALID:
            raise ValueError(
                f"Invalid environment '{self.environment}'. "
                f"Must be one of: {', '.join(sorted(Environment.VALID))}"
            )
        if self.environment == Environment.LIVE:
            raise ValueError(
                "LIVE environment is not implemented. "
                "Use 'live_readonly' for read-only broker sync, "
                "or 'live_disabled' as a protective default."
            )
        if not self.database_url:
            self.database_url = os.getenv("DATABASE_URL", "sqlite:///consensus.db")

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> SystemConfig:
        """Create config from a dictionary, ignoring unknown keys."""
        valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in d.items() if k in valid_fields}
        return cls(**filtered)

    @classmethod
    def from_file(cls, path: str) -> SystemConfig:
        """Load config from a JSON or YAML file."""
        if not os.path.exists(path):
            raise FileNotFoundError(f"Config file not found: {path}")

        with open(path, "r") as f:
            if path.endswith((".yaml", ".yml")):
                try:
                    import yaml
                    data = yaml.safe_load(f)
                except ImportError:
                    raise ImportError("PyYAML is required for YAML config files")
            else:
                data = json.load(f)

        logger.info("Loaded config from %s", path)
        return cls.from_dict(data)

    def merge(self, overrides: dict) -> SystemConfig:
        """Return a new config with overrides applied."""
        base = self.to_dict()
        base.update({k: v for k, v in overrides.items() if v is not None})
        return SystemConfig.from_dict(base)


# ---------------------------------------------------------------------------
# Default configs per environment
# ---------------------------------------------------------------------------

DEMO_CONFIG = SystemConfig(
    environment=Environment.DEMO,
    dry_run=True,
    require_approval=False,
    paper_execute=False,
)

PAPER_CONFIG = SystemConfig(
    environment=Environment.PAPER,
    dry_run=False,
    require_approval=False,
    paper_execute=True,
)

LIVE_READONLY_CONFIG = SystemConfig(
    environment=Environment.LIVE_READONLY,
    dry_run=False,
    require_approval=True,
    paper_execute=False,
)

LIVE_DISABLED_CONFIG = SystemConfig(
    environment=Environment.LIVE_DISABLED,
    dry_run=True,
    require_approval=True,
    paper_execute=False,
)


def get_default_config(environment: str) -> SystemConfig:
    """Get the default configuration for an environment."""
    if environment == Environment.DEMO:
        return SystemConfig.from_dict(DEMO_CONFIG.to_dict())
    elif environment == Environment.PAPER:
        return SystemConfig.from_dict(PAPER_CONFIG.to_dict())
    elif environment == Environment.LIVE_READONLY:
        return SystemConfig.from_dict(LIVE_READONLY_CONFIG.to_dict())
    elif environment == Environment.LIVE_DISABLED:
        return SystemConfig.from_dict(LIVE_DISABLED_CONFIG.to_dict())
    elif environment == Environment.LIVE:
        raise ValueError("LIVE environment is not implemented.")
    else:
        raise ValueError(f"Unknown environment: {environment}")
