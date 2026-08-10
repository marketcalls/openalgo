"""
Kotak Neo order-update adapter — dedicated Order & Position streaming socket.

Docs: broker-api-docs/kotak-api-docs/13-order-position-streaming-websocket.md
(12-neo-websocket.md calls the same stream "HSI", the order feed that sits
alongside the "HSM" market feed driven by kotak_websocket.py).

Endpoint: wss://<baseurl>/realtime — <baseurl> is the value /tradeApiValidate
returns, already stored as the 3rd ":::"-separated component of the DB auth
token (broker/kotak/api/auth_api.py builds
"trading_token:::trading_sid:::base_url:::access_token").

Auth: the first frame after onopen carries the session credentials —
    {"type":"cn","Authorization":<token>,"Sid":<sid>,"src":"WEB"}
and the server replies {"ak":"ok","type":"cn","msg":"connected"}.

The two sources disagree on the encoding: doc 13 insists on a RAW, non-JSON
string ({type:cn,Authorization:...}), while Kotak's own HSI client vendored
here (HSWebSocketLib.HSIWebSocket.send) json.dumps() the same dict. Kotak
dropped the connection immediately on the raw form in live testing, so JSON is
tried first and the encoding alternates on any attempt that opens without a
"cn" ack — whichever Kotak accepts sticks.

An unacked attempt does not always announce itself: dropping the socket is one
failure mode, but silently holding it open and never authenticating is the
other, and that one looks exactly like a healthy connection on an idle market.
The ack watchdog below closes any attempt that goes KOTAK_CONNECT_ACK_TIMEOUT_
SECONDS without an ack, which both surfaces the state in the log and lets the
reconnect flip the encoding.

Frames are JSON: {"type":"order","data":{...}} and {"type":"position",...}.
Only order frames are published — OpenAlgo has no position-update event, so
position frames are ignored. Multiple frames arrive per order as it walks the
lifecycle (put order req received -> validation pending -> open pending ->
open -> complete), which is exactly the intermediate detail the client stream
wants; each is published as its own OrderUpdateEvent.
"""

import json
import threading
import time

from broker.kotak.mapping.transform_data import map_exchange
from database.auth_db import get_auth_token
from utils.logging import get_logger
from websocket_proxy.order_adapter import BaseOrderUpdateAdapter, to_openalgo_symbol

logger = get_logger(__name__)

# Kotak's own HSI client (HSWebSocketLib.StartHSIServer) runs a 30s protocol
# ping; there is no app-level heartbeat frame in the protocol.
KOTAK_WS_PING_INTERVAL_SECONDS = 30

# How long to wait for the "cn" ack before treating the attempt as failed. The
# ack arrives in one round trip when it arrives at all, so this only has to
# clear a slow link.
KOTAK_CONNECT_ACK_TIMEOUT_SECONDS = 10

# Kotak ordSt values (lowercase free text) -> OpenAlgo's lowercase
# order_status vocabulary. Every in-flight OMS state collapses to "open".
_STATUS_MAP = {
    "complete": "complete",
    "rejected": "rejected",
    "cancelled": "cancelled",
    "canceled": "cancelled",
    "open": "open",
    "trigger pending": "trigger pending",
    "put order req received": "open",
    "validation pending": "open",
    "open pending": "open",
    "modified": "open",
    "modify validation pending": "open",
    "modify pending": "open",
    "cancel pending": "open",
    "after market order req received": "open",
    "modify after market order req received": "open",
    "cancelled after market order": "cancelled",
}

# Kotak prcTp codes -> OpenAlgo pricetype constants. "L" is what
# mapping/transform_data.py::map_order_type sends on placement; the stream
# docs also show "MKT"/"LMT".
_PRICETYPE_MAP = {
    "MKT": "MARKET",
    "MARKET": "MARKET",
    "L": "LIMIT",
    "LMT": "LIMIT",
    "LIMIT": "LIMIT",
    "SL": "SL",
    "SL-M": "SL-M",
}

_ACTION_MAP = {"B": "BUY", "S": "SELL"}


def _num(value, cast=float, default=0):
    """Parse Kotak's string-typed numeric fields ("0.00", "", None) safely."""
    try:
        return cast(float(value))
    except (TypeError, ValueError):
        return default


