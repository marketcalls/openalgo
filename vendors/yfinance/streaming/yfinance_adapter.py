"""yfinance WebSocket streaming adapter.

Bridges Yahoo Finance's native streamer into OpenAlgo's WebSocket proxy.
The broker-WS contract is identical (BaseBrokerWebSocketAdapter), so the
proxy server (websocket_proxy/server.py) and ZMQ topic shape
(EXCHANGE_SYMBOL_MODE) remain unchanged.

Runtime constraints (per CLAUDE.md):

* **No asyncio anywhere in this adapter.** Production runs under
  gunicorn + eventlet (`--worker-class eventlet -w 1`), where
  `asyncio.run()` / `asyncio.get_event_loop()` are incompatible with the
  eventlet hub. The yfinance library exposes both a sync `yf.WebSocket`
  (built on `websocket-client`, blocking sync sockets) and an async
  `yf.AsyncWebSocket` (asyncio-based). We use ONLY the sync `yf.WebSocket`.
* **Listener runs on a real OS thread**, not an eventlet greenlet, by
  pulling the unpatched `threading` module via `eventlet.patcher.original`.
  Same pattern used in `services/telegram_bot_service.py:_render_plotly_png`
  for Kaleido. A real OS thread + sync sockets is safe under eventlet
  because the GIL releases on `socket.recv()` and the eventlet hub keeps
  serving green threads on the main thread.
* Yahoo's NSE/BSE feed is delayed ~15 minutes during market hours.
* Depth is unavailable — `subscribe(mode=4)` returns `NOT_SUPPORTED`.
* Quote mode overlays the daily OHLC snapshot (fetched once per ticker via
  `fast_info`) onto each tick because the WS payload only carries
  price / dayVolume.
"""

import sys
import time

# Use the unpatched threading module so the yfinance listener runs on a real
# OS thread, isolated from eventlet's hub. See module docstring.
if "eventlet" in sys.modules:
    import eventlet

    original_threading = eventlet.patcher.original("threading")
else:
    import threading as original_threading

from utils.logging import get_logger
from vendors.base_vendor import VendorSymbolError
from vendors.yfinance.mapping.symbol_map import to_vendor
from websocket_proxy.base_adapter import BaseBrokerWebSocketAdapter

logger = get_logger(__name__)

try:
    import yfinance as yf
except ImportError as exc:
    yf = None
    _YF_IMPORT_ERROR: Exception | None = exc
else:
    _YF_IMPORT_ERROR = None

    # Defensive sanity check: if a future yfinance version replaces the sync
    # WebSocket with an asyncio-only implementation, refuse to load this
    # adapter under eventlet rather than silently breaking in production.
    _ws_module_path = getattr(getattr(yf, "WebSocket", None), "__module__", "") or ""
    if "asyncio" in _ws_module_path.lower():
        raise RuntimeError(
            "yfinance.WebSocket appears to be an asyncio-based implementation "
            "in this yfinance version — refusing to load to avoid breaking "
            "under eventlet. Pin a yfinance version that ships the sync "
            "WebSocket (websocket-client based)."
        )


# OpenAlgo subscription modes (mirrors broker adapters)
_MODE_LTP = 1
_MODE_QUOTE = 2
_MODE_DEPTH = 4

_MODE_NAME = {_MODE_LTP: "LTP", _MODE_QUOTE: "QUOTE", _MODE_DEPTH: "DEPTH"}


