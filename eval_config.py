"""Evaluation configuration: repeatable experiment definitions.

Supports ablation modes (memory ON/OFF, strict/non-strict, evidence features),
date ranges, benchmark selection, and run identifiers for reproducibility.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional


@dataclass
class EvalConfig:
    """Configuration for a single evaluation run.

    All fields have sensible defaults. Override to create ablation experiments.
    """
    # --- Run identity ---
    run_id: str = "default"
    run_label: str = ""  # human-readable label for reports

    # --- Date range ---
    start_date: date = date(2025, 1, 1)
    end_date: date = date(2025, 12, 31)
    cadence_days: int = 7

    # --- Portfolio ---
    initial_cash: float = 1_000_000.0
    transaction_cost_bps: float = 10.0
    apply_trades: bool = True

    # --- Replay mode ---
    strict_replay: bool = False

    # --- Memory ablation ---
    memory_enabled: bool = True  # False = bypass memory retrieval in thesis updates

    # --- Evidence feature ablation ---
    contradiction_metadata_enabled: bool = True  # False = ignore contradiction flags
    evidence_downweighting_enabled: bool = True   # False = all evidence weight = 1.0

    # --- Benchmark ---
    benchmark_ticker: str = "SPY"  # benchmark index for comparison
    include_equal_weight_baseline: bool = True  # compare vs equal-weight universe

    # --- Ticker filter ---
    ticker_filter: Optional[str] = None

    # --- Determinism ---
    seed: int = 42  # for any stochastic components (currently unused but reserved)

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "run_label": self.run_label,
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "cadence_days": self.cadence_days,
            "initial_cash": self.initial_cash,
            "transaction_cost_bps": self.transaction_cost_bps,
            "apply_trades": self.apply_trades,
            "strict_replay": self.strict_replay,
            "memory_enabled": self.memory_enabled,
            "contradiction_metadata_enabled": self.contradiction_metadata_enabled,
            "evidence_downweighting_enabled": self.evidence_downweighting_enabled,
            "benchmark_ticker": self.benchmark_ticker,
            "include_equal_weight_baseline": self.include_equal_weight_baseline,
            "ticker_filter": self.ticker_filter,
            "seed": self.seed,
        }

    @staticmethod
    def memory_comparison_pair(
        *,
        start_date: date = date(2025, 1, 1),
        end_date: date = date(2025, 12, 31),
        cadence_days: int = 7,
        initial_cash: float = 1_000_000.0,
        strict_replay: bool = False,
    ) -> tuple[EvalConfig, EvalConfig]:
        """Create a matched pair of configs for memory-vs-no-memory comparison."""
        base = dict(
            start_date=start_date,
            end_date=end_date,
            cadence_days=cadence_days,
            initial_cash=initial_cash,
            strict_replay=strict_replay,
        )
        memory_on = EvalConfig(
            run_id="memory_on",
            run_label="Memory enabled (standard)",
            memory_enabled=True,
            **base,
        )
        memory_off = EvalConfig(
            run_id="memory_off",
            run_label="Memory disabled (ablation)",
            memory_enabled=False,
            **base,
        )
        return memory_on, memory_off
