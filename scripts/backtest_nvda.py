"""Single-ticker backtest: conviction + valuation -> allocation.

Two separate signals:
1. Conviction score (LLM-driven, from documents) — how strong is the thesis?
2. Valuation adjustment (forward P/E vs 5yr history + peers) — is the price right?

Allocation = conviction_pct * valuation_multiplier
- If P/E is cheap (z-score < -1): multiplier > 1 (more aggressive)
- If P/E is fair (z-score ~ 0): multiplier = 1 (conviction drives allocation)
- If P/E is expensive (z-score > 1): multiplier < 1 (trim despite conviction)
"""
import os
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_BACKTEST_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backtests")
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_BACKTEST_DIR, 'nvda_backtest.db')}"

from db import SessionLocal
from sqlalchemy import text
from auto_valuation import run_valuation_for_ticker


def get_valuation_multiplier(session, ticker, as_of_date):
    """Compute allocation multiplier from valuation data.

    Returns (multiplier, valuation_info_dict).
    multiplier: 0.6-1.2 range based on P/E z-score vs 5yr history.
    - z < -1.5: 1.20 (very cheap, be aggressive)
    - z < -0.5: 1.10 (cheap)
    - z ~ 0:    1.00 (fair, let conviction drive)
    - z > 0.5:  0.90 (getting expensive)
    - z > 1.0:  0.80 (expensive, trim)
    - z > 1.5:  0.70 (very expensive, trim hard)
    - z > 2.0:  0.60 (extreme, significant trim)
    """
    try:
        result = run_valuation_for_ticker(session, ticker, as_of_date)
        if not result or result.pe_forward is None:
            return 1.0, {}

        info = {
            "pe_forward": result.pe_forward,
            "pe_mean_5y": result.pe_forward_mean_5y,
            "pe_std_5y": result.pe_forward_std_5y,
            "zscore": result.pe_forward_zscore,
            "peer_median_pe": result.peer_median_pe,
            "peer_premium_pct": result.peer_premium_pct,
            "signal": result.valuation_signal,
        }

        z = result.pe_forward_zscore
        if z is None:
            return 1.0, info

        if z > 2.0:
            mult = 0.60
        elif z > 1.5:
            mult = 0.70
        elif z > 1.0:
            mult = 0.80
        elif z > 0.5:
            mult = 0.90
        elif z > -0.5:
            mult = 1.00
        elif z > -1.5:
            mult = 1.10
        else:
            mult = 1.20

        return mult, info
    except Exception:
        return 1.0, {}


def get_conviction_as_of(history, as_of_date):
    """Get conviction score as of a date from sorted history list."""
    score = 0.0
    for dt, conv in history:
        if dt.date() <= as_of_date if isinstance(dt, datetime) else dt <= as_of_date:
            score = conv
        else:
            break
    return score


def get_price_as_of(prices, as_of_date):
    """Get latest price on or before date."""
    price = None
    for dt, close in prices:
        d = dt.date() if isinstance(dt, datetime) else dt if isinstance(dt, date) else date.fromisoformat(str(dt)[:10])
        if d <= as_of_date:
            price = close
        else:
            break
    return price


