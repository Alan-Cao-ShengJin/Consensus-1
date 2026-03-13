"""Historical evaluation config: bounded configuration for historical proof runs.

Supports:
- Universe selection (full or subset)
- Date range for backfill and evaluation
- Source toggles (which connectors to use)
- Backfill-only vs full regeneration vs evaluate-only modes
- Rebuild from scratch vs incremental continuation
- Forward-return measurement horizons
- Memory ablation toggle
- Deterministic run ID and output paths
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional


class HistoricalRunMode:
    """Run mode constants."""
    BACKFILL_ONLY = "backfill_only"          # fetch historical data, no thesis regeneration
    REGENERATE = "regenerate"                 # backfill + thesis regeneration + evaluation
    EVALUATE_ONLY = "evaluate_only"           # evaluate on existing regenerated state
    MEMORY_ABLATION = "memory_ablation"       # run regeneration twice: memory ON vs OFF


@dataclass
class HistoricalEvalConfig:
    """Configuration for a historical proof run.

    All fields have sensible defaults for a bounded, repeatable run.
    """
    # --- Run identity ---
    run_id: str = "historical_default"
    run_label: str = ""

    # --- Mode ---
    mode: str = HistoricalRunMode.REGENERATE

    # --- Universe ---
    tickers: list[str] = field(default_factory=list)  # empty = full UNIVERSE_TICKERS

    # --- Date range ---
    backfill_start: date = date(2024, 1, 1)
    backfill_end: date = date(2025, 1, 1)
    eval_start: date = date(2024, 3, 1)       # evaluation starts after backfill warmup
    eval_end: date = date(2025, 1, 1)

    # --- Review cadence ---
    cadence_days: int = 7                       # weekly review

    # --- Source toggles ---
    backfill_prices: bool = True
    backfill_sec_filings: bool = True
    backfill_news_rss: bool = True
    backfill_pr_rss: bool = True

    # --- Thesis regeneration ---
    rebuild_from_scratch: bool = True           # True = clean DB, False = incremental
    use_llm: bool = False                       # stub mode by default

    # --- Portfolio ---
    initial_cash: float = 1_000_000.0
    transaction_cost_bps: float = 10.0
    apply_trades: bool = True
    strict_replay: bool = False

    # --- Forward-return horizons ---
    forward_return_days: list[int] = field(default_factory=lambda: [5, 20, 60])

    # --- Conviction buckets ---
    conviction_buckets: list[tuple[float, float, str]] = field(
        default_factory=lambda: [
            (0, 40, "low"),
            (40, 65, "medium"),
            (65, 100, "high"),
        ]
    )

    # --- Memory ablation ---
    memory_enabled: bool = True

    # --- Benchmark ---
    benchmark_ticker: str = "SPY"
    include_equal_weight_baseline: bool = True

    # --- Output ---
    output_dir: str = "historical_proof_runs"

    # --- Determinism ---
    seed: int = 42

    def effective_tickers(self) -> list[str]:
        """Return the ticker list to use, falling back to full universe."""
        if self.tickers:
            return list(self.tickers)
        from source_registry import UNIVERSE_TICKERS
        return list(UNIVERSE_TICKERS)

    def conviction_bucket_for(self, score: float) -> str:
        """Return the bucket label for a conviction score."""
        for low, high, label in self.conviction_buckets:
            if low <= score < high:
                return label
        return "high"  # scores at 100

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "run_label": self.run_label,
            "mode": self.mode,
            "tickers": self.effective_tickers(),
            "backfill_start": self.backfill_start.isoformat(),
            "backfill_end": self.backfill_end.isoformat(),
            "eval_start": self.eval_start.isoformat(),
            "eval_end": self.eval_end.isoformat(),
            "cadence_days": self.cadence_days,
            "backfill_prices": self.backfill_prices,
            "backfill_sec_filings": self.backfill_sec_filings,
            "backfill_news_rss": self.backfill_news_rss,
            "backfill_pr_rss": self.backfill_pr_rss,
            "rebuild_from_scratch": self.rebuild_from_scratch,
            "use_llm": self.use_llm,
            "initial_cash": self.initial_cash,
            "transaction_cost_bps": self.transaction_cost_bps,
            "strict_replay": self.strict_replay,
            "forward_return_days": self.forward_return_days,
            "memory_enabled": self.memory_enabled,
            "benchmark_ticker": self.benchmark_ticker,
            "output_dir": self.output_dir,
            "seed": self.seed,
        }

    @staticmethod
    def memory_ablation_pair(
        *,
        tickers: list[str] | None = None,
        backfill_start: date = date(2024, 1, 1),
        backfill_end: date = date(2025, 1, 1),
        eval_start: date = date(2024, 3, 1),
        eval_end: date = date(2025, 1, 1),
        cadence_days: int = 7,
    ) -> tuple[HistoricalEvalConfig, HistoricalEvalConfig]:
        """Create matched pair for memory-on vs memory-off historical ablation."""
        base = dict(
            tickers=tickers or [],
            backfill_start=backfill_start,
            backfill_end=backfill_end,
            eval_start=eval_start,
            eval_end=eval_end,
            cadence_days=cadence_days,
            mode=HistoricalRunMode.MEMORY_ABLATION,
        )
        config_on = HistoricalEvalConfig(
            run_id="historical_memory_on",
            run_label="Historical regeneration: memory ON",
            memory_enabled=True,
            **base,
        )
        config_off = HistoricalEvalConfig(
            run_id="historical_memory_off",
            run_label="Historical regeneration: memory OFF",
            memory_enabled=False,
            **base,
        )
        return config_on, config_off
