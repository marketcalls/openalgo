"""Nuvama market data adapter -> OpenAlgo unified streaming.

Modes: 1 (LTP) and 2 (Quote) subscribe Nuvama's reduced quote stream
(``quote``); 3 (Depth) adds the depth stream (``quote2``), whose packets carry
only the five levels, so a depth tick is the latest quote merged with the
latest depth. Indices stream like any instrument, by their master contract
token (``-29``).
"""

import threading
import time
from datetime import datetime

from broker.nuvama.api.baseurl import parse_token
from broker.nuvama.streaming.nuvama_mapping import topic_mode
from broker.nuvama.streaming.nuvama_socket import NuvamaStreamClient
from database.auth_db import get_auth_token
from database.token_db import get_token
from websocket_proxy.base_adapter import BaseBrokerWebSocketAdapter


def _f(value):
    if value in (None, "", "--"):
        return 0.0
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return 0.0


def _i(value):
    return int(_f(value))


def _epoch_ms(text):
    """'21 Jul 2023, 12:44:55 PM' or '21/07/2023 12:35:39' (IST) -> epoch ms."""
    if not text:
        return int(time.time() * 1000)
    for fmt in ("%d %b %Y, %I:%M:%S %p", "%d/%m/%Y %H:%M:%S"):
        try:
            naive = datetime.strptime(text, fmt)
        except ValueError:
            continue
        # IST is UTC+5:30 with no daylight saving.
        return int(((naive - datetime(1970, 1, 1)).total_seconds() - 19800) * 1000)
    return int(time.time() * 1000)