def run_backtest():
    session = SessionLocal()

    # Load conviction history
    rows = session.execute(text("""
        SELECT created_at, conviction_score
        FROM thesis_state_history
        WHERE thesis_id = (SELECT id FROM theses WHERE company_ticker = 'NVDA' AND status_active = 1)
        ORDER BY created_at
    """)).fetchall()

    history = []
    for r in rows:
        dt = r[0]
        if isinstance(dt, str):
            dt = datetime.fromisoformat(dt)
        history.append((dt, r[1]))

    # Load prices
    price_rows = session.execute(text("""
        SELECT date, close FROM prices WHERE ticker = 'NVDA' ORDER BY date
    """)).fetchall()

    prices = []
    for r in price_rows:
        dt = r[0]
        if isinstance(dt, str):
            dt = date.fromisoformat(dt[:10])
        prices.append((dt, r[1]))

    # Keep session open for valuation queries

    # Backtest parameters
    initial_cash = 100_000.0
    tx_cost_bps = 10.0  # 0.10% per trade
    start_date = date(2024, 3, 1)  # first Friday after initial calibration
    end_date = date(2026, 3, 20)

    # Generate daily review dates (every trading day = weekday)
    review_dates = []
    d = start_date
    while d <= end_date:
        if d.weekday() < 5:  # Mon-Fri
            review_dates.append(d)
        d += timedelta(days=1)

    # Simulation state
    cash = initial_cash
    shares = 0.0
    trades = []
    portfolio_values = []

    # Buy-and-hold comparison
    first_price = get_price_as_of(prices, start_date)
    bh_shares = initial_cash / first_price if first_price else 0

    print(f"{'='*70}")
    print(f"NVDA BACKTEST: {start_date} to {end_date}")
    print(f"Initial: ${initial_cash:,.0f} | TX cost: {tx_cost_bps} bps")
    print(f"First price: ${first_price:.2f}")
    print(f"{'='*70}")
    print(f"{'Date':<12} {'Conv':>4} {'ValMul':>6} {'Target%':>7} {'Action':<6} {'Shares':>8} "
          f"{'Price':>8} {'Port$':>10} {'B&H$':>10}")
    print("-" * 80)

    # Cache valuation multiplier (recompute weekly, not daily)
    cached_val_mult = 1.0
    cached_val_info = {}
    last_val_date = None

    for review_date in review_dates:
        price = get_price_as_of(prices, review_date)
        if price is None:
            continue

        conviction = get_conviction_as_of(history, review_date)

        # Recompute valuation multiplier weekly (every Monday or first day)
        if last_val_date is None or (review_date - last_val_date).days >= 7:
            cached_val_mult, cached_val_info = get_valuation_multiplier(session, 'NVDA', review_date)
            last_val_date = review_date

        val_mult = cached_val_mult

        # Target allocation: conviction% * valuation_multiplier, capped at 95%
        raw_pct = conviction / 100.0 * val_mult
        target_pct = min(max(raw_pct, 0.0), 0.95)

        # Current portfolio value
        port_value = cash + shares * price

        # Target shares
        target_value = port_value * target_pct
        current_value = shares * price
        delta_value = target_value - current_value

        action = ""
        if abs(delta_value) > port_value * 0.02:  # only trade if >2% rebalance
            if delta_value > 0:
                # Buy
                cost = delta_value * (1 + tx_cost_bps / 10000)
                if cost <= cash:
                    new_shares = delta_value / price
                    shares += new_shares
                    cash -= cost
                    action = "BUY"
                    trades.append((review_date, "BUY", new_shares, price))
            else:
                # Sell
                sell_shares = abs(delta_value) / price
                if sell_shares <= shares:
                    proceeds = abs(delta_value) * (1 - tx_cost_bps / 10000)
                    shares -= sell_shares
                    cash += proceeds
                    action = "SELL"
                    trades.append((review_date, "SELL", sell_shares, price))

        port_value = cash + shares * price
        bh_value = bh_shares * price
        alloc_pct = (shares * price / port_value * 100) if port_value > 0 else 0
        portfolio_values.append((review_date, port_value, bh_value, conviction, price, alloc_pct, val_mult))

        if action or review_date == review_dates[0] or review_date == review_dates[-1]:
            print(f"{review_date}  {conviction:3.0f}  {val_mult:5.2f}  {target_pct*100:5.1f}%  {action:<6} "
                  f"{shares:8.1f} {price:8.2f} {port_value:10,.0f} {bh_value:10,.0f}")

    # Final results
    final_port = portfolio_values[-1][1] if portfolio_values else initial_cash
    final_bh = portfolio_values[-1][2] if portfolio_values else initial_cash
    last_price = get_price_as_of(prices, end_date)

    port_return = (final_port / initial_cash - 1) * 100
    bh_return = (final_bh / initial_cash - 1) * 100
    nvda_return = (last_price / first_price - 1) * 100 if first_price and last_price else 0

    print(f"\n{'='*70}")
    print(f"RESULTS")
    print(f"{'='*70}")
    print(f"Strategy return:   {port_return:+.1f}% (${final_port:,.0f})")
    print(f"Buy & hold return: {bh_return:+.1f}% (${final_bh:,.0f})")
    print(f"NVDA price return: {nvda_return:+.1f}% (${first_price:.2f} -> ${last_price:.2f})")
    print(f"Alpha vs B&H:      {port_return - bh_return:+.1f}%")
    print(f"Total trades:      {len(trades)}")
    print(f"Final allocation:  {(shares * last_price / final_port * 100):.0f}% NVDA, "
          f"{(cash / final_port * 100):.0f}% cash")

    # Max drawdown
    peak = initial_cash
    max_dd = 0
    for _, pv, _, _, _, _, _ in portfolio_values:
        if pv > peak:
            peak = pv
        dd = (peak - pv) / peak * 100
        if dd > max_dd:
            max_dd = dd
    print(f"Max drawdown:      {max_dd:.1f}%")

    session.close()

    # Plot
    _plot_results(portfolio_values, initial_cash, trades)

    return portfolio_values, trades