def _realtime_ws_url(base_url: str) -> str:
    """Build wss://<baseurl>/realtime from the stored tradeApiValidate baseUrl.

    The stored value is an https origin (order_api.py uses it as
    f"{base_url}/quick/user/orders"), so only the scheme needs swapping.
    """
    base = (base_url or "").strip().rstrip("/")
    if base.startswith("https://"):
        base = "wss://" + base[len("https://") :]
    elif base.startswith("http://"):
        base = "ws://" + base[len("http://") :]
    elif not base.startswith(("wss://", "ws://")):
        base = "wss://" + base
    return f"{base}/realtime"


class KotakOrderUpdateAdapter(BaseOrderUpdateAdapter):
    """Dedicated order-update WebSocket adapter for Kotak Neo."""

    def __init__(self, user_id: str, base_url: str, session_token: str, session_sid: str):
        super().__init__(broker_name="kotak", user_id=user_id)
        self.base_url = base_url
        self.session_token = session_token
        self.session_sid = session_sid
        # Handshake-encoding state, see on_open_extra() and the module docstring.
        self._use_json_handshake = True
        self._connect_attempted = False
        self._connect_acked = False

    def get_ws_url(self) -> str:
        return _realtime_ws_url(self.base_url)

    def get_headers(self):
        return None  # auth is the post-connect "cn" frame, not a header

    def ws_ping_interval(self) -> int:
        return KOTAK_WS_PING_INTERVAL_SECONDS

    def on_open_extra(self, ws) -> None:
        # If the previous attempt opened but was dropped without a "cn" ack,
        # the encoding was wrong — alternate for the next try (see below).
        if self._connect_attempted and not self._connect_acked:
            self._use_json_handshake = not self._use_json_handshake
        self._connect_attempted = True
        self._connect_acked = False

        if self._use_json_handshake:
            # Kotak's own HSI client (HSWebSocketLib.HSIWebSocket.send) sends
            # this frame as JSON, contradicting doc 13's "NOT JSON" note.
            frame = json.dumps(
                {
                    "type": "cn",
                    "Authorization": self.session_token,
                    "Sid": self.session_sid,
                    "src": "WEB",
                }
            )
        else:
            # Doc 13's literal raw-string form.
            frame = f"{{type:cn,Authorization:{self.session_token},Sid:{self.session_sid},src:WEB}}"

        ws.send(frame)
        encoding = "json" if self._use_json_handshake else "raw"
        self.logger.info(
            f"Sent Kotak realtime connect frame ({encoding}) for sid {self.session_sid}"
        )
        self._start_ack_watchdog(ws, encoding)

    def _start_ack_watchdog(self, ws, encoding: str) -> None:
        """Close the socket if Kotak never acks the connect frame.

        A rejected handshake is sometimes a drop and sometimes silence — an
        unauthenticated socket that Kotak simply holds open pushes nothing and
        is indistinguishable from a quiet market. Closing it here turns that
        case into a logged failure plus a reconnect, which alternates the
        encoding via on_open_extra().
        """

        def watch():
            deadline = time.monotonic() + KOTAK_CONNECT_ACK_TIMEOUT_SECONDS
            while time.monotonic() < deadline:
                time.sleep(0.5)
                # Bound to the socket it was started for: a reconnect replaces
                # self._ws, and this thread must not close its successor.
                if self._connect_acked or self._shutting_down or self._ws is not ws:
                    return
            self.logger.warning(
                f"No Kotak realtime 'cn' ack within {KOTAK_CONNECT_ACK_TIMEOUT_SECONDS}s of the "
                f"{encoding} connect frame — closing so the next attempt tries the other encoding"
            )
            try:
                ws.close()
            except Exception:
                pass

        threading.Thread(
            target=watch,
            daemon=True,
            name=f"order-adapter-ack-kotak-{self.user_id}",
        ).start()

    def normalize(self, raw_message):
        if isinstance(raw_message, (bytes, bytearray)):
            return None

        try:
            message = json.loads(raw_message)
        except (json.JSONDecodeError, TypeError):
            self.logger.info(f"Kotak realtime text frame: {raw_message}")
            return None  # non-JSON acks / keepalive text

        if not isinstance(message, dict):
            return None

        msg_type = message.get("type")
        if msg_type in ("order", "position"):
            # Live data proves the session authenticated, whatever the ack
            # looked like — stop the watchdog from closing a working socket.
            self._connect_acked = True

        if msg_type != "order":
            # "cn" ack, "position" frames and broker notices. Log them — the
            # ack confirms which handshake encoding Kotak accepted, and a
            # failure notice carries the reason it is about to close.
            if msg_type == "cn" or "ak" in message:
                self._connect_acked = str(message.get("ak", "")).lower() == "ok"
                self.logger.info(f"Kotak realtime connect response: {message}")
            elif msg_type != "position":
                self.logger.info(f"Kotak realtime notice: {message}")
            return None

        data = message.get("data") or {}
        if not data.get("nOrdNo"):
            return None

        self.logger.debug(f"Kotak order frame: {data}")

        raw_status = str(data.get("ordSt", "")).strip().lower()
        order_status = _STATUS_MAP.get(raw_status, raw_status or "open")

        # exSeg is Kotak's segment code ("nse_cm"); map_exchange returns the
        # canonical OpenAlgo exchange, same as mapping/order_data.py does for
        # the REST orderbook. Unknown segments fall through as-is.
        raw_segment = data.get("exSeg", "")
        exchange = map_exchange(raw_segment) or raw_segment

        # Token-keyed lookup first (tok + mapped exchange), falling back to the
        # series-suffixed trading symbol ("ITBEES-EQ" -> "ITBEES").
        symbol = to_openalgo_symbol(
            data.get("trdSym") or data.get("sym", ""), exchange, token=data.get("tok")
        )

        quantity = _num(data.get("qty"), int)
        filled = _num(data.get("fldQty"), int)
        pending = _num(data.get("unFldSz"), int, default=max(quantity - filled, 0))

        raw_pricetype = str(data.get("prcTp", "")).upper()
        action = _ACTION_MAP.get(data.get("trnsTp", ""), str(data.get("trnsTp", "")).upper())

        # One line per lifecycle transition (put order req received -> ... ->
        # complete), so the log shows an order's full progression.
        self.logger.info(
            f"Kotak order update: {data.get('nOrdNo')} {action} {symbol} [{exchange}] "
            f"{order_status} qty={quantity} filled={filled} avg={_num(data.get('avgPrc'))}"
            + (f" reason={data.get('rejRsn')}" if order_status == "rejected" else "")
        )

        return {
            "orderid": str(data.get("nOrdNo", "")),
            "symbol": symbol,
            "exchange": exchange,
            "action": action,
            "quantity": quantity,
            "price": _num(data.get("prc")),
            "trigger_price": _num(data.get("trgPrc")),
            "pricetype": _PRICETYPE_MAP.get(raw_pricetype, raw_pricetype),
            "product": data.get("prod", ""),  # NRML/MIS/CNC already match OpenAlgo
            "order_status": order_status,
            "filled_quantity": filled,
            "pending_quantity": pending,
            "average_price": _num(data.get("avgPrc")),
            "rejection_reason": data.get("rejRsn", "") if order_status == "rejected" else "",
        }


def create_kotak_order_adapter(user_id: str) -> "KotakOrderUpdateAdapter | None":
    """
    Factory: build a KotakOrderUpdateAdapter for user_id. The stored DB token
    is the composite "trading_token:::trading_sid:::base_url:::access_token"
    (same split kotak_adapter.py and api/order_api.py use); the realtime socket
    needs the token, the sid and the baseUrl.
    """
    auth_token = get_auth_token(user_id, bypass_cache=True)
    if not auth_token:
        logger.warning(
            f"No Kotak auth token found for user {user_id}; order-update adapter not started"
        )
        return None

    parts = auth_token.split(":::")
    if len(parts) != 4:
        logger.warning(
            f"Unexpected Kotak auth token format for user {user_id}; "
            "order-update adapter not started"
        )
        return None

    session_token, session_sid, base_url = parts[0], parts[1], parts[2]
    if not (session_token and session_sid and base_url):
        logger.warning(
            f"Incomplete Kotak credentials for user {user_id}; order-update adapter not started"
        )
        return None

    return KotakOrderUpdateAdapter(
        user_id=user_id,
        base_url=base_url,
        session_token=session_token,
        session_sid=session_sid,
    )
