"""
mstock WebSocket adapter implementation (synchronous).

Uses sync websocket-client to avoid asyncio event loop conflicts
with eventlet in gunicorn+eventlet deployments.
"""

import copy
import json
import os
import sys
import threading
import time
from typing import Any

from broker.mstock.api.data import BrokerData
from broker.mstock.api.mstockwebsocket import MstockWebSocket, _env_float
from database.auth_db import get_auth_token
from database.token_db import get_token
from utils.logging import get_logger

sys.path.append(os.path.join(os.path.dirname(__file__), "../../../"))

from websocket_proxy.base_adapter import BaseBrokerWebSocketAdapter
from websocket_proxy.mapping import SymbolMapper

from .mstock_mapping import MstockCapabilityRegistry, MstockExchangeMapper


class MstockWebSocketAdapter(BaseBrokerWebSocketAdapter):
    """mstock-specific implementation of the WebSocket adapter"""

    def __init__(self):
        super().__init__()
        self.logger = get_logger("mstock_websocket")
        self.ws_client = None
        self.data_client = None
        self.user_id = None
        self.broker_name = "mstock"
        self.running = False
        self.lock = threading.Lock()
        self.auth_token = None
        self.token_modes = {}
        self.token_correlation_ids = {}

        # Subscribe coalescing (issue #1352) - mirrors the angel/zerodha
        # subscription_queue + batch_timer pattern. Per-symbol subscribe()
        # calls append to the queue and arm a 500ms timer; the timer drains
        # the queue and emits one ws_client.subscribe_batch() per mode, so a
        # 100-symbol watchlist collapses into a handful of broker-side frames
        # instead of one frame per symbol. mStock's tokenList accepts many
        # tokens per exchangeType, so the whole batch fits in one message.
        self.subscription_queue: list[dict] = []
        self.batch_timer: threading.Timer | None = None
        # Per-token requeue budget. A refused send is retried, but a socket that
        # keeps refusing while still reporting connected would otherwise requeue
        # and re-arm every batch_delay forever, spinning the timer and filling
        # the log. After the budget is spent the token is left for the resync,
        # which runs on the next login.
        self.send_retries: dict[str, int] = {}
        self.max_send_retries = max(1, int(_env_float("MSTOCK_WS_SEND_RETRIES", 3)))
        # Coalescing window; overridable from .env for deployments that want a
        # tighter or looser batch than the fleet default.
        self.batch_delay = _env_float("MSTOCK_WS_BATCH_DELAY", 0.5)

    def initialize(
        self, broker_name: str, user_id: str, auth_data: dict[str, str] | None = None
    ) -> None:
        self.user_id = user_id
        self.broker_name = broker_name

        if not auth_data:
            auth_token = get_auth_token(user_id, bypass_cache=True)
            if not auth_token:
                self.logger.error(f"No authentication token found for user {user_id}")
                raise ValueError(f"No authentication token found for user {user_id}")
        else:
            auth_token = auth_data.get("auth_token")
            if not auth_token:
                self.logger.error("Missing required authentication data")
                raise ValueError("Missing required authentication data")

        self.auth_token = auth_token
        self.data_client = BrokerData(auth_token=auth_token)
        # Pass a token_provider so the client re-reads a fresh access token from
        # the database before each reconnect; Indian broker tokens roll over
        # daily (~3 AM IST) and the construction-time token is dead after rollover.
        self.ws_client = MstockWebSocket(
            auth_token=auth_token,
            token_provider=self._get_fresh_auth_token,
            # is_auth_error() is inherited from BaseBrokerWebSocketAdapter, so
            # mstock shares the fleet's 401/403 vocabulary instead of its own.
            auth_error_check=self.is_auth_error,
        )
        self.running = True
        self.logger.info(f"mstock adapter initialized for user {user_id}")

    def _get_fresh_auth_token(self) -> str | None:
        """
        Re-read a fresh access token from the database for the current user.

        Used as the token_provider for MstockWebSocket so reconnects after the
        daily token rollover (~3 AM IST) pick up a live token. Returns None on
        failure so the client keeps its existing token.
        """
        if not self.user_id:
            return None
        try:
            return get_auth_token(self.user_id, bypass_cache=True)
        except Exception as e:
            self.logger.warning(f"Failed to re-read fresh mstock auth token: {e}")
            return None

    def connect(self) -> None:
        """Establish persistent connection to mstock WebSocket"""
        if not self.ws_client:
            self.logger.error("WebSocket client not initialized. Call initialize() first.")
            return

        self.logger.info("Connecting to mstock WebSocket in streaming mode...")
        self.running = True

        # Set before the thread starts. connect_stream() returns immediately but
        # the worker is already live, and a connection that fails outright can
        # reach _on_feed_dead() first - setting the flag afterwards would
        # overwrite its False and hand the proxy a feed whose thread has exited.
        self.connected = True

        # Start streaming — returns immediately (same as Angel/Upstox pattern)
        self.ws_client.connect_stream(
            self._on_data,
            resync_callback=self._resync_subscriptions,
            auth_failure_callback=self._on_feed_dead,
        )

        # And re-check, in case the worker died between the two statements.
        if not self.ws_client.running:
            self.connected = False
            self.logger.error("mstock feed died during connect; adapter left disconnected")
            return

        self.logger.info("mstock WebSocket adapter connected")

    def _on_feed_dead(self) -> None:
        """Stop advertising a feed that will not recover without a new login.

        Reached on an expired credential and on an exhausted reconnect budget.
        Without this the proxy keeps serving a cached adapter whose thread has
        already exited, so subscribes succeed and no tick ever arrives.
        """
        self.connected = False
        self.logger.error(
            "mstock feed is terminally down; marking the adapter disconnected "
            "so it is rebuilt on the next login"
        )

    def _on_data(self, quote_data: dict) -> None:
        """Callback function called when data is received from WebSocket"""
        try:
            token = quote_data.get("token")
            if not token:
                self.logger.warning("Received data without token")
                return

            matching_subscriptions = []
            with self.lock:
                for sub in self.subscriptions.values():
                    if sub["token"] == token:
                        matching_subscriptions.append(sub)

            if not matching_subscriptions:
                self.logger.warning(f"Received data for unsubscribed token: '{token}'")
                return

            packet_mode = quote_data.get("subscription_mode", 1)
            market_data_base = self._normalize_market_data(quote_data, packet_mode)

            for subscription in matching_subscriptions:
                symbol = subscription["symbol"]
                exchange = subscription["exchange"]
                mode = subscription["mode"]
                mode_str = {1: "LTP", 2: "QUOTE", 3: "DEPTH"}[mode]
                topic = f"{exchange}_{symbol}_{mode_str}"

                market_data = copy.deepcopy(market_data_base)
                market_data.update(
                    {
                        "symbol": symbol,
                        "exchange": exchange,
                        "mode": mode,
                        "timestamp": int(time.time() * 1000),
                    }
                )

                self.publish_market_data(topic, market_data)
                self.logger.debug(f"Published data for {symbol} on {exchange} mode {mode}")

        except Exception as e:
            self.logger.exception(f"Error processing data: {str(e)}")

    def disconnect(self) -> None:
        """Disconnect from mstock WebSocket"""
        self.running = False

        # Cancel any pending subscribe-batch flush so the timer thread does not
        # outlive the connection it was going to send on.
        with self.lock:
            if self.batch_timer:
                self.batch_timer.cancel()
                self.batch_timer = None
            self.subscription_queue.clear()

        if self.ws_client:
            self.ws_client.disconnect_stream()

        self.connected = False
        self.logger.info("mstock WebSocket adapter disconnected")
        self.cleanup_zmq()

    def subscribe(
        self, symbol: str, exchange: str, mode: int = 2, depth_level: int = 5
    ) -> dict[str, Any]:
        if mode not in [1, 2, 3]:
            return self._create_error_response(
                "INVALID_MODE", f"Invalid mode {mode}. Must be 1 (LTP), 2 (Quote), or 3 (Depth)"
            )

        if mode == 3 and depth_level not in [5]:
            return self._create_error_response(
                "INVALID_DEPTH", f"Invalid depth level {depth_level}. mstock only supports 5 levels"
            )

        token_info = SymbolMapper.get_token_from_symbol(symbol, exchange)
        if not token_info:
            return self._create_error_response(
                "SYMBOL_NOT_FOUND", f"Symbol {symbol} not found for exchange {exchange}"
            )

        token = token_info["token"]
        brexchange = token_info["brexchange"]
        exchange_type = MstockExchangeMapper.get_exchange_type(brexchange)
        correlation_id = f"{symbol}_{exchange}_{mode}"

        needs_ws_subscribe = False
        subscribe_mode = mode

        with self.lock:
            self.subscriptions[correlation_id] = {
                "symbol": symbol,
                "exchange": exchange,
                "brexchange": brexchange,
                "token": token,
                "mode": mode,
                "depth_level": depth_level,
                "exchange_type": exchange_type,
            }

            max_mode_for_token = mode
            for sub in self.subscriptions.values():
                if sub["token"] == token:
                    max_mode_for_token = max(max_mode_for_token, sub["mode"])

            # token_modes records what the BROKER has confirmed, so it is written
            # by the flush once a frame is actually sent - never here. Writing it
            # optimistically made a dropped subscribe permanent: this branch
            # would never fire again for the token, and the reconnect path walks
            # the SDK's dict, which never received the entry either.
            current_mstock_mode = self.token_modes.get(token, 0)
            queued_mode = max(
                (q["mode"] for q in self.subscription_queue if q["token"] == token),
                default=0,
            )
            if max_mode_for_token > max(current_mstock_mode, queued_mode):
                needs_ws_subscribe = True
                subscribe_mode = max_mode_for_token

        if needs_ws_subscribe and self.ws_client and self.running:
            if not self.ws_client.is_connected():
                # Held in self.subscriptions only. token_modes stays unset, so
                # the resync on the next successful login sends it.
                self.logger.warning(
                    f"WebSocket not connected; subscription for {symbol} held locally "
                    f"and will be sent on reconnect"
                )
            else:
                # Queue for batched subscribe. The actual send is emitted by
                # _process_batch_subscriptions after the coalescing window, so
                # bursty per-symbol startups collapse into one frame per mode.
                try:
                    with self.lock:
                        self.subscription_queue.append(
                            {
                                "token": token,
                                "mode": subscribe_mode,
                                "exchange_type": exchange_type,
                                "symbol": symbol,
                                "exchange": exchange,
                                # Set when upgrading an existing lower mode, so
                                # the flush drops the old subscription first.
                                "old_correlation_id": (
                                    self.token_correlation_ids.get(token)
                                    if current_mstock_mode > 0
                                    else None
                                ),
                            }
                        )
                        if len(self.subscription_queue) == 1:
                            self._start_batch_timer()
                except Exception as e:
                    self.logger.exception(
                        f"Error queuing subscription for {symbol}.{exchange}: {e}"
                    )
                    return self._create_error_response("SUBSCRIPTION_ERROR", str(e))

        return {
            "status": "success",
            "message": f"Subscribed to {symbol} on {exchange} in mode {mode}",
            "correlation_id": correlation_id,
        }

    def _normalize_market_data(self, quote_data: dict, mode: int) -> dict[str, Any]:
        try:
            normalized = {"ltp": float(quote_data.get("ltp", 0))}

            if mode >= 2:
                normalized.update(
                    {
                        "open": float(quote_data.get("open", 0)),
                        "high": float(quote_data.get("high", 0)),
                        "low": float(quote_data.get("low", 0)),
                        "close": float(quote_data.get("close", 0)),
                        "prev_close": float(quote_data.get("close", 0)),
                        "volume": int(quote_data.get("volume", 0)),
                        "oi": int(quote_data.get("oi", 0)),
                        "last_trade_quantity": int(quote_data.get("last_traded_qty", 0)),
                        "average_price": float(quote_data.get("avg_price", 0)),
                        "total_buy_quantity": int(quote_data.get("total_buy_qty", 0)),
                        "total_sell_quantity": int(quote_data.get("total_sell_qty", 0)),
                    }
                )

            if mode == 3:
                bids = quote_data.get("bids", [])[:5]
                asks = quote_data.get("asks", [])[:5]

                formatted_bids = []
                for bid in bids:
                    if isinstance(bid, dict):
                        formatted_bids.append(
                            {
                                "price": float(bid.get("price", 0)),
                                "quantity": int(bid.get("quantity", 0)),
                                "orders": int(bid.get("orders", 0)),
                            }
                        )
                    elif isinstance(bid, (list, tuple)) and len(bid) >= 2:
                        formatted_bids.append(
                            {
                                "price": float(bid[0]),
                                "quantity": int(bid[1]),
                                "orders": int(bid[2]) if len(bid) > 2 else 0,
                            }
                        )

                formatted_asks = []
                for ask in asks:
                    if isinstance(ask, dict):
                        formatted_asks.append(
                            {
                                "price": float(ask.get("price", 0)),
                                "quantity": int(ask.get("quantity", 0)),
                                "orders": int(ask.get("orders", 0)),
                            }
                        )
                    elif isinstance(ask, (list, tuple)) and len(ask) >= 2:
                        formatted_asks.append(
                            {
                                "price": float(ask[0]),
                                "quantity": int(ask[1]),
                                "orders": int(ask[2]) if len(ask) > 2 else 0,
                            }
                        )

                normalized["depth"] = {"buy": formatted_bids, "sell": formatted_asks}
                normalized.update(
                    {
                        "total_buy_quantity": int(quote_data.get("total_buy_qty", 0)),
                        "total_sell_quantity": int(quote_data.get("total_sell_qty", 0)),
                        "upper_circuit": float(quote_data.get("upper_circuit", 0)),
                        "lower_circuit": float(quote_data.get("lower_circuit", 0)),
                    }
                )

            return normalized

        except Exception as e:
            self.logger.exception(f"Error normalizing market data: {str(e)}")
            return {"ltp": 0}

    def _resync_subscriptions(self) -> None:
        """
        Re-send every desired subscription after a successful login.

        self.subscriptions is the desired state and is authoritative; the
        broker holds nothing after a reconnect, so confirmed state is cleared
        and each token is queued again at its highest requested mode. This is
        what recovers a subscription made while the socket was down, or one
        whose batch was dropped - both leave token_modes unset and would
        otherwise never be retried.
        """
        with self.lock:
            desired: dict[str, dict] = {}
            for sub in self.subscriptions.values():
                token = str(sub["token"])
                if token not in desired or sub["mode"] > desired[token]["mode"]:
                    desired[token] = sub

            # The broker retains nothing across a reconnect.
            self.token_modes.clear()
            self.token_correlation_ids.clear()
            self.send_retries.clear()
            self.subscription_queue = [
                {
                    "token": token,
                    "mode": sub["mode"],
                    "exchange_type": sub["exchange_type"],
                    "symbol": sub["symbol"],
                    "exchange": sub["exchange"],
                    "old_correlation_id": None,
                }
                for token, sub in desired.items()
            ]
            if self.subscription_queue:
                self._start_batch_timer()

        if desired:
            self.logger.info(f"Resyncing {len(desired)} subscription(s) after login")

    def _start_batch_timer(self) -> None:
        """
        Arm the coalescing timer that drains subscription_queue.

        Called from within the lock when a fresh subscription enters an empty
        queue; enqueues during the window join the same flush.
        """
        if self.batch_timer:
            self.batch_timer.cancel()
        self.batch_timer = threading.Timer(self.batch_delay, self._process_batch_subscriptions)
        self.batch_timer.daemon = True
        self.batch_timer.start()

    def _process_batch_subscriptions(self) -> None:
        """
        Drain the queue and emit one subscribe frame per mode.

        Collapses N per-symbol subscribes into one frame per distinct mode.
        Mode upgrades drop their old subscription first; those unsubscribes
        are batched too, so the settle pause is paid once for the whole flush
        rather than once per symbol.
        """
        with self.lock:
            if not self.subscription_queue:
                self.batch_timer = None
                return
            pending = list(self.subscription_queue)
            self.subscription_queue.clear()
            self.batch_timer = None

        if not self.running or not self.ws_client or not self.ws_client.is_connected():
            self.logger.warning(f"Dropping batch of {len(pending)} subscriptions - not connected")
            return

        # Last entry wins per token: a token queued twice in one window only
        # needs its final mode, and the earlier entry's frame would be
        # superseded immediately anyway.
        latest: dict[str, dict] = {}
        for sub in pending:
            latest[str(sub["token"])] = sub

        # Revalidate against current state before sending: a token unsubscribed
        # after being queued must not be subscribed at the broker. unsubscribe()
        # already prunes the queue, so this only catches an unsubscribe that
        # landed between the drain above and here.
        with self.lock:
            desired_mode: dict[str, int] = {}
            for sub in self.subscriptions.values():
                token = str(sub["token"])
                desired_mode[token] = max(desired_mode.get(token, 0), sub["mode"])

        # Compare the queued mode against the highest mode still wanted, not
        # merely whether the token survives: unsubscribing a depth stream while
        # an LTP one remains leaves the token live but its queued mode stale,
        # and sending it would resubscribe depth nobody asked for.
        dropped = [
            token for token, sub in latest.items() if sub["mode"] > desired_mode.get(token, 0)
        ]
        for token in dropped:
            del latest[token]
        if dropped:
            self.logger.info(
                f"Skipping {len(dropped)} queued subscription(s) no longer wanted at that mode"
            )
        if not latest:
            return

        try:
            stale = [
                sub["old_correlation_id"]
                for sub in latest.values()
                if sub.get("old_correlation_id")
            ]
            if stale:
                self.ws_client.unsubscribe_batch(stale)
                # One settle pause for the whole flush, not one per symbol.
                time.sleep(0.2)

            by_mode: dict[int, list] = {}
            for token, sub in latest.items():
                correlation_id = "mstock_" + token + "_" + str(sub["mode"])
                by_mode.setdefault(sub["mode"], []).append(
                    {
                        "correlation_id": correlation_id,
                        "token": token,
                        "exchange_type": sub["exchange_type"],
                    }
                )

            for mode, subs in by_mode.items():
                if self.ws_client.subscribe_batch(subs, mode):
                    # Confirmed at the broker: record it only now, so a failed
                    # or dropped send leaves token_modes unset and the resync
                    # (or a later subscribe) retries the token.
                    with self.lock:
                        for entry in subs:
                            self.token_correlation_ids[entry["token"]] = entry["correlation_id"]
                            self.token_modes[entry["token"]] = mode
                            self.send_retries.pop(entry["token"], None)
                    self.logger.info(f"Batch subscribed {len(subs)} token(s) in mode {mode}")
                else:
                    # Requeue rather than wait for a resync: the client is still
                    # connected, so no login is coming and nothing else would
                    # ever send these. token_modes stays unset either way.
                    with self.lock:
                        queued_tokens = {q["token"] for q in self.subscription_queue}
                        requeued, exhausted = [], []
                        for entry in subs:
                            token = entry["token"]
                            if token in queued_tokens:
                                continue
                            sub = latest.get(token)
                            if sub is None:
                                continue

                            attempts = self.send_retries.get(token, 0) + 1
                            if attempts > self.max_send_retries:
                                # Spent: leave it unconfirmed for the resync
                                # rather than re-arming the timer forever.
                                exhausted.append(token)
                                continue

                            self.send_retries[token] = attempts
                            requeued.append(token)
                            self.subscription_queue.append(
                                {
                                    "token": token,
                                    "mode": mode,
                                    "exchange_type": entry["exchange_type"],
                                    "symbol": sub["symbol"],
                                    "exchange": sub["exchange"],
                                    "old_correlation_id": None,
                                }
                            )
                        if self.subscription_queue and self.batch_timer is None:
                            self._start_batch_timer()

                    if requeued:
                        self.logger.warning(
                            f"Batch subscription failed for {len(subs)} token(s) in mode {mode}; "
                            f"requeued {len(requeued)} (attempt "
                            f"{max(self.send_retries[t] for t in requeued)} of "
                            f"{self.max_send_retries})"
                        )
                    if exhausted:
                        self.logger.error(
                            f"Giving up sending {len(exhausted)} token(s) in mode {mode} after "
                            f"{self.max_send_retries} attempts; left unconfirmed for the resync"
                        )

        except Exception as e:
            self.logger.exception(f"Error processing subscription batch: {str(e)}")

    def unsubscribe(self, symbol: str, exchange: str, mode: int = 2) -> dict[str, Any]:
        correlation_id = f"{symbol}_{exchange}_{mode}"

        needs_ws_update = False
        new_mode = 0
        token = None
        exchange_type = None

        with self.lock:
            if correlation_id not in self.subscriptions:
                return self._create_error_response(
                    "NOT_SUBSCRIBED", f"{symbol} on {exchange} mode {mode} is not subscribed"
                )

            subscription = self.subscriptions[correlation_id]
            token = subscription["token"]
            exchange_type = subscription["exchange_type"]

            del self.subscriptions[correlation_id]

            max_mode_for_token = 0
            for sub in self.subscriptions.values():
                if sub["token"] == token:
                    max_mode_for_token = max(max_mode_for_token, sub["mode"])

            # Drop any entry still waiting in the coalescing window. Without
            # this, a subscribe followed by an unsubscribe inside the 500ms
            # window clears local state but leaves the queued entry, so the
            # flush would still subscribe the token at mStock and every tick
            # would arrive for a token this adapter no longer tracks.
            if max_mode_for_token == 0:
                self.subscription_queue = [
                    queued for queued in self.subscription_queue if queued["token"] != token
                ]
                # Drop the retry budget with the subscription. Kept, a token
                # that had exhausted it would come back already spent, so a
                # later subscribe got its one send and no retry at all - and
                # the dict would grow a permanent entry per token ever seen.
                self.send_retries.pop(token, None)

            current_mstock_mode = self.token_modes.get(token, 0)
            if max_mode_for_token < current_mstock_mode:
                needs_ws_update = True
                new_mode = max_mode_for_token
                if new_mode > 0:
                    self.token_modes[token] = new_mode
                else:
                    self.token_modes.pop(token, None)
                    self.token_correlation_ids.pop(token, None)

        if needs_ws_update and self.ws_client and self.running:
            try:
                current_correlation_id = self.token_correlation_ids.get(token)

                if new_mode == 0:
                    if current_correlation_id:
                        self.ws_client.unsubscribe_stream(current_correlation_id)
                        self.logger.info(f"Unsubscribed token {token} from mstock")
                else:
                    if (
                        current_correlation_id
                        and current_correlation_id in self.ws_client.subscriptions
                    ):
                        self.ws_client.unsubscribe_stream(current_correlation_id)
                        time.sleep(0.2)

                    new_correlation_id = f"mstock_{token}_{new_mode}"
                    self.ws_client.subscribe_stream(
                        new_correlation_id, token, exchange_type, new_mode
                    )
                    self.token_correlation_ids[token] = new_correlation_id
                    self.logger.debug(
                        f"Downgraded subscription for token {token} to mode {new_mode}"
                    )

            except Exception as e:
                self.logger.exception(f"Error updating WebSocket subscription: {str(e)}")

        return {
            "status": "success",
            "message": f"Unsubscribed from {symbol} on {exchange} mode {mode}",
        }

    def _create_error_response(self, error_code: str, message: str) -> dict[str, Any]:
        return {"status": "error", "error_code": error_code, "message": message}

    def get_subscriptions(self) -> list[dict[str, Any]]:
        with self.lock:
            return [
                {
                    "symbol": sub["symbol"],
                    "exchange": sub["exchange"],
                    "mode": sub["mode"],
                    "depth_level": sub.get("depth_level", 5),
                }
                for sub in self.subscriptions.values()
            ]