def _plot_results(portfolio_values, initial_cash, trades):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates

    dates = [pv[0] for pv in portfolio_values]
    port_vals = [pv[1] for pv in portfolio_values]
    bh_vals = [pv[2] for pv in portfolio_values]
    convictions = [pv[3] for pv in portfolio_values]
    prices = [pv[4] for pv in portfolio_values]
    alloc_pcts = [pv[5] for pv in portfolio_values]
    val_mults = [pv[6] for pv in portfolio_values]

    fig, (ax1, ax2, ax3, ax4) = plt.subplots(4, 1, figsize=(14, 14), height_ratios=[1.2, 0.8, 0.8, 0.8], sharex=True)

    # Panel 1: NVDA share price
    ax1.plot(dates, prices, color='#2196F3', linewidth=1.5)
    ax1.set_ylabel('NVDA Price ($)')
    ax1.set_title('NVDA Backtest: Price, Conviction, Valuation Multiplier & Allocation')
    ax1.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'${x:.0f}'))
    ax1.grid(alpha=0.2)

    # Mark trades on price chart
    buy_dates = [t[0] for t in trades if t[1] == 'BUY']
    buy_prices = [next(pv[4] for pv in portfolio_values if pv[0] == t[0]) for t in trades if t[1] == 'BUY']
    sell_dates = [t[0] for t in trades if t[1] == 'SELL']
    sell_prices = [next(pv[4] for pv in portfolio_values if pv[0] == t[0]) for t in trades if t[1] == 'SELL']
    ax1.scatter(buy_dates, buy_prices, color='green', marker='^', s=60, zorder=5, label='Buy')
    ax1.scatter(sell_dates, sell_prices, color='red', marker='v', s=60, zorder=5, label='Sell')
    ax1.legend(loc='upper left')

    # Panel 2: Conviction score (pure LLM signal)
    ax2.fill_between(dates, convictions, alpha=0.3, color='#FF5722')
    ax2.plot(dates, convictions, color='#FF5722', linewidth=1.5)
    ax2.set_ylabel('Conviction Score')
    ax2.set_ylim(0, 105)
    ax2.axhline(y=75, color='green', linestyle='--', alpha=0.3, label='75 (strong)')
    ax2.axhline(y=50, color='gray', linestyle='--', alpha=0.3, label='50 (moderate)')
    ax2.legend(loc='upper left')
    ax2.grid(alpha=0.2)

    # Panel 3: Valuation multiplier (P/E based adjustment)
    ax3.plot(dates, val_mults, color='#9C27B0', linewidth=1.5)
    ax3.fill_between(dates, val_mults, 1.0, where=[v >= 1.0 for v in val_mults],
                     alpha=0.2, color='green', label='Cheap (boost)')
    ax3.fill_between(dates, val_mults, 1.0, where=[v < 1.0 for v in val_mults],
                     alpha=0.2, color='red', label='Expensive (trim)')
    ax3.axhline(y=1.0, color='gray', linestyle='--', alpha=0.5, label='Fair value')
    ax3.set_ylabel('Valuation Mult.')
    ax3.set_ylim(0.4, 1.4)
    ax3.legend(loc='upper left')
    ax3.grid(alpha=0.2)

    # Panel 4: Actual % holding in portfolio (conviction * valuation)
    ax4.fill_between(dates, alloc_pcts, alpha=0.3, color='#4CAF50')
    ax4.plot(dates, alloc_pcts, color='#4CAF50', linewidth=1.5)
    ax4.set_ylabel('NVDA Allocation (%)')
    ax4.set_ylim(0, 105)
    ax4.axhline(y=95, color='red', linestyle='--', alpha=0.3, label='95% cap')
    ax4.legend(loc='upper left')
    ax4.set_xlabel('Date')
    ax4.grid(alpha=0.2)

    ax4.xaxis.set_major_formatter(mdates.DateFormatter('%b %Y'))
    ax4.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
    fig.autofmt_xdate()

    fig.tight_layout()
    out_path = os.path.join(_BACKTEST_DIR, 'nvda_backtest_results.png')
    plt.savefig(out_path, dpi=150, bbox_inches='tight')
    print(f"\nPlot saved: {out_path}")


if __name__ == "__main__":
    run_backtest()
