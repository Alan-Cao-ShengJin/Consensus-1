"""Alpaca broker adapter: real broker connectivity via alpaca-py SDK.

Implements BrokerInterface with both read and write operations.
Supports paper and live Alpaca accounts via the `paper` flag.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Optional

from broker_interface import (
    BrokerInterface,
    AccountSnapshot,
    BrokerPosition,
    BrokerOrder,
    BrokerFill,
)

logger = logging.getLogger(__name__)

# Alpaca SDK imports — optional dependency
try:
    from alpaca.trading.client import TradingClient
    from alpaca.trading.requests import (
        GetOrdersRequest,
        MarketOrderRequest,
        LimitOrderRequest,
        ReplaceOrderRequest,
    )
    from alpaca.trading.enums import (
        OrderSide,
        OrderType,
        TimeInForce,
        QueryOrderStatus,
    )
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockLatestTradeRequest
    ALPACA_AVAILABLE = True
except ImportError:
    ALPACA_AVAILABLE = False


# ---------------------------------------------------------------------------
# Rate limiter (simple token bucket)
# ---------------------------------------------------------------------------

class _RateLimiter:
    """Simple rate limiter: max `rate` calls per `period` seconds."""

    def __init__(self, rate: int = 180, period: float = 60.0):
        self._rate = rate
        self._period = period
        self._timestamps: list[float] = []

    def wait(self):
        now = time.time()
        # Purge old timestamps
        self._timestamps = [t for t in self._timestamps if now - t < self._period]
        if len(self._timestamps) >= self._rate:
            sleep_time = self._period - (now - self._timestamps[0]) + 0.1
            if sleep_time > 0:
                logger.debug("Rate limiter: sleeping %.1fs", sleep_time)
                time.sleep(sleep_time)
        self._timestamps.append(time.time())


# ---------------------------------------------------------------------------
# Retry helper
# ---------------------------------------------------------------------------

def _retry(fn, max_retries: int = 3, backoff: float = 1.0):
    """Retry on transient HTTP errors (429, 503)."""
    last_exc = None
    for attempt in range(max_retries):
        try:
            return fn()
        except Exception as e:
            last_exc = e
            err_str = str(e)
            # Retry on rate limit or service unavailable
            if "429" in err_str or "503" in err_str:
                wait = backoff * (2 ** attempt)
                logger.warning("Alpaca API error (attempt %d/%d): %s — retrying in %.1fs",
                               attempt + 1, max_retries, err_str, wait)
                time.sleep(wait)
            else:
                raise
    raise last_exc


# ---------------------------------------------------------------------------
# Alpaca broker adapter
# ---------------------------------------------------------------------------

class AlpacaBrokerAdapter(BrokerInterface):
    """Broker adapter backed by Alpaca's trading API.

    Args:
        api_key: Alpaca API key
        secret_key: Alpaca secret key
        paper: If True (default), use Alpaca paper trading endpoint
    """

    def __init__(self, api_key: str, secret_key: str, paper: bool = True):
        if not ALPACA_AVAILABLE:
            raise ImportError(
                "alpaca-py is required for AlpacaBrokerAdapter. "
                "Install with: pip install alpaca-py"
            )
        self._paper = paper
        self._trading_client = TradingClient(api_key, secret_key, paper=paper)
        self._data_client = StockHistoricalDataClient(api_key, secret_key)
        self._rate_limiter = _RateLimiter()
        env_label = "paper" if paper else "LIVE"
        logger.info("AlpacaBrokerAdapter initialized (%s)", env_label)

    def _call(self, fn):
        """Rate-limited + retried API call."""
        self._rate_limiter.wait()
        return _retry(fn)

    # -------------------------------------------------------------------
    # Read operations
    # -------------------------------------------------------------------

    def get_account_snapshot(self) -> AccountSnapshot:
        account = self._call(lambda: self._trading_client.get_account())
        positions = self.get_positions()
        open_orders = self.get_open_orders()
        recent_fills = self.get_recent_fills()

        return AccountSnapshot(
            snapshot_at=datetime.utcnow().isoformat(),
            cash=float(account.cash),
            buying_power=float(account.buying_power),
            total_equity=float(account.equity),
            positions=positions,
            open_orders=open_orders,
            recent_fills=recent_fills,
            broker_name="alpaca_paper" if self._paper else "alpaca_live",
            account_id=str(account.account_number),
        )

    def get_cash(self) -> float:
        account = self._call(lambda: self._trading_client.get_account())
        return float(account.cash)

    def get_positions(self) -> list[BrokerPosition]:
        raw_positions = self._call(lambda: self._trading_client.get_all_positions())
        result = []
        for p in raw_positions:
            result.append(BrokerPosition(
                ticker=p.symbol,
                shares=float(p.qty),
                market_value=float(p.market_value),
                avg_cost=float(p.avg_entry_price),
                last_price=float(p.current_price),
                unrealized_pnl=float(p.unrealized_pl),
            ))
        return result

    def get_open_orders(self) -> list[BrokerOrder]:
        request = GetOrdersRequest(status=QueryOrderStatus.OPEN)
        raw_orders = self._call(lambda: self._trading_client.get_orders(filter=request))
        result = []
        for o in raw_orders:
            result.append(BrokerOrder(
                order_id=str(o.id),
                ticker=o.symbol,
                side=o.side.value,
                quantity=float(o.qty) if o.qty else 0.0,
                order_type=o.type.value if o.type else "market",
                status=o.status.value if o.status else "unknown",
                filled_quantity=float(o.filled_qty) if o.filled_qty else 0.0,
                limit_price=float(o.limit_price) if o.limit_price else None,
                fill_price=float(o.filled_avg_price) if o.filled_avg_price else None,
                submitted_at=o.submitted_at.isoformat() if o.submitted_at else None,
                filled_at=o.filled_at.isoformat() if o.filled_at else None,
            ))
        return result

    def get_recent_fills(self, limit: int = 50) -> list[BrokerFill]:
        request = GetOrdersRequest(status=QueryOrderStatus.CLOSED, limit=limit)
        raw_orders = self._call(lambda: self._trading_client.get_orders(filter=request))
        result = []
        for o in raw_orders:
            if o.filled_qty and float(o.filled_qty) > 0:
                filled_price = float(o.filled_avg_price) if o.filled_avg_price else 0.0
                filled_qty = float(o.filled_qty)
                result.append(BrokerFill(
                    fill_id=str(o.id),
                    ticker=o.symbol,
                    side=o.side.value,
                    shares=filled_qty,
                    price=filled_price,
                    notional=filled_qty * filled_price,
                    filled_at=o.filled_at.isoformat() if o.filled_at else "",
                    order_id=str(o.id),
                ))
        return result

    def get_reference_price(self, ticker: str) -> Optional[float]:
        try:
            request = StockLatestTradeRequest(symbol_or_symbols=ticker)
            trades = self._call(lambda: self._data_client.get_stock_latest_trade(request))
            if ticker in trades:
                return float(trades[ticker].price)
        except Exception as e:
            logger.warning("Failed to get reference price for %s: %s", ticker, e)
        return None

    def get_reference_prices(self, tickers: list[str]) -> dict[str, float]:
        if not tickers:
            return {}
        try:
            request = StockLatestTradeRequest(symbol_or_symbols=tickers)
            trades = self._call(lambda: self._data_client.get_stock_latest_trade(request))
            return {symbol: float(trade.price) for symbol, trade in trades.items()}
        except Exception as e:
            logger.warning("Failed to get batch reference prices: %s", e)
            return {}

    # -------------------------------------------------------------------
    # Write operations
    # -------------------------------------------------------------------

    def submit_order(
        self,
        ticker: str,
        side: str,
        quantity: float,
        order_type: str = "market",
        time_in_force: str = "day",
        limit_price: Optional[float] = None,
        **kwargs,
    ) -> BrokerOrder:
        """Submit an order to Alpaca.

        Args:
            ticker: Stock symbol
            side: "buy" or "sell"
            quantity: Number of shares (supports fractional)
            order_type: "market" or "limit"
            time_in_force: "day", "gtc", "ioc"
            limit_price: Required for limit orders

        Returns:
            BrokerOrder with Alpaca order ID
        """
        alpaca_side = OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL
        alpaca_tif = {
            "day": TimeInForce.DAY,
            "gtc": TimeInForce.GTC,
            "ioc": TimeInForce.IOC,
        }.get(time_in_force.lower(), TimeInForce.DAY)

        if order_type.lower() == "limit":
            if limit_price is None:
                raise ValueError("limit_price required for limit orders")
            request = LimitOrderRequest(
                symbol=ticker,
                qty=quantity,
                side=alpaca_side,
                time_in_force=alpaca_tif,
                limit_price=limit_price,
            )
        else:
            request = MarketOrderRequest(
                symbol=ticker,
                qty=quantity,
                side=alpaca_side,
                time_in_force=alpaca_tif,
            )

        logger.info("Submitting %s order: %s %s %.4f shares @ %s",
                     order_type, side, ticker, quantity,
                     f"${limit_price}" if limit_price else "market")

        order = self._call(lambda: self._trading_client.submit_order(request))

        result = BrokerOrder(
            order_id=str(order.id),
            ticker=order.symbol,
            side=order.side.value,
            quantity=float(order.qty) if order.qty else quantity,
            order_type=order.type.value if order.type else order_type,
            status=order.status.value if order.status else "submitted",
            filled_quantity=float(order.filled_qty) if order.filled_qty else 0.0,
            limit_price=float(order.limit_price) if order.limit_price else None,
            fill_price=float(order.filled_avg_price) if order.filled_avg_price else None,
            submitted_at=order.submitted_at.isoformat() if order.submitted_at else None,
            filled_at=order.filled_at.isoformat() if order.filled_at else None,
        )
        logger.info("Order submitted: %s (broker_id=%s, status=%s)",
                     ticker, result.order_id, result.status)
        return result

    def cancel_order(self, order_id: str) -> None:
        """Cancel an open order by ID."""
        logger.info("Cancelling order: %s", order_id)
        self._call(lambda: self._trading_client.cancel_order_by_id(order_id))
        logger.info("Order cancelled: %s", order_id)

    def cancel_all_orders(self) -> int:
        """Cancel all open orders. Returns count of cancelled orders."""
        logger.warning("Cancelling ALL open orders")
        responses = self._call(lambda: self._trading_client.cancel_orders())
        count = len(responses) if responses else 0
        logger.warning("Cancelled %d orders", count)
        return count

    def modify_order(self, order_id: str, **kwargs) -> None:
        """Modify an open order (quantity and/or limit_price)."""
        replace_kwargs = {}
        if "quantity" in kwargs:
            replace_kwargs["qty"] = kwargs["quantity"]
        if "limit_price" in kwargs:
            replace_kwargs["limit_price"] = kwargs["limit_price"]
        if not replace_kwargs:
            return

        request = ReplaceOrderRequest(**replace_kwargs)
        logger.info("Modifying order %s: %s", order_id, replace_kwargs)
        self._call(lambda: self._trading_client.replace_order_by_id(order_id, request))
        logger.info("Order modified: %s", order_id)

    # -------------------------------------------------------------------
    # Market clock
    # -------------------------------------------------------------------

    def get_clock(self) -> dict:
        """Get market clock (is_open, next_open, next_close)."""
        clock = self._call(lambda: self._trading_client.get_clock())
        return {
            "is_open": clock.is_open,
            "next_open": clock.next_open.isoformat() if clock.next_open else None,
            "next_close": clock.next_close.isoformat() if clock.next_close else None,
            "timestamp": clock.timestamp.isoformat() if clock.timestamp else None,
        }

    def is_market_open(self) -> bool:
        """Check if the market is currently open."""
        clock = self._call(lambda: self._trading_client.get_clock())
        return clock.is_open