class NuvamaWebSocketAdapter(BaseBrokerWebSocketAdapter):
    def __init__(self):
        super().__init__()
        self.broker_name = "nuvama"
        self.user_id = None
        self.client: NuvamaStreamClient | None = None
        self.running = False
        self._lock = threading.Lock()
        # token -> {"symbol", "exchange", "modes": set}
        self.token_info: dict[str, dict] = {}
        # token -> last quote packet / last depth packet
        self._last_quote: dict[str, dict] = {}
        self._last_depth: dict[str, dict] = {}

    # --- lifecycle --------------------------------------------------------------

    def initialize(self, broker_name, user_id, auth_data=None):
        try:
            self.broker_name = broker_name
            self.user_id = user_id
            token = (auth_data or {}).get("token") or get_auth_token(user_id, bypass_cache=True)
            if not token:
                return self._create_error_response(
                    "NO_AUTH_TOKEN", f"No Nuvama session found for user {user_id}"
                )
            session = parse_token(token)
            # The proxy re-initializes in place after a failed connect (and the
            # pool does on an auth error). Stop the previous client first, or
            # its socket and thread outlive this adapter's disconnect().
            previous, self.client = self.client, None
            if previous is not None:
                previous.stop()
            self.client = NuvamaStreamClient(
                app_id=session.app_id_key,
                account_type=session.account_type or "EQ",
                on_packet=self._on_packet,
                on_connect=self._on_connect,
                on_disconnect=self._on_disconnect,
            )
            # Carry the current subscriptions over to the new client.
            if self.token_info:
                self._push_sets()
            self.logger.info(f"Nuvama adapter initialized for user {user_id}")
            return self._create_success_response("Nuvama adapter initialized")
        except Exception as e:
            self.logger.exception(f"Error initializing Nuvama adapter: {e}")
            return self._create_error_response("INIT_ERROR", str(e))

    def _on_connect(self):
        self.connected = True

    def _on_disconnect(self):
        self.connected = False

    def connect(self):
        try:
            if not self.client:
                return self._create_error_response("NOT_INITIALIZED", "Call initialize() first")
            self.client.start()
            self.running = True
            self.client.wait_for_connection(timeout=15.0)
            self.connected = self.client.is_connected()
            return self._create_success_response("Nuvama stream connecting")
        except Exception as e:
            self.logger.exception(f"Error connecting Nuvama stream: {e}")
            return self._create_error_response("CONNECT_ERROR", str(e))

    def disconnect(self):
        try:
            self.running = False
            self.connected = False
            if self.client:
                self.client.stop()
        except Exception as e:
            self.logger.exception(f"Error disconnecting Nuvama stream: {e}")
        finally:
            self.cleanup_zmq()

    # --- subscriptions ----------------------------------------------------------

    def _push_sets(self):
        with self._lock:
            quote = [t for t, i in self.token_info.items() if i["modes"]]
            depth = [t for t, i in self.token_info.items() if 3 in i["modes"]]
        self.client.set_symbols("quote", quote)
        self.client.set_symbols("quote2", depth)

    def subscribe(self, symbol, exchange, mode=2, depth_level=5):
        try:
            if not self.client:
                return self._create_error_response("NOT_INITIALIZED", "Call initialize() first")
            token = get_token(symbol, exchange)
            if not token:
                return self._create_error_response(
                    "TOKEN_NOT_FOUND", f"No token for {exchange}:{symbol}"
                )
            with self._lock:
                info = self.token_info.setdefault(
                    token, {"symbol": symbol, "exchange": exchange, "modes": set()}
                )
                info["modes"].add(int(mode))
            self._push_sets()
            return self._create_success_response(
                f"Subscribed {exchange}:{symbol}",
                symbol=symbol,
                exchange=exchange,
                mode=mode,
                actual_depth=5 if int(mode) == 3 else None,
            )
        except Exception as e:
            self.logger.exception(f"Error subscribing {exchange}:{symbol}: {e}")
            return self._create_error_response("SUBSCRIBE_ERROR", str(e))

    def unsubscribe(self, symbol, exchange, mode=2):
        try:
            if not self.client:
                return self._create_error_response("NOT_INITIALIZED", "Call initialize() first")
            token = get_token(symbol, exchange)
            if not token:
                return self._create_error_response(
                    "TOKEN_NOT_FOUND", f"No token for {exchange}:{symbol}"
                )
            with self._lock:
                info = self.token_info.get(token)
                if info:
                    info["modes"].discard(int(mode))
                    if not info["modes"]:
                        self.token_info.pop(token, None)
                        self._last_quote.pop(token, None)
                        self._last_depth.pop(token, None)
            self._push_sets()
            return self._create_success_response(f"Unsubscribed {exchange}:{symbol}")
        except Exception as e:
            self.logger.exception(f"Error unsubscribing {exchange}:{symbol}: {e}")
            return self._create_error_response("UNSUBSCRIBE_ERROR", str(e))

    # --- packets ----------------------------------------------------------------

    def _on_packet(self, streaming_type, data):
        token = data.get("sym") or data.get("symbol")
        if not token:
            return
        info = self.token_info.get(token)
        if not info:
            return
        if streaming_type == "quote":
            self._last_quote[token] = data
        elif streaming_type == "quote2":
            self._last_depth[token] = data
        else:
            return

        modes = set(info["modes"])
        symbol, exchange = info["symbol"], info["exchange"]
        quote = self._last_quote.get(token, {})

        if streaming_type == "quote":
            for mode in modes & {1, 2}:
                name = topic_mode(mode)
                self.publish_market_data(
                    f"{exchange}_{symbol}_{name}", self._normalize(quote, symbol, exchange, mode)
                )
        if 3 in modes and (streaming_type == "quote2" or token in self._last_depth):
            tick = self._normalize(quote, symbol, exchange, 3)
            tick["depth"] = self._depth(self._last_depth.get(token, {}))
            self.publish_market_data(f"{exchange}_{symbol}_DEPTH", tick)

    @staticmethod
    def _normalize(q, symbol, exchange, mode):
        ltp = _f(q.get("ltp"))
        close = _f(q.get("c"))
        data = {
            "symbol": symbol,
            "exchange": exchange,
            "mode": mode,
            "ltp": ltp,
            "last_price": ltp,
            "ltt": _epoch_ms(q.get("altt") or q.get("ltt")),
            "timestamp": int(time.time() * 1000),
        }
        if close:
            data["close"] = close
            data["prev_close"] = close
            data["change"] = round(ltp - close, 2) if ltp else 0
            data["change_percent"] = round((ltp - close) / close * 100, 2) if ltp else 0
        if mode >= 2:
            data.update(
                {
                    "open": _f(q.get("o")),
                    "high": _f(q.get("h")),
                    "low": _f(q.get("l")),
                    "volume": _i(q.get("vol")),
                    "last_quantity": _i(q.get("ltq")),
                    "average_price": _f(q.get("avgPrc")),
                    "total_buy_quantity": _i(q.get("tBQ")),
                    "total_sell_quantity": _i(q.get("tSQ")),
                    "oi": _i(q.get("oI")),
                    "open_interest": _i(q.get("oI")),
                }
            )
        if mode == 3:
            data["upper_circuit"] = _f(q.get("hCL"))
            data["lower_circuit"] = _f(q.get("lCL"))
        return data

    @staticmethod
    def _depth(d):
        def side(rows):
            out = [
                {
                    "price": _f(r.get("price")),
                    "quantity": _i(r.get("qty")),
                    "orders": _i(r.get("no")),
                }
                for r in (rows or [])[:5]
            ]
            while len(out) < 5:
                out.append({"price": 0.0, "quantity": 0, "orders": 0})
            return out

        return {"buy": side(d.get("bidValues")), "sell": side(d.get("askValues"))}
