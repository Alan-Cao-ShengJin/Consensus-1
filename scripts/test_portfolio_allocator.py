"""Test portfolio allocator with real prices/PE + fake convictions.

Loads S&P 500 data from FMP (universe_v1_data.json), generates
random conviction scores, and runs through the allocator to verify
the system works end-to-end without LLM.
"""
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from portfolio_allocator import (
    TickerSignal,
    Position,
    ProfitTarget,
    compute_target_weights,
    decide_actions,
    upside_score,
    CONVICTION_FULL_ELIGIBLE,
    CONVICTION_EXIT,
    MAX_POSITION_PCT,
)

_BACKTEST_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backtests")


def load_universe():
    """Load real price/PE data for S&P 500."""
    with open(os.path.join(_BACKTEST_DIR, "universe_v1_data.json"), "r") as f:
        data = json.load(f)
    return data


def generate_fake_convictions(tickers, seed=42):
    """Generate fake conviction scores with realistic distribution.

    - ~20% high conviction (70-95)
    - ~30% moderate (45-70)
    - ~30% low (20-45)
    - ~20% very low (0-20)
    """
    random.seed(seed)
    convictions = {}
    for t in tickers:
        r = random.random()
        if r < 0.20:
            convictions[t] = random.uniform(70, 95)
        elif r < 0.50:
            convictions[t] = random.uniform(45, 70)
        elif r < 0.80:
            convictions[t] = random.uniform(20, 45)
        else:
            convictions[t] = random.uniform(0, 20)
    return convictions


def compute_pe_stats(universe):
    """Compute simple PE stats per sector for z-score calculation.

    In production this uses 5yr historical PE with distortion detection.
    For testing, use sector median as proxy for mean.
    """
    import numpy as np

    # Group PEs by sector
    sector_pes = {}
    for item in universe:
        sector = item.get("sector", "Unknown")
        pe = item["fwd_pe"]
        if 0 < pe < 200:  # filter outliers
            sector_pes.setdefault(sector, []).append(pe)

    # Compute sector stats
    sector_stats = {}
    for sector, pes in sector_pes.items():
        arr = np.array(pes)
        sector_stats[sector] = {
            "mean": float(np.mean(arr)),
            "std": float(np.std(arr)),
            "median": float(np.median(arr)),
        }

    return sector_stats