class YfinanceWebSocketAdapter(BaseBrokerWebSocketAdapter):
    """Streaming adapter for Yahoo Finance via the yfinance native WebSocket."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if yf is None:
            raise RuntimeError(
                f"yfinance package is not installed. Run `uv add yfinance`. "
                f"Original import error: {_YF_IMPORT_ERROR}"
            )

        self._ws = None
        self._listen_thread: original_threading.Thread | None = None
        self._stop_event = original_threading.Event()
        self._lock = original_threading.RLock()

        # yf_ticker -> set of (symbol, exchange, mode) — multiple modes per ticker allowed
        self._symbols: dict[str, set[tuple[str, str, int]]] = {}
        # yf_ticker -> daily OHLC snapshot for QUOTE-mode overlay
        self._snapshot_cache: dict[str, dict] = {}
        # yf_ticker -> running per-session high/low derived from streamed prices
        self._session_extrema: dict[str, dict[str, float]] = {}

    # ------------------------------------------------------------------ lifecycle

    def initialize(self, broker_name, user_id, auth_data=None):
        with self._lock:
            if self._ws is not None:
                return self._create_success_response(
                    "yfinance ws already initialized", broker="yfinance"
                )
            try:
                self._ws = yf.WebSocket()
            except Exception as exc:
                self.logger.exception("Failed to construct yfinance WebSocket: %s", exc)
                return self._create_error_response("INIT_FAILED", str(exc))

            self.connected = True
            self.logger.info(
                "yfinance ws adapter initialized (user_id=%s, broker_arg=%s)",
                user_id,
                broker_name,
            )
            return self._create_success_response(
                "yfinance ws ready",
                broker="yfinance",
                capabilities={"ltp": True, "quote": True, "depth": False},
                data_delay_minutes=15,
            )

    def connect(self):
        with self._lock:
            if self._ws is None:
                return self._create_error_response("NOT_INITIALIZED", "Call initialize() first")
            if self._listen_thread and self._listen_thread.is_alive():
                return self._create_success_response("already listening")

            self._stop_event.clear()
            self._listen_thread = original_threading.Thread(
                target=self._run_listener, name="yfinance-ws-listener", daemon=True
            )
            self._listen_thread.start()
            self.logger.info("yfinance ws listener thread started")
            return self._create_success_response("connected")

    def disconnect(self):
        # Temporarily silence yfinance.live's noisy ERROR during graceful close
        # (it logs the RFC-6455 normal closure 1000 as an error). We only raise
        # the threshold for the duration of the close, then restore it.
        import logging as _logging

        yf_live_logger = _logging.getLogger("yfinance.live")
        prev_level = yf_live_logger.level
        yf_live_logger.setLevel(_logging.CRITICAL)

        with self._lock:
            self._stop_event.set()
            try:
                if self._ws is not None:
                    try:
                        self._ws.close()
                    except Exception as exc:
                        self.logger.debug("yfinance ws close raised: %s", exc)
                self._ws = None
            finally:
                self.connected = False

        # Join outside the lock so the listener can release any inner locks first.
        if self._listen_thread and self._listen_thread.is_alive():
            self._listen_thread.join(timeout=2.0)
        self._listen_thread = None

        yf_live_logger.setLevel(prev_level)

        try:
            self.cleanup_zmq()
        except Exception as exc:
            self.logger.debug("cleanup_zmq raised during disconnect: %s", exc)

        return self._create_success_response("disconnected")

    # ------------------------------------------------------------ subscribe/unsub

    def subscribe(self, symbol, exchange, mode=_MODE_QUOTE, depth_level=5):
        if mode == _MODE_DEPTH:
            return self._create_error_response(
                "NOT_SUPPORTED",
                "Market depth is not supported by data vendor 'yfinance'",
            )
        if mode not in (_MODE_LTP, _MODE_QUOTE):
            return self._create_error_response(
                "INVALID_MODE",
                f"Unsupported subscription mode {mode}. Use 1 (LTP) or 2 (QUOTE).",
            )

        try:
            yf_ticker = to_vendor(symbol, exchange)
        except VendorSymbolError as exc:
            return self._create_error_response("INVALID_SYMBOL", str(exc))

        with self._lock:
            if self._ws is None:
                return self._create_error_response("NOT_INITIALIZED", "Call initialize() first")

            new_ticker = yf_ticker not in self._symbols
            self._symbols.setdefault(yf_ticker, set()).add((symbol, exchange, mode))
            self.subscriptions[(symbol, exchange, mode)] = yf_ticker

            if new_ticker:
                try:
                    self._ws.subscribe([yf_ticker])
                    self.logger.info(
                        "yfinance ws subscribed %s (oa=%s:%s mode=%s)",
                        yf_ticker,
                        exchange,
                        symbol,
                        _MODE_NAME.get(mode, mode),
                    )
                except Exception as exc:
                    self.logger.exception(
                        "yfinance ws subscribe failed for %s: %s", yf_ticker, exc
                    )
                    self._symbols[yf_ticker].discard((symbol, exchange, mode))
                    if not self._symbols[yf_ticker]:
                        del self._symbols[yf_ticker]
                    self.subscriptions.pop((symbol, exchange, mode), None)
                    return self._create_error_response("SUBSCRIBE_FAILED", str(exc))

            if mode == _MODE_QUOTE and yf_ticker not in self._snapshot_cache:
                self._snapshot_cache[yf_ticker] = self._fetch_daily_snapshot(yf_ticker)

        return self._create_success_response(
            "subscribed",
            symbol=symbol,
            exchange=exchange,
            mode=mode,
            vendor_ticker=yf_ticker,
            capability={"depth": False},
        )

    def unsubscribe(self, symbol, exchange, mode=_MODE_QUOTE):
        try:
            yf_ticker = to_vendor(symbol, exchange)
        except VendorSymbolError as exc:
            return self._create_error_response("INVALID_SYMBOL", str(exc))

        with self._lock:
            self.subscriptions.pop((symbol, exchange, mode), None)
            holders = self._symbols.get(yf_ticker)
            if holders:
                holders.discard((symbol, exchange, mode))
                if not holders:
                    del self._symbols[yf_ticker]
                    self._snapshot_cache.pop(yf_ticker, None)
                    self._session_extrema.pop(yf_ticker, None)
                    if self._ws is not None:
                        try:
                            self._ws.unsubscribe([yf_ticker])
                        except Exception as exc:
                            self.logger.debug(
                                "yfinance ws unsubscribe failed for %s: %s", yf_ticker, exc
                            )

        return self._create_success_response(
            "unsubscribed", symbol=symbol, exchange=exchange, mode=mode
        )

    # ------------------------------------------------------------------ internals

    def _run_listener(self):
        """Thread target — yfinance's `listen` blocks until the ws closes.

        During graceful shutdown, yfinance's live.listen() catches the
        `ConnectionClosedOK` from websockets.recv() and logs it at ERROR
        level before re-raising — noisy but harmless. We swallow it silently
        when _stop_event is set.
        """
        try:
            self._ws.listen(self._on_message)
        except Exception as exc:
            if self._stop_event.is_set():
                self.logger.debug("yfinance ws listener exiting on shutdown: %s", exc)
            else:
                # Unexpected termination — log and let the disconnect path clean up.
                exc_name = type(exc).__name__
                if "ConnectionClosed" in exc_name:
                    self.logger.warning(
                        "yfinance ws closed unexpectedly (%s) — clients will need to resubscribe",
                        exc,
                    )
                else:
                    self.logger.exception("yfinance ws listener crashed: %s", exc)
        finally:
            self.logger.info("yfinance ws listener exited")

    def _on_message(self, message):
        if not isinstance(message, dict):
            return
        yf_ticker = message.get("id") or message.get("symbol")
        if not yf_ticker:
            return

        with self._lock:
            holders = list(self._symbols.get(yf_ticker, ()))
            snapshot = self._snapshot_cache.get(yf_ticker, {})

        if not holders:
            return

        try:
            ltp = float(message.get("price", 0) or 0)
        except (TypeError, ValueError):
            ltp = 0.0
        ts_ms = self._extract_timestamp_ms(message)

        # Update running session extrema for QUOTE-mode high/low overlay.
        if ltp:
            extrema = self._session_extrema.setdefault(
                yf_ticker, {"high": ltp, "low": ltp}
            )
            if ltp > extrema["high"]:
                extrema["high"] = ltp
            if ltp < extrema["low"]:
                extrema["low"] = ltp
        else:
            extrema = self._session_extrema.get(yf_ticker, {})

        try:
            day_volume = int(message.get("dayVolume") or message.get("day_volume") or 0)
        except (TypeError, ValueError):
            day_volume = 0

        for symbol, exchange, mode in holders:
            if mode == _MODE_LTP:
                payload = {
                    "exchange": exchange,
                    "symbol": symbol,
                    "ltp": ltp,
                    "timestamp": ts_ms,
                }
                topic = f"{exchange}_{symbol}_LTP"
            else:  # QUOTE
                snap_high = float(snapshot.get("high") or 0)
                snap_low = float(snapshot.get("low") or 0)
                running_high = max(snap_high, extrema.get("high", ltp) or ltp)
                running_low = (
                    min(snap_low, extrema.get("low", ltp) or ltp)
                    if snap_low
                    else (extrema.get("low", ltp) or ltp)
                )
                payload = {
                    "exchange": exchange,
                    "symbol": symbol,
                    "ltp": ltp,
                    "open": float(snapshot.get("open") or 0),
                    "high": running_high,
                    "low": running_low,
                    "close": float(snapshot.get("prev_close") or 0),
                    "volume": day_volume or int(snapshot.get("volume") or 0),
                    "timestamp": ts_ms,
                }
                topic = f"{exchange}_{symbol}_QUOTE"

            try:
                self.publish_market_data(topic, payload)
            except Exception as exc:
                self.logger.debug("publish failed for topic %s: %s", topic, exc)

    @staticmethod
    def _extract_timestamp_ms(message: dict) -> int:
        ts = message.get("time") or message.get("timestamp")
        if ts is None:
            return int(time.time() * 1000)
        try:
            ts_int = int(ts)
        except (TypeError, ValueError):
            return int(time.time() * 1000)
        # Yahoo sometimes ships seconds, sometimes ms — normalize to ms.
        return ts_int if ts_int > 10**12 else ts_int * 1000

    def _fetch_daily_snapshot(self, yf_ticker: str) -> dict:
        try:
            info = yf.Ticker(yf_ticker).fast_info
        except Exception as exc:
            self.logger.debug("snapshot fetch failed for %s: %s", yf_ticker, exc)
            return {}

        def _get(*keys):
            for key in keys:
                try:
                    value = info[key] if hasattr(info, "__getitem__") else getattr(info, key, None)
                except (KeyError, AttributeError, TypeError):
                    value = None
                if value is not None:
                    return value
            return None

        return {
            "open": _get("open", "regularMarketOpen") or 0,
            "high": _get("day_high", "dayHigh") or 0,
            "low": _get("day_low", "dayLow") or 0,
            "prev_close": _get("previous_close", "previousClose") or 0,
            "volume": _get("last_volume", "regularMarketVolume", "volume") or 0,
        }
