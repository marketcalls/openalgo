"""Pocketful market-data adapter for the OpenAlgo websocket proxy.

Socket and authentication
-------------------------
``wss://algo.pocketful.in/ws/v1/feeds?login_id=<client id>&access_token=<token>``

The docs page connecting-websockets.md names ``wss://algo.pocketful.in/api/v1/ws``
and says only to "include your access token in the connection handshake or
subsequent authentication message": no header, parameter or message is given.
Both of Pocketful's SDKs connect to ``/ws/v1/feeds`` with the client id and the
access token as query parameters, on the host of their REST calls (Python SDK
0.1.2: pocketfulwebsocket.py base_url and wsclient.py socket_connect;
JavaScript SDK: pocketfulwebsocket.js and wsclient.js socketConnect). Pocketful
moved that host from trade.pocketful.in to algo.pocketful.in in the JavaScript
SDK's commit 894e597c ("updated websocket base url", 2026-06-09) and kept the
path and both parameters. That form is the only one either source specifies in
full, so it is the one used. The URL carries the token and is never logged.

The client id and the access token both come from the stored session token,
``<client_id>:::<access_token>`` (broker/pocketful/api/baseurl.py). OpenAlgo's
own user id is the OpenAlgo login name, not the Pocketful client id, and is
never sent as one (this adapter used to send it as ``login_id``).

The address, the subscribe, unsubscribe and heartbeat messages and the packet
layouts live in broker/pocketful/api/packet_decoder.py, each with its source.

OpenAlgo modes (docs/prompt/websockets-format.md)
-------------------------------------------------
* LTP (1) from compact packets: ``ltp``, ``timestamp``.
* Quote (2) from detailed packets: ``ltp``, ``change``, ``change_percent``,
  ``volume``, ``open``, ``high``, ``low``, ``close``, ``last_trade_quantity``,
  ``avg_trade_price``, ``timestamp``, plus ``bid_price``, ``ask_price``,
  ``bid_size``, ``ask_size`` and ``oi``, which the packet also carries.
* Depth (3) from snapquote packets: ``depth.buy`` and ``depth.sell`` (five
  levels of price, quantity, orders), ``timestamp`` and the packet's OHLC,
  volume, average price and total quantities. A snapquote packet has no last
  traded price, so a Depth subscription also takes the instrument's compact
  packets and its frame carries the latest price from them (or from detailed
  packets). Until one has arrived the frame has no ``ltp`` at all: the average
  price is not a last traded price, and publishing it as one fed a wrong price
  to every consumer of the depth stream, the sandbox engine among them.

A price of zero means the feed has none yet (no trade today, an index's empty
book side aside) and is left out rather than published as a price.
"""

import threading
import time
import types
from collections import deque
from typing import Any

import websocket

from broker.pocketful.api.baseurl import client_id as stored_client_id
from broker.pocketful.api.baseurl import split_token
from broker.pocketful.api.packet_decoder import (
    CHANNEL_NAMES,
    COMPACT_MODE,
    DETAILED_MODE,
    HEARTBEAT_MESSAGE,
    HEARTBEAT_SECONDS,
    SNAPQUOTE_MODE,
    decodeCompactMarketData,
    decodeDetailedMarketData,
    decodeSnapquoteData,
    feed_message,
    feed_url,
    packet_mode,
)
from database.auth_db import get_auth_token
from utils import runtime as _runtime
from utils.logging import get_logger
from websocket_proxy.base_adapter import BaseBrokerWebSocketAdapter
from websocket_proxy.mapping import SymbolMapper

from .pocketful_mapping import PocketfulExchangeMapper

_real_threading = _runtime.original("threading")

# The feed channels each OpenAlgo mode needs. The first carries the mode's
# data; Depth also takes compact packets for the last traded price.
MODE_CHANNELS = {
    1: (COMPACT_MODE,),
    2: (DETAILED_MODE,),
    3: (SNAPQUOTE_MODE, COMPACT_MODE),
}
MODE_LABELS = {1: "LTP", 2: "QUOTE", 3: "DEPTH"}

# Paise to rupees: the docs' samples for NSE token 1333 carry 144895 for 1448.95.
PRICE_DIVISOR = 100.0
DEPTH_LEVELS = 5