def main():
    print("Loading universe data...")
    universe = load_universe()
    print(f"Loaded {len(universe)} tickers with real prices and forward PE")

    # Generate fake convictions
    tickers = [item["ticker"] for item in universe]
    convictions = generate_fake_convictions(tickers)

    # Compute PE stats by sector (proxy for historical mean/std)
    import numpy as np
    sector_stats = compute_pe_stats(universe)

    print(f"\nSector PE stats:")
    for sector in sorted(sector_stats.keys()):
        s = sector_stats[sector]
        print(f"  {sector:<30s} mean={s['mean']:5.1f}x  std={s['std']:5.1f}x  median={s['median']:5.1f}x")

    # Build signals
    signals = []
    for item in universe:
        sector = item.get("sector", "Unknown")
        stats = sector_stats.get(sector, {"mean": 20, "std": 10})
        pe = item["fwd_pe"]

        # Skip extreme PE outliers
        if pe <= 0 or pe > 200:
            continue

        z = (pe - stats["mean"]) / stats["std"] if stats["std"] > 0 else 0

        signals.append(TickerSignal(
            ticker=item["ticker"],
            conviction=convictions[item["ticker"]],
            current_pe=pe,
            pe_z_score=z,
            pe_mean=stats["mean"],
            pe_std=stats["std"],
            price=item["price"],
        ))

    print(f"\nBuilt {len(signals)} signals")

    # Summary stats
    conv_above_60 = sum(1 for s in signals if s.conviction >= 60)
    conv_40_60 = sum(1 for s in signals if 40 <= s.conviction < 60)
    conv_below_40 = sum(1 for s in signals if s.conviction < 40)
    cheap = sum(1 for s in signals if s.pe_z_score < -0.5)
    fair = sum(1 for s in signals if -0.5 <= s.pe_z_score <= 0.5)
    expensive = sum(1 for s in signals if s.pe_z_score > 0.5)

    print(f"\nConviction distribution:")
    print(f"  > 60 (eligible):  {conv_above_60}")
    print(f"  40-60 (trim):     {conv_40_60}")
    print(f"  < 40 (exit):      {conv_below_40}")
    print(f"\nValuation distribution:")
    print(f"  Cheap (z < -0.5): {cheap}")
    print(f"  Fair (-0.5 to 0.5): {fair}")
    print(f"  Expensive (z > 0.5): {expensive}")

    # Eligible = conviction > 60 AND cheap (z < -0.5)
    eligible_and_cheap = [s for s in signals if s.conviction >= 60 and s.pe_z_score < -0.5]
    print(f"\nEligible AND cheap (will get allocation): {len(eligible_and_cheap)}")

    # Compute target weights
    held_tickers = set()  # fresh portfolio, nothing held
    weights = compute_target_weights(signals, held_tickers)

    allocated = {t: w for t, w in weights.items() if w > 0}
    total_allocated = sum(allocated.values())

    print(f"\n{'='*70}")
    print(f"PORTFOLIO ALLOCATION RESULT")
    print(f"{'='*70}")
    print(f"Tickers with allocation: {len(allocated)}")
    print(f"Total allocated: {total_allocated:.1f}%")
    print(f"Cash: {100 - total_allocated:.1f}%")
    print()

    # Show top allocations
    sorted_alloc = sorted(allocated.items(), key=lambda x: -x[1])
    print(f"{'Ticker':<8} {'Weight':>7} {'Conv':>5} {'PE':>6} {'Z':>6} {'Upside':>7} {'Sector'}")
    print("-" * 70)
    for ticker, weight in sorted_alloc[:30]:
        sig = next(s for s in signals if s.ticker == ticker)
        sector = next((item["sector"] for item in universe if item["ticker"] == ticker), "")
        u = upside_score(sig.pe_z_score)
        print(f"{ticker:<8} {weight:6.2f}% {sig.conviction:5.1f} {sig.current_pe:6.1f}x {sig.pe_z_score:+5.2f} {u:6.1f}   {sector}")

    if len(sorted_alloc) > 30:
        print(f"  ... and {len(sorted_alloc) - 30} more")

    # Test profit-taking logic
    print(f"\n{'='*70}")
    print(f"PROFIT-TAKING TEST")
    print(f"{'='*70}")

    # Simulate: pick a held stock, move PE through targets
    if eligible_and_cheap:
        test_sig = eligible_and_cheap[0]
        pos = Position(
            ticker=test_sig.ticker,
            shares=100,
            cost_basis=test_sig.price * 0.8,
            profit_target=ProfitTarget(
                mean_pe=test_sig.pe_mean,
                std_pe=test_sig.pe_std,
            ),
        )
        print(f"\nTest ticker: {test_sig.ticker}")
        print(f"  Mean PE: {test_sig.pe_mean:.1f}x, +1SD: {test_sig.pe_mean + test_sig.pe_std:.1f}x, +2SD: {test_sig.pe_mean + 2*test_sig.pe_std:.1f}x")

        for test_pe in [test_sig.current_pe, test_sig.pe_mean, test_sig.pe_mean + test_sig.pe_std, test_sig.pe_mean + 2*test_sig.pe_std]:
            action = pos.profit_target.check_profit_taking(test_pe)
            print(f"  PE={test_pe:5.1f}x -> {action} (shares={pos.shares:.0f})")

    # Test conviction gate transitions
    print(f"\n{'='*70}")
    print(f"CONVICTION GATE TEST")
    print(f"{'='*70}")

    test_ticker = "TEST"
    for conv, held, expected in [
        (80, False, "allocate"),
        (80, True, "allocate"),
        (50, False, "no entry"),
        (50, True, "trim to 1%"),
        (30, False, "no entry"),
        (30, True, "full exit"),
    ]:
        test_signal = TickerSignal(
            ticker=test_ticker, conviction=conv, current_pe=15,
            pe_z_score=-1.0, pe_mean=25, pe_std=8, price=100,
        )
        held_set = {test_ticker} if held else set()
        w = compute_target_weights([test_signal], held_set)
        actual_w = w.get(test_ticker, 0)
        status = "PASS" if (
            (expected == "allocate" and actual_w > 0) or
            (expected == "no entry" and actual_w == 0) or
            (expected == "trim to 1%" and 0 < actual_w <= 1) or
            (expected == "full exit" and actual_w == 0)
        ) else "FAIL"
        print(f"  conv={conv}, held={held} -> weight={actual_w:.1f}%, expected={expected} [{status}]")

    print(f"\nDone.")


if __name__ == "__main__":
    main()
