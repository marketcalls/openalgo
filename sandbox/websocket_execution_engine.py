# sandbox/websocket_execution_engine.py
"""
WebSocket-based Execution Engine - Event-driven order execution

Features:
- Real-time order execution using WebSocket market data
- Subscribes to MarketDataService for LTP updates
- Immediate execution when price conditions are met (sub-second latency)
- Automatic fallback to polling engine if WebSocket data is stale
- Thread-safe order index management
"""

import os
import sys
import threading
import time
from decimal import Decimal
from typing import Dict, List, Optional, Set

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.sandbox_db import SandboxOrders, db_session
from services.market_data_service import get_market_data_service
from services.websocket_service import subscribe_to_symbols, unsubscribe_from_symbols
from utils.logging import get_logger

logger = get_logger(__name__)


class WebSocketExecutionEngine:
    """
    Event-driven execution engine that uses WebSocket market data
    instead of polling for order execution.
    """

    def __init__(self):
        self.market_data_service = get_market_data_service()
        self._subscriber_id: str | None = None
        self._running = False
        self._lock = threading.Lock()

        # Index of pending orders by symbol key (exchange:symbol)
        # Maps symbol_key -> list of order IDs
        self._pending_orders_index: dict[str, list[str]] = {}

        # Track symbols we're monitoring
        self._monitored_symbols: set[str] = set()

        # Track per-user symbol subscriptions (refcounts)
        # {user_id: {symbol_key: count}}
        self._user_symbol_refcounts: dict[str, dict[str, int]] = {}

        # Event-driven MTM: open POSITIONS hold a feed subscription just like
        # open orders do, so the proxy keeps MarketDataService warm and the
        # MTM loop reads tick-fresh prices instead of falling back to REST
        # multiquotes for unwatched symbols. One ref per (user_id, symbol_key)
        # regardless of how many products hold the symbol; the ref is released
        # only when every product's position is flat.
        self._position_refs: set[tuple[str, str]] = set()

        # Fallback settings
        self.fallback_enabled = os.getenv("SANDBOX_ENGINE_FALLBACK", "true").lower() == "true"
        self.stale_data_threshold = 30  # seconds
        self._fallback_thread: threading.Thread | None = None
        self._fallback_running = False

        # Import execution engine for order processing and fallback
        from sandbox.execution_engine import ExecutionEngine

        self._execution_engine = ExecutionEngine()

    def start(self):
        """Start the WebSocket execution engine"""
        if self._running:
            logger.debug("WebSocket execution engine already running")
            return

        logger.debug("Starting WebSocket execution engine")
        self._running = True

        # Build initial order index from database
        self._rebuild_order_index()

        # Subscribe to MarketDataService with CRITICAL priority for immediate processing
        try:
            self._subscriber_id = self.market_data_service.subscribe_critical(
                callback=self._on_market_data,
                filter_symbols=None,  # All symbols - we filter in callback
                name="sandbox_websocket_execution_engine",
            )
            logger.debug(f"Subscribed to MarketDataService with ID: {self._subscriber_id}")
        except Exception as e:
            logger.exception(f"Failed to subscribe to MarketDataService: {e}")
            self._running = False
            return

        # Start health monitoring thread
        self._start_health_monitor()

    def stop(self):
        """Stop the WebSocket execution engine"""
        if not self._running:
            return

        logger.info("Stopping WebSocket execution engine")
        self._running = False

        # Stop fallback if running
        self._stop_fallback()

        # Unsubscribe from MarketDataService
        if self._subscriber_id:
            try:
                self.market_data_service.unsubscribe_from_updates(self._subscriber_id)
                logger.info("Unsubscribed from MarketDataService")
            except Exception as e:
                logger.exception(f"Error unsubscribing from MarketDataService: {e}")

        self._subscriber_id = None

        # Unsubscribe all WebSocket symbols for all users
        self._unsubscribe_all_ws()

    def _rebuild_order_index(self):
        """Build index of pending orders from database"""
        subscriptions_to_add: dict[str, list[tuple[str, str]]] = {}

        with self._lock:
            self._pending_orders_index.clear()
            self._monitored_symbols.clear()
            self._user_symbol_refcounts.clear()
            self._position_refs.clear()

            try:
                pending_orders = SandboxOrders.query.filter_by(order_status="open").all()

                for order in pending_orders:
                    # Skip orders on expired F&O contracts: the symbol is gone
                    # from the master contract after the daily refresh, so
                    # subscribing it just makes the broker adapter log
                    # token-lookup errors on every boot ("No brsymbol found").
                    # Cancellation (with margin release) is handled by the
                    # square-off cycle's _cancel_expired_contract_orders --
                    # deliberately NOT done here, since cancel_order re-enters
                    # this engine via notify_order_completed and would deadlock
                    # on self._lock.
                    from datetime import date

                    from sandbox.position_manager import get_contract_expiry

                    expiry_date = get_contract_expiry(order.symbol, order.exchange)
                    if expiry_date is not None and date.today() > expiry_date:
                        logger.info(
                            f"Skipping WS subscription for {order.symbol}: contract "
                            f"expired {expiry_date}; order {order.orderid} awaits auto-cancel"
                        )
                        continue

                    symbol_key = f"{order.exchange}:{order.symbol}"
                    if symbol_key not in self._pending_orders_index:
                        self._pending_orders_index[symbol_key] = []
                    self._pending_orders_index[symbol_key].append(order.orderid)
                    self._monitored_symbols.add(symbol_key)
                    self._increment_user_symbol_refcount(order.user_id, symbol_key)

                logger.debug(
                    f"Built order index: {len(pending_orders)} orders across {len(self._monitored_symbols)} symbols"
                )

                # Event-driven MTM: open positions hold feed subscriptions too,
                # so a restart re-warms MarketDataService for every held symbol
                # (the poll loop then reads ticks instead of REST-fetching).
                # Contracts already past expiry are skipped -- their positions
                # are awaiting settlement, and the symbol may already be gone
                # from the master contract.
                from datetime import date

                from database.sandbox_db import SandboxPositions
                from sandbox.position_manager import get_contract_expiry

                open_positions = SandboxPositions.query.filter(
                    SandboxPositions.quantity != 0
                ).all()
                pos_subscribed = 0
                for pos in open_positions:
                    expiry = get_contract_expiry(pos.symbol, pos.exchange)
                    if expiry is not None and date.today() > expiry:
                        continue
                    key = f"{pos.exchange}:{pos.symbol}"
                    if (pos.user_id, key) not in self._position_refs:
                        self._position_refs.add((pos.user_id, key))
                        self._increment_user_symbol_refcount(pos.user_id, key)
                        pos_subscribed += 1
                if pos_subscribed:
                    logger.info(
                        f"Position feed: {pos_subscribed} open-position symbols added to index"
                    )

            except Exception as e:
                logger.exception(f"Error building order index: {e}")
                return

            # Build subscriptions per user (outside lock)
            for user_id, symbols in self._user_symbol_refcounts.items():
                new_symbols = []
                for symbol_key in symbols:
                    exchange, symbol = symbol_key.split(":", 1)
                    new_symbols.append((symbol, exchange))
                if new_symbols:
                    subscriptions_to_add[user_id] = new_symbols

        # Subscribe for all users
        for user_id, symbols in subscriptions_to_add.items():
            self._subscribe_ws_symbols(user_id, symbols)

    def notify_order_placed(self, order):
        """Called when a new order is placed to update the index"""
        symbol_key = f"{order.exchange}:{order.symbol}"
        subscribe_user = None
        subscribe_symbol = None

        with self._lock:
            if symbol_key not in self._pending_orders_index:
                self._pending_orders_index[symbol_key] = []

            if order.orderid not in self._pending_orders_index[symbol_key]:
                self._pending_orders_index[symbol_key].append(order.orderid)
                self._monitored_symbols.add(symbol_key)
                logger.debug(f"Added order {order.orderid} to index for {symbol_key}")

            # Increment refcount and decide if we need to subscribe
            if self._increment_user_symbol_refcount(order.user_id, symbol_key):
                subscribe_user = order.user_id
                subscribe_symbol = symbol_key

        if subscribe_user and subscribe_symbol:
            exchange, symbol = subscribe_symbol.split(":", 1)
            self._subscribe_ws_symbols(subscribe_user, [(symbol, exchange)])

    def notify_order_completed(self, order_id: str, symbol_key: str, user_id: str | None = None):
        """Called when an order is completed/cancelled to update the index"""
        unsubscribe_user = None
        unsubscribe_symbol = None

        with self._lock:
            if symbol_key and symbol_key in self._pending_orders_index:
                if order_id in self._pending_orders_index[symbol_key]:
                    self._pending_orders_index[symbol_key].remove(order_id)
                    logger.debug(f"Removed order {order_id} from index for {symbol_key}")

                # Clean up empty symbol entries
                if not self._pending_orders_index[symbol_key]:
                    del self._pending_orders_index[symbol_key]
                    self._monitored_symbols.discard(symbol_key)
            else:
                # Fallback: remove order_id from any symbol list
                self._remove_order_from_index(order_id)

            # Decrement refcount and decide if we should unsubscribe
            if user_id and symbol_key:
                if self._decrement_user_symbol_refcount(user_id, symbol_key):
                    unsubscribe_user = user_id
                    unsubscribe_symbol = symbol_key

        if unsubscribe_user and unsubscribe_symbol:
            exchange, symbol = unsubscribe_symbol.split(":", 1)
            self._unsubscribe_ws_symbols(unsubscribe_user, [(symbol, exchange)])

    def notify_position_opened(self, user_id: str, symbol: str, exchange: str):
        """Hold a feed subscription for an open position (event-driven MTM).

        Called after a fill leaves a non-zero position. Idempotent per
        (user, symbol): repeat fills on an already-referenced symbol are
        no-ops, and a symbol some open order already subscribed just gains
        a second refcount -- the pool sees one subscription either way.
        """
        if not self._running:
            return
        symbol_key = f"{exchange}:{symbol}"
        subscribe = False
        with self._lock:
            if (user_id, symbol_key) not in self._position_refs:
                self._position_refs.add((user_id, symbol_key))
                subscribe = self._increment_user_symbol_refcount(user_id, symbol_key)
        if subscribe:
            logger.info(f"Position feed: subscribing {symbol_key} for MTM (user {user_id})")
            self._subscribe_ws_symbols(user_id, [(symbol, exchange)])

    def notify_position_closed(self, user_id: str, symbol: str, exchange: str):
        """Release the position's feed subscription once the symbol is flat.

        Flat means NO product (MIS/NRML/CNC) still holds quantity -- an MIS
        close while an NRML position remains must keep the feed up. On any
        doubt (query failure) the subscription is kept; a stray subscription
        costs a few ticks, a dropped one costs live MTM.
        """
        if not self._running:
            return
        try:
            from database.sandbox_db import SandboxPositions

            remaining = (
                SandboxPositions.query.filter_by(
                    user_id=user_id, symbol=symbol, exchange=exchange
                )
                .filter(SandboxPositions.quantity != 0)
                .count()
            )
        except Exception:
            logger.debug("Position feed: flatness check failed; keeping subscription")
            return
        if remaining:
            return
        symbol_key = f"{exchange}:{symbol}"
        unsubscribe = False
        with self._lock:
            if (user_id, symbol_key) in self._position_refs:
                self._position_refs.discard((user_id, symbol_key))
                unsubscribe = self._decrement_user_symbol_refcount(user_id, symbol_key)
        if unsubscribe:
            logger.info(f"Position feed: releasing {symbol_key} (user {user_id}, flat)")
            self._unsubscribe_ws_symbols(user_id, [(symbol, exchange)])

    def _on_market_data(self, data: dict):
        """
        Callback when new market data arrives from WebSocket.
        Called immediately when LTP updates are received.
        """
        if not self._running:
            return

        try:
            symbol = data.get("symbol", "").upper()
            exchange = data.get("exchange", "")
            market_data = data.get("data", {})
            ltp = market_data.get("ltp")

            if not ltp or not symbol or not exchange:
                return

            symbol_key = f"{exchange}:{symbol}"

            # Check if we have pending orders for this symbol
            with self._lock:
                order_ids = self._pending_orders_index.get(symbol_key, []).copy()

            if not order_ids:
                return

            # Process each pending order for this symbol
            for order_id in order_ids:
                try:
                    self._check_and_execute_order(order_id, Decimal(str(ltp)))
                except Exception as e:
                    logger.exception(f"Error processing order {order_id}: {e}")

        except Exception as e:
            logger.exception(f"Error in market data callback: {e}")

    def _check_and_execute_order(self, order_id: str, ltp: Decimal):
        """
        Check if an order should execute at the current LTP and execute if conditions are met.
        """
        try:
            # Fetch the order from database
            order = SandboxOrders.query.filter_by(orderid=order_id, order_status="open").first()

            if not order:
                # Order no longer pending, remove from index and unsubscribe if possible
                stale_order = SandboxOrders.query.filter_by(orderid=order_id).first()
                if stale_order:
                    symbol_key = f"{stale_order.exchange}:{stale_order.symbol}"
                    self.notify_order_completed(order_id, symbol_key, stale_order.user_id)
                else:
                    self.notify_order_completed(order_id, "", None)
                return

            # Create a mock quote for the execution engine's _process_order method
            quote = {
                "ltp": float(ltp),
                "bid": float(ltp),  # Use LTP as bid/ask fallback
                "ask": float(ltp),
            }

            # Use the existing execution engine's order processing logic
            self._execution_engine._process_order(order, quote)

            # If order was executed, remove from index
            # Refresh the order to check status
            db_session.refresh(order)
            if order.order_status != "open":
                symbol_key = f"{order.exchange}:{order.symbol}"
                self.notify_order_completed(order_id, symbol_key, order.user_id)

        except Exception as e:
            logger.exception(f"Error checking/executing order {order_id}: {e}")

    def _start_health_monitor(self):
        """Start a thread to monitor WebSocket health and trigger fallback if needed"""

        def monitor():
            while self._running:
                try:
                    # Check if market data is fresh
                    is_fresh = self.market_data_service.is_data_fresh(
                        max_age_seconds=self.stale_data_threshold
                    )

                    if not is_fresh and self.fallback_enabled and not self._fallback_running:
                        logger.debug("WebSocket data is stale, starting polling fallback")
                        self._start_fallback()
                    elif is_fresh and self._fallback_running:
                        logger.debug("WebSocket data recovered, stopping polling fallback")
                        self._stop_fallback()

                except Exception as e:
                    logger.exception(f"Error in health monitor: {e}")

                time.sleep(5)  # Check every 5 seconds

        monitor_thread = threading.Thread(
            target=monitor, daemon=True, name="WSExecEngine-HealthMonitor"
        )
        monitor_thread.start()
        logger.debug("Started health monitor thread")

    def _start_fallback(self):
        """Start polling fallback when WebSocket is unavailable"""
        if self._fallback_running:
            return

        self._fallback_running = True

        def fallback_loop():
            from database.sandbox_db import get_config
            from sandbox.execution_engine import run_execution_engine_once

            check_interval = int(get_config("order_check_interval", "5"))
            logger.debug(f"Fallback polling started with {check_interval}s interval")

            while self._fallback_running and self._running:
                try:
                    run_execution_engine_once()
                except Exception as e:
                    logger.exception(f"Error in fallback polling: {e}")

                # Sleep in small increments for quick shutdown
                for _ in range(check_interval):
                    if not self._fallback_running or not self._running:
                        break
                    time.sleep(1)

            logger.debug("Fallback polling stopped")

        self._fallback_thread = threading.Thread(
            target=fallback_loop, daemon=True, name="WSExecEngine-Fallback"
        )
        self._fallback_thread.start()

    def _stop_fallback(self):
        """Stop polling fallback"""
        self._fallback_running = False

        if self._fallback_thread and self._fallback_thread.is_alive():
            self._fallback_thread.join(timeout=10)
            self._fallback_thread = None

    def _increment_user_symbol_refcount(self, user_id: str, symbol_key: str) -> bool:
        """
        Increment refcount for a user's symbol. Returns True if this is the first ref.
        """
        if user_id not in self._user_symbol_refcounts:
            self._user_symbol_refcounts[user_id] = {}

        current = self._user_symbol_refcounts[user_id].get(symbol_key, 0)
        self._user_symbol_refcounts[user_id][symbol_key] = current + 1
        return current == 0

    def _decrement_user_symbol_refcount(self, user_id: str, symbol_key: str) -> bool:
        """
        Decrement refcount for a user's symbol. Returns True if count reaches zero.
        """
        if user_id not in self._user_symbol_refcounts:
            return False

        current = self._user_symbol_refcounts[user_id].get(symbol_key, 0)
        if current <= 1:
            self._user_symbol_refcounts[user_id].pop(symbol_key, None)
            if not self._user_symbol_refcounts[user_id]:
                self._user_symbol_refcounts.pop(user_id, None)
            return True

        self._user_symbol_refcounts[user_id][symbol_key] = current - 1
        return False

    def _remove_order_from_index(self, order_id: str):
        """Remove order_id from all symbol buckets (fallback cleanup)."""
        to_cleanup = []
        for symbol_key, order_ids in self._pending_orders_index.items():
            if order_id in order_ids:
                order_ids.remove(order_id)
                logger.debug(f"Removed order {order_id} from index for {symbol_key} (fallback)")
                if not order_ids:
                    to_cleanup.append(symbol_key)
        for symbol_key in to_cleanup:
            del self._pending_orders_index[symbol_key]
            self._monitored_symbols.discard(symbol_key)

    def _subscribe_ws_symbols(self, user_id: str, symbols: list[tuple[str, str]]):
        """Subscribe to LTP via WebSocket for the given user and symbols."""
        if not symbols:
            return

        try:
            from database.auth_db import get_api_key_for_tradingview, get_broker_name

            api_key = get_api_key_for_tradingview(user_id)
            if not api_key:
                logger.warning(
                    f"WebSocket subscribe skipped: no API key for user {user_id}"
                )
                return
            broker = get_broker_name(api_key) if api_key else None
            broker_name = broker or "unknown"
            if broker_name == "unknown":
                logger.warning(
                    f"WebSocket subscribe may fail: unknown broker for user {user_id}"
                )

            symbol_payload = [{"symbol": s, "exchange": e} for s, e in symbols]
            success, response, status_code = subscribe_to_symbols(
                username=user_id, broker=broker_name, symbols=symbol_payload, mode="LTP"
            )
            if not success:
                logger.warning(
                    f"WebSocket subscribe failed for user {user_id}: {response.get('message')} (status {status_code})"
                )
        except Exception as e:
            logger.exception(f"Error subscribing WebSocket symbols for user {user_id}: {e}")

    def _unsubscribe_ws_symbols(self, user_id: str, symbols: list[tuple[str, str]]):
        """Unsubscribe from LTP via WebSocket for the given user and symbols."""
        if not symbols:
            return

        try:
            from database.auth_db import get_api_key_for_tradingview, get_broker_name

            api_key = get_api_key_for_tradingview(user_id)
            if not api_key:
                logger.warning(
                    f"WebSocket unsubscribe skipped: no API key for user {user_id}"
                )
                return
            broker = get_broker_name(api_key) if api_key else None
            broker_name = broker or "unknown"
            if broker_name == "unknown":
                logger.warning(
                    f"WebSocket unsubscribe may fail: unknown broker for user {user_id}"
                )

            symbol_payload = [{"symbol": s, "exchange": e} for s, e in symbols]
            success, response, status_code = unsubscribe_from_symbols(
                username=user_id, broker=broker_name, symbols=symbol_payload, mode="LTP"
            )
            if not success:
                logger.warning(
                    f"WebSocket unsubscribe failed for user {user_id}: {response.get('message')} (status {status_code})"
                )
        except Exception as e:
            logger.exception(f"Error unsubscribing WebSocket symbols for user {user_id}: {e}")

    def _unsubscribe_all_ws(self):
        """Unsubscribe all WebSocket symbols for all users."""
        users_to_unsub = []
        with self._lock:
            for user_id, symbols in self._user_symbol_refcounts.items():
                symbol_list = []
                for symbol_key in symbols:
                    exchange, symbol = symbol_key.split(":", 1)
                    symbol_list.append((symbol, exchange))
                if symbol_list:
                    users_to_unsub.append((user_id, symbol_list))
            self._user_symbol_refcounts.clear()

        for user_id, symbols in users_to_unsub:
            self._unsubscribe_ws_symbols(user_id, symbols)


# Global instance for singleton access
_websocket_execution_engine: WebSocketExecutionEngine | None = None
_engine_lock = threading.Lock()


def get_websocket_execution_engine() -> WebSocketExecutionEngine:
    """Get or create the singleton WebSocket execution engine instance"""
    global _websocket_execution_engine

    with _engine_lock:
        if _websocket_execution_engine is None:
            _websocket_execution_engine = WebSocketExecutionEngine()
        return _websocket_execution_engine


def start_websocket_execution_engine():
    """Start the WebSocket execution engine"""
    engine = get_websocket_execution_engine()
    engine.start()
    return True, "WebSocket execution engine started"


def stop_websocket_execution_engine():
    """Stop the WebSocket execution engine"""
    global _websocket_execution_engine

    with _engine_lock:
        if _websocket_execution_engine:
            _websocket_execution_engine.stop()
            _websocket_execution_engine = None
            return True, "WebSocket execution engine stopped"
        return True, "WebSocket execution engine not running"


def is_websocket_execution_engine_running() -> bool:
    """Check if WebSocket execution engine is running"""
    with _engine_lock:
        return _websocket_execution_engine is not None and _websocket_execution_engine._running