def feed_credentials(token: str | None) -> tuple[str | None, str | None]:
    """(client id, access token) for a stored session token.

    The client id is the one packed into the token; for a bare token, the one
    the login stored with the session (baseurl.client_id).
    """
    if not token:
        return None, None
    access = split_token(token)[1]
    if not access:
        return None, None
    return stored_client_id(token), access


def _price(value: int) -> float | None:
    return value / PRICE_DIVISOR if value and value > 0 else None


def _now_ms() -> int:
    return int(time.time() * 1000)


class PocketfulWebSocketAdapter(BaseBrokerWebSocketAdapter):
    """Pocketful's market-data feed, published to the ZeroMQ bus."""

    BATCH_DELAY = 0.5
    HEALTH_CHECK_INTERVAL = 30
    DATA_SILENCE_TIMEOUT = 90
    DATA_ARM_BUCKET = 30
    DATA_ARM_BUCKETS = 3
    DATA_ARM_WINDOW = 300

    # Read on every packet without the lock, so each is replaced whole, never
    # changed in place. Class defaults keep an adapter built without __init__
    # (as the thread tests build one) working.
    _routes = types.MappingProxyType({})
    _depth_instruments = frozenset()
    _socket_generation = 0

    def __init__(self):
        super().__init__()
        self.logger = get_logger("pocketful_websocket")
        self.ws_client = None
        self.user_id = None
        self.broker_name = "pocketful"
        self.access_token = None
        self.reconnect_delay = 5  # Initial delay in seconds
        self.max_reconnect_delay = 60  # Maximum delay in seconds
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 10
        self.running = False
        self.lock = _real_threading.Lock()
        self.heartbeat_thread = None
        self._heartbeat_stop = None
        self._connect_thread = None
        self._reconnect_stop = threading.Event()
        self.subscription_queue = {}
        self.batch_timer = None
        self.health_thread = None
        self._health_stop = None
        self._last_data_message_time = None
        self._data_watchdog_armed = False
        self._data_bucket_starts = deque(maxlen=self.DATA_ARM_BUCKETS)
        # Per socket: the channels the broker has confirmed sending, the ones
        # whose subscribe is on its way (True once an unsubscribe wants it
        # dropped when the subscribe returns), and the last traded price, in
        # paise, of each instrument a Depth subscription holds.
        self._broker_channels = set()
        self._inflight = {}
        self._last_ltp = {}

    def initialize(
        self, broker_name: str, user_id: str, auth_data: dict[str, str] | None = None
    ) -> None:
        """Read the session for ``user_id`` (or take ``auth_data``) and get ready to connect.

        Raises:
            ValueError: no Pocketful session is stored, or it carries no client id.
        """
        self.user_id = user_id
        self.broker_name = broker_name

        if auth_data:
            token = auth_data.get("auth_token") or auth_data.get("access_token")
        else:
            token = get_auth_token(user_id, bypass_cache=True)
        if not token:
            self.logger.error(f"No Pocketful session is stored for user {user_id}")
            raise ValueError("No Pocketful session was found. Log in to Pocketful again.")

        client, access = feed_credentials(token)
        if not client or not access:
            self.logger.error(f"The Pocketful session for user {user_id} carries no client id")
            raise ValueError(
                "The Pocketful session is missing its client ID. Log in to Pocketful again."
            )

        self.access_token = token
        self.running = True
        self.logger.info(f"Pocketful feed adapter initialized for user {user_id}")

    def connect(self) -> None:
        """Start the connection thread, unless one is already running."""
        if not self.access_token:
            self.logger.error("Pocketful feed adapter is not initialized. Call initialize() first.")
            return

        with self.lock:
            if (
                self._connect_thread is not None
                and self._connect_thread.is_alive()
                and not self._reconnect_stop.is_set()
            ):
                return
            # A prior disconnect can still be finishing its old loop. Give
            # this connection its own stop signal so a new login cannot revive
            # the old loop by clearing a shared Event.
            stop_event = threading.Event()
            self._reconnect_stop = stop_event
            self._connect_thread = threading.Thread(
                target=self._connect_with_retry,
                args=(stop_event,),
                daemon=True,
                name="pocketful-market-reconnect",
            )
            self._connect_thread.start()

    def _backoff(self) -> float:
        self.reconnect_attempts += 1
        return min(self.reconnect_delay * (2**self.reconnect_attempts), self.max_reconnect_delay)

    def _connect_with_retry(self, stop_event: threading.Event | None = None) -> None:
        """Connect, and reconnect with backoff until stopped or out of attempts."""
        if stop_event is None:
            stop_event = self._reconnect_stop
        while (
            self.running
            and not stop_event.is_set()
            and self.reconnect_attempts < self.max_reconnect_attempts
        ):
            try:
                self.logger.info(
                    f"Connecting to the Pocketful feed (attempt {self.reconnect_attempts + 1})"
                )

                # Re-read the session before every connection: Indian broker
                # tokens roll over daily at about 3 AM IST, so a reconnect
                # after that must not reuse the token it started with.
                fresh_token = get_auth_token(self.user_id, bypass_cache=True)
                if fresh_token:
                    self.access_token = fresh_token
                else:
                    self.logger.warning(
                        "Could not read a fresh Pocketful session; reusing the current one"
                    )
                if not self.running or stop_event.is_set():
                    break

                client, access = feed_credentials(self.access_token)
                if not client or not access:
                    delay = self._backoff()
                    self.logger.error(
                        "The Pocketful session is missing its client ID, so live prices "
                        f"cannot start. Log in to Pocketful again. Checking again in {delay} seconds."
                    )
                    if stop_event.wait(delay):
                        break
                    continue
                ws_url = feed_url(client, access)

                # A logout may have landed during the session read. Publish
                # the socket under the same short lock disconnect() uses, so
                # it cannot appear after disconnect already looked for one.
                with self.lock:
                    if not self.running or stop_event.is_set():
                        break
                    ws_client = websocket.WebSocketApp(
                        ws_url,
                        on_message=self._on_message,
                        on_error=self._on_error,
                        on_close=self._on_close,
                        on_open=self._on_open,
                    )
                    self.ws_client = ws_client

                if not self.running or stop_event.is_set():
                    ws_client.close()
                    break
                ws_client.run_forever()

                # run_forever returned: the connection closed.
                if not self.running or stop_event.is_set():
                    break

                delay = self._backoff()
                self.logger.warning(f"Pocketful feed connection lost. Retrying in {delay} seconds.")
                if stop_event.wait(delay):
                    break

            except Exception:
                delay = self._backoff()
                self.logger.exception(
                    f"Pocketful feed connection failed. Retrying in {delay} seconds."
                )
                if stop_event.wait(delay):
                    break

        if self.reconnect_attempts >= self.max_reconnect_attempts:
            self.logger.error(
                f"Pocketful feed: gave up after {self.reconnect_attempts} connection attempts"
            )

    def disconnect(self) -> None:
        """Stop every thread, close the socket and release the ZeroMQ publisher."""
        with self.lock:
            self.running = False
            self.connected = False
            self._reconnect_stop.set()
            if self._heartbeat_stop is not None:
                self._heartbeat_stop.set()
            if self._health_stop is not None:
                self._health_stop.set()
            if self.batch_timer is not None:
                self.batch_timer.cancel()
                self.batch_timer = None
            self.subscription_queue.clear()
            self._broker_channels = set()
            self._inflight = {}
            self._last_ltp = {}
            ws_client = self.ws_client
        if ws_client is not None:
            ws_client.close()

        self.cleanup_zmq()

    # ------------------------------------------------------------------ subscriptions

    def subscribe(
        self, symbol: str, exchange: str, mode: int = 2, depth_level: int = 5
    ) -> dict[str, Any]:
        """Subscribe to LTP (1), Quote (2) or Depth (3) for one instrument."""
        if mode not in MODE_CHANNELS:
            return self._create_error_response(
                "INVALID_MODE", f"Mode {mode} is not available. Choose LTP, Quote or Depth."
            )
        if mode == 3:
            try:
                levels = int(depth_level)
            except (TypeError, ValueError):
                levels = None
            if levels != DEPTH_LEVELS:
                return self._create_error_response(
                    "INVALID_DEPTH",
                    f"Pocketful streams {DEPTH_LEVELS} levels of market depth; "
                    f"{depth_level} levels are not available.",
                )

        token_info = SymbolMapper.get_token_from_symbol(symbol, exchange)
        if not token_info:
            return self._create_error_response(
                "SYMBOL_NOT_FOUND", f"{symbol} was not found on {exchange}."
            )
        try:
            token = int(str(token_info["token"]).strip())
        except (KeyError, TypeError, ValueError):
            self.logger.error(f"Pocketful token for {symbol} on {exchange} is not numeric")
            return self._create_error_response(
                "SYMBOL_NOT_FOUND", f"{symbol} on {exchange} has no Pocketful instrument token."
            )

        exchange_code = PocketfulExchangeMapper.get_exchange_code(exchange)
        if exchange_code is None:
            return self._create_error_response(
                "EXCHANGE_NOT_SUPPORTED", f"Pocketful does not stream live prices for {exchange}."
            )

        correlation_id = f"{symbol}_{exchange}_{mode}"
        if mode == 3:
            correlation_id = f"{correlation_id}_{depth_level}"
        channels = MODE_CHANNELS[mode]
        subscription = {
            "symbol": symbol,
            "exchange": exchange,
            "brexchange": token_info.get("brexchange"),
            "token": token,
            "mode": mode,
            "pocketful_mode": channels[0],
            "channels": channels,
            "exchange_code": exchange_code,
            "depth_level": depth_level,
            "actual_depth": DEPTH_LEVELS if mode == 3 else depth_level,
            "is_fallback": False,
        }

        with self.lock:
            self.subscriptions[correlation_id] = subscription
            self._publish_routes_locked()
            if self.connected and self.ws_client:
                self.subscription_queue[correlation_id] = subscription
                self._start_batch_timer_locked()

        return self._create_success_response(
            "Subscription requested",
            symbol=symbol,
            exchange=exchange,
            mode=mode,
            requested_depth=depth_level,
            actual_depth=subscription["actual_depth"],
            is_fallback=False,
        )

    def unsubscribe(self, symbol: str, exchange: str, mode: int = 2) -> dict[str, Any]:
        """Unsubscribe one mode of one instrument; the broker keeps channels others need."""
        prefix = f"{symbol}_{exchange}_{mode}"
        drop = []
        with self.lock:
            correlation_id = prefix
            for key, sub in self.subscriptions.items():
                if (
                    (key == prefix or key.startswith(prefix + "_"))
                    and sub["symbol"] == symbol
                    and sub["exchange"] == exchange
                    and sub["mode"] == mode
                ):
                    correlation_id = key
                    break
            removed = self.subscriptions.pop(correlation_id, None)
            self.subscription_queue.pop(correlation_id, None)
            if removed is not None:
                self._publish_routes_locked()
                drop = self._release_channels_locked(removed)
            ws_client = self.ws_client if self.connected else None

        if drop and ws_client is not None:
            try:
                self._send_channels("unsubscribe", drop, ws_client)
            except Exception:
                self.logger.exception(f"Could not unsubscribe {symbol} on {exchange} at Pocketful")
                return self._create_error_response(
                    "UNSUBSCRIPTION_ERROR",
                    f"Could not stop live prices for {symbol} on {exchange}. Try again.",
                )

        return self._create_success_response(
            f"Unsubscribed from {symbol}.{exchange}", symbol=symbol, exchange=exchange, mode=mode
        )

    @staticmethod
    def _channels_of(sub: dict) -> tuple:
        return sub.get("channels") or (sub["pocketful_mode"],)

    def _needed_channels_locked(self) -> set:
        needed = set()
        for sub in self.subscriptions.values():
            code, token = sub["exchange_code"], int(sub["token"])
            for channel in self._channels_of(sub):
                needed.add((channel, code, token))
        return needed

    def _release_channels_locked(self, removed: dict) -> list:
        """Channels of a removed subscription that no other one needs.

        Returns the ones the broker is sending, to unsubscribe now. One whose
        subscribe is still on its way is marked, and dropped when it returns.
        """
        needed = self._needed_channels_locked()
        code, token = removed["exchange_code"], int(removed["token"])
        drop = []
        for mode in self._channels_of(removed):
            channel = (mode, code, token)
            if channel in needed:
                continue
            if channel in self._broker_channels:
                self._broker_channels.discard(channel)
                drop.append(channel)
            elif channel in self._inflight:
                self._inflight[channel] = True
        return drop

    def _publish_routes_locked(self) -> None:
        """Rebuild what the packet handlers read: topics per channel, Depth instruments.

        Also drops the cached price of an instrument no Depth subscription
        holds any more.
        """
        routes = {}
        depth_instruments = set()
        for sub in self.subscriptions.values():
            mode = sub["mode"]
            channels = MODE_CHANNELS.get(mode)
            if not channels:
                continue
            instrument = (sub["exchange_code"], int(sub["token"]))
            topic = f"{sub['exchange']}_{sub['symbol']}_{MODE_LABELS[mode]}"
            routes.setdefault((channels[0], *instrument), {})[topic] = None
            if mode == 3:
                depth_instruments.add(instrument)
        self._routes = types.MappingProxyType({key: tuple(t) for key, t in routes.items()})
        self._depth_instruments = frozenset(depth_instruments)
        for instrument in [key for key in self._last_ltp if key not in depth_instruments]:
            del self._last_ltp[instrument]

    def _start_batch_timer_locked(self) -> None:
        if self.batch_timer is not None and self.batch_timer.is_alive():
            return
        self.batch_timer = _real_threading.Timer(
            self.BATCH_DELAY, self._process_batch_subscriptions
        )
        self.batch_timer.daemon = True
        self.batch_timer.start()

    def _process_batch_subscriptions(self) -> None:
        """Send the queued subscriptions, one message per channel and exchange."""
        with self.lock:
            self.batch_timer = None
            if not self.connected or not self.ws_client or not self.subscription_queue:
                return
            ws_client = self.ws_client
            generation = self._socket_generation
            queued = list(self.subscription_queue.items())
            self.subscription_queue.clear()
            groups = {}
            for correlation_id, sub in queued:
                code, token = sub["exchange_code"], int(sub["token"])
                for mode in self._channels_of(sub):
                    instruments, subs = groups.setdefault((mode, code), ({}, {}))
                    subs[correlation_id] = sub
                    channel = (mode, code, token)
                    if channel in self._broker_channels or channel in self._inflight:
                        continue
                    instruments[token] = [code, token]
                    self._inflight[channel] = False

        for (mode, code), (instruments, subs) in groups.items():
            if not instruments:
                continue
            try:
                self._send_subscription_batch(list(instruments.values()), mode, ws_client)
            except Exception:
                self.logger.exception(
                    f"Pocketful batch subscription failed for {CHANNEL_NAMES.get(mode, mode)}"
                )
                with self.lock:
                    if generation != self._socket_generation:
                        continue  # the new socket resubscribed everything
                    for token in instruments:
                        self._inflight.pop((mode, code, token), None)
                    for correlation_id, sub in subs.items():
                        if self.subscriptions.get(correlation_id) is sub:
                            self.subscription_queue[correlation_id] = sub
                    if self.connected and self.subscription_queue:
                        self._start_batch_timer_locked()
                continue

            stale = []
            with self.lock:
                if generation != self._socket_generation:
                    continue
                needed = None
                for token in instruments:
                    channel = (mode, code, token)
                    if self._inflight.pop(channel, False):
                        if needed is None:
                            needed = self._needed_channels_locked()
                        if channel not in needed:
                            stale.append(channel)
                            continue
                    self._broker_channels.add(channel)
            if stale:
                try:
                    self._send_channels("unsubscribe", stale, ws_client)
                except Exception:
                    self.logger.exception("Could not unsubscribe released Pocketful instruments")

    def _send_subscription_batch(self, instruments, mode: int, ws=None) -> None:
        (ws or self.ws_client).send(feed_message("subscribe", instruments, mode))
        self.logger.info(
            f"Sent subscribe for {len(instruments)} instruments on {CHANNEL_NAMES[mode]}"
        )

    def _send_channels(self, action: str, channels, ws) -> None:
        """Send one ``action`` message per feed channel for (mode, code, token) entries."""
        by_mode = {}
        for mode, code, token in channels:
            by_mode.setdefault(mode, []).append([code, token])
        for mode, instruments in by_mode.items():
            ws.send(feed_message(action, instruments, mode))
            self.logger.info(
                f"Sent {action} for {len(instruments)} instruments on {CHANNEL_NAMES[mode]}"
            )

    # ------------------------------------------------------------------ socket callbacks

    def _on_open(self, ws) -> None:
        """Start this socket's heartbeat and watchdog, and resubscribe everything."""
        with self.lock:
            # websocket-client may invoke on_open even when disconnect closed
            # this socket just before run_forever began. Never start a
            # heartbeat for a revoked or obsolete connection.
            if not self.running or self._reconnect_stop.is_set() or ws is not self.ws_client:
                stale = True
            else:
                stale = False
                self.connected = True
                self.reconnect_attempts = 0
                if self._heartbeat_stop is not None:
                    self._heartbeat_stop.set()
                stop_event = threading.Event()
                self._heartbeat_stop = stop_event
                if self._health_stop is not None:
                    self._health_stop.set()
                health_stop = _real_threading.Event()
                self._health_stop = health_stop
                self._last_data_message_time = None
                self._data_watchdog_armed = False
                self._data_bucket_starts.clear()
                # A new socket starts with nothing subscribed and no prices.
                self._socket_generation += 1
                self._broker_channels = set()
                self._inflight = {}
                self._last_ltp = {}
                current_ws = self.ws_client
        if stale:
            ws.close()
            return

        self.logger.info("Connected to the Pocketful feed")
        self.heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            args=(stop_event, current_ws),
            daemon=True,
            name="pocketful-market-heartbeat",
        )
        self.heartbeat_thread.start()

        self.health_thread = _real_threading.Thread(
            target=self._health_check_loop,
            args=(health_stop, current_ws),
            daemon=True,
            name="pocketful-market-health",
        )
        self.health_thread.start()

        with self.lock:
            self.subscription_queue.update(self.subscriptions)
            if self.subscription_queue:
                self._start_batch_timer_locked()

    def _on_error(self, ws, error) -> None:
        self.logger.error(f"Pocketful feed error: {error}")

    def _on_close(self, ws, close_status_code=None, close_msg=None) -> None:
        self.logger.info(
            f"Pocketful feed connection closed: code={close_status_code}, message={close_msg}"
        )
        with self.lock:
            if ws is self.ws_client:
                self.connected = False
                if self._heartbeat_stop is not None:
                    self._heartbeat_stop.set()
                if self._health_stop is not None:
                    self._health_stop.set()

    def _on_message(self, ws, message) -> None:
        """Route one binary packet by its mode byte."""
        try:
            mode = packet_mode(message)
            if mode == COMPACT_MODE:
                self._handle_compact_data(message)
            elif mode == DETAILED_MODE:
                self._handle_detailed_data(message)
            elif mode == SNAPQUOTE_MODE:
                self._handle_snapquote_data(message)
            elif mode is None and isinstance(message, str):
                self.logger.debug(f"Pocketful feed sent a text message: {message[:200]}")
        except Exception:
            self.logger.exception("Error processing a Pocketful feed message")

    # ------------------------------------------------------------------ packets

    def _note_ltp(self, instrument: tuple, ltp: int) -> None:
        """Keep the last traded price of an instrument a Depth subscription holds."""
        if ltp <= 0 or instrument not in self._depth_instruments:
            return
        with self.lock:
            if instrument in self._depth_instruments:
                self._last_ltp[instrument] = ltp

    def _handle_compact_data(self, message) -> None:
        """Compact packet: the LTP of LTP subscriptions, and the price for Depth."""
        res = decodeCompactMarketData(message)
        if not res:
            return
        self._record_market_data()
        instrument = (res["exchange_code"], res["instrument_token"])
        ltp = res["last_traded_price"]
        self._note_ltp(instrument, ltp)

        topics = self._routes.get((COMPACT_MODE, *instrument))
        if not topics or ltp <= 0:
            return
        data = {"ltp": ltp / PRICE_DIVISOR, "timestamp": _now_ms()}
        for topic in topics:
            self.publish_market_data(topic, data)

    def _handle_detailed_data(self, message) -> None:
        """Detailed packet: the frame of Quote subscriptions."""
        res = decodeDetailedMarketData(message)
        if not res:
            return
        self._record_market_data()
        instrument = (res["exchange_code"], res["instrument_token"])
        ltp = res["last_traded_price"]
        self._note_ltp(instrument, ltp)

        topics = self._routes.get((DETAILED_MODE, *instrument))
        if not topics:
            return
        close = res["close_price"]
        data = {
            "volume": res["trade_volume"],
            "last_trade_quantity": res["last_traded_quantity"],
            "bid_price": res["best_bid_price"] / PRICE_DIVISOR,
            "bid_size": res["best_bid_quantity"],
            "ask_price": res["best_ask_price"] / PRICE_DIVISOR,
            "ask_size": res["best_ask_quantity"],
            "oi": res["currentOpenInterest"],
            "timestamp": _now_ms(),
        }
        for key, field in (
            ("ltp", "last_traded_price"),
            ("open", "open_price"),
            ("high", "high_price"),
            ("low", "low_price"),
            ("close", "close_price"),
            ("avg_trade_price", "average_trade_price"),
        ):
            value = _price(res[field])
            if value is not None:
                data[key] = value
        if ltp > 0 and close > 0:
            data["change"] = (ltp - close) / PRICE_DIVISOR
            data["change_percent"] = round((ltp - close) * 100 / close, 2)
        for topic in topics:
            self.publish_market_data(topic, data)

    def _handle_snapquote_data(self, message) -> None:
        """Snapquote packet: the five-level book of Depth subscriptions."""
        res = decodeSnapquoteData(message)
        if not res:
            return
        self._record_market_data()
        instrument = (res["exchange_code"], res["instrument_token"])
        topics = self._routes.get((SNAPQUOTE_MODE, *instrument))
        if not topics:
            return

        data = {
            "depth": {
                "buy": self._levels(res["bidPrices"], res["bidQtys"], res["buyers"]),
                "sell": self._levels(res["askPrices"], res["askQtys"], res["sellers"]),
            },
            "volume": res["volume"],
            "totalbuyqty": res["totalBuyQty"],
            "totalsellqty": res["totalSellQty"],
            "timestamp": _now_ms(),
        }
        ltp = _price(self._last_ltp.get(instrument, 0))
        if ltp is not None:
            data["ltp"] = ltp
        for key, field in (
            ("open", "open"),
            ("high", "high"),
            ("low", "low"),
            ("close", "close"),
            ("avg_trade_price", "averageTradePrice"),
        ):
            value = _price(res[field])
            if value is not None:
                data[key] = value
        for topic in topics:
            self.publish_market_data(topic, data)

    @staticmethod
    def _levels(prices, quantities, orders) -> list[dict[str, Any]]:
        return [
            {"price": price / PRICE_DIVISOR, "quantity": quantity, "orders": count}
            for price, quantity, count in zip(
                prices[:DEPTH_LEVELS], quantities[:DEPTH_LEVELS], orders[:DEPTH_LEVELS], strict=True
            )
        ]

    # ------------------------------------------------------------------ liveness

    def _heartbeat_loop(self, stop_event: threading.Event, current_ws) -> None:
        """Send the SDK's heartbeat every eight seconds while this socket is current."""
        while self.running and self.connected and not stop_event.is_set():
            if self.ws_client is current_ws:
                try:
                    current_ws.send(HEARTBEAT_MESSAGE)
                    self.logger.debug("Pocketful feed heartbeat sent")
                except Exception:
                    # As the SDK does: a heartbeat that cannot be sent means the
                    # socket is gone, and its close starts the reconnect.
                    self.logger.exception("Could not send the Pocketful feed heartbeat")
                    return
            if stop_event.wait(HEARTBEAT_SECONDS):
                break

    def _record_market_data(self) -> None:
        now = time.monotonic()
        with self.lock:
            self._last_data_message_time = now
            if self._data_watchdog_armed:
                return
            bucket = now - (now % self.DATA_ARM_BUCKET)
            if not self._data_bucket_starts or self._data_bucket_starts[-1] != bucket:
                self._data_bucket_starts.append(bucket)
            recent = [
                start for start in self._data_bucket_starts if now - start <= self.DATA_ARM_WINDOW
            ]
            self._data_bucket_starts = deque(recent, maxlen=self.DATA_ARM_BUCKETS)
            if len(self._data_bucket_starts) >= self.DATA_ARM_BUCKETS:
                self._data_watchdog_armed = True
                self.logger.info("Pocketful market-data silence watchdog armed")

    def _health_check_loop(self, stop_event, current_ws) -> None:
        while self.running and not stop_event.wait(self.HEALTH_CHECK_INTERVAL):
            with self.lock:
                if current_ws is not self.ws_client or not self.connected:
                    return
                silent_for = (
                    time.monotonic() - self._last_data_message_time
                    if self._last_data_message_time is not None
                    else None
                )
                should_close = (
                    self._data_watchdog_armed
                    and silent_for is not None
                    and silent_for >= self.DATA_SILENCE_TIMEOUT
                )
            if should_close:
                self.logger.warning(
                    "Pocketful market data stalled for %.0f seconds; closing socket to reconnect",
                    silent_for,
                )
                try:
                    current_ws.close()
                except Exception:
                    self.logger.exception("Error closing the stalled Pocketful socket")
                return
