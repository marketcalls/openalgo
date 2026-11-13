"""
Tradejini order-update adapter - "orders" events on a dedicated CubePlus stream.

Docs: broker-api-docs/tradejini-api-docs/12-websocket-sdks.md ("Order Events",
"Authorization") and the official Python streaming SDK
(cdn.tradejini.com/cubeplus/static/sdk/streaming/python-sdk.tar.gz, vendored as
broker/tradejini/api/nxtradstream.py), whose binaryspec-doc.md documents the
frame layout.

Wire protocol, as the SDK speaks it:
    1. connect to wss://api.tradejini.com/v2.1/stream?token=<APIkey>:<accessToken>&version=3.1
       (no login frame; the token in the URL authenticates the socket)
    2. send {"type":"event","action":"sub","events":["orders"]} + "\\n"
       (NxtradStream.subscribeEvents; the SDK examples pass the event names)
    3. frames arrive binary: 4-byte length, 1-byte version (1), 1-byte
       compression flag (100 = zlib), then packets of [2-byte length, 1-byte
       packet type, 1-byte key + value fields]. Packet type 15 (EVENTS)
       carries one string field (key 61) whose length is given by key 56; that
       string is the event, a JSON object routed by "evntType". Packet type 13
       (auth) carries auth_status (key 25), 1 meaning accepted.
    4. an expired or invalid token closes the socket with code 4001, and the
       same token fails again on reconnect, so the adapter stands down until
       the next login

The documented event fields are evntType, type, trdSym, exch, qty, product,
price, side, status, orderId, orderTime, actStatus, msg and reason. There is no
fill quantity, average price or trigger price in that list, so those are left
out of the event unless the broker includes them.

Why a separate socket instead of the market-data one: that adapter runs in the
websocket_proxy subprocess under gunicorn, so an event published there would
land on the wrong process's event bus. Tradejini allows 5 concurrent WebSocket
connections per user (13-rate-limits.md, 16-faq.md), so a second socket should
not evict the market-data feed the way 5paisa's and Flattrade's do. Not yet
verified live.

Credentials: the auth token from the database joined to the API key from
broker/tradejini/api/auth_api.get_api_key(), exactly as the market-data
adapter (tradejini_adapter.py::initialize) and order_api.py build them.
"""

import json
import struct
import zlib

from broker.tradejini.mapping.transform_data import (
    reverse_map_order_type,
    reverse_map_product_type,
)
from database.auth_db import get_auth_token
from utils.logging import get_logger
from websocket_proxy.order_adapter import BaseOrderUpdateAdapter, to_openalgo_symbol

logger = get_logger(__name__)

TRADEJINI_STREAM_HOST = "api.tradejini.com"
TRADEJINI_STREAM_VERSION = "3.1"  # what tradejini_adapter.py passes to NxtradStream
ORDER_EVENTS = ["orders"]

# Frame constants from the SDK (nxtradstream.py / binaryspec-doc.md).
_FRAME_VERSION = 1
_ZLIB_FLAG = 100
_PKT_AUTH = 13
_PKT_EVENTS = 15
_KEY_AUTH_STATUS = 25
_KEY_MSG_LEN = 56
_KEY_MESSAGE = 61
_DEFAULT_MESSAGE_LEN = 100  # the SDK spec's length when no nLen precedes it
_CLOSE_UNAUTHORIZED = 4001  # expired or invalid token (12-websocket-sdks.md)

# Tradejini status -> OpenAlgo's lowercase push vocabulary. Mirrors
# broker/tradejini/mapping/order_data.py::map_order_data, which the order book
# uses; unknown values are passed through lowercased.
_STATUS_MAP = {
    "completed": "complete",
    "traded": "complete",
    "filled": "complete",
    "complete": "complete",
    "open": "open",
    "pending": "open",
    "trigger pending": "trigger pending",
    "rejected": "rejected",
    "cancelled": "cancelled",
    "canceled": "cancelled",
}

# The REST order book sends "buy"/"sell"; the doc's order-book sample shows
# "b"/"s". Accept both.
_ACTION_MAP = {"buy": "BUY", "b": "BUY", "sell": "SELL", "s": "SELL"}


def _present(data: dict, key: str) -> bool:
    value = data.get(key)
    return value is not None and str(value).strip() != ""


def decode_stream_frame(frame: bytes) -> tuple[list[str], list[int]]:
    """Split one binary stream frame into its event strings and auth statuses.

    Every other packet type (L1, L5, OHLC, market status, ping, greeks) is
    skipped by its length, so the decoder does not need their field specs.
    """
    events: list[str] = []
    auth_statuses: list[int] = []
    if not isinstance(frame, (bytes, bytearray)) or len(frame) < 6:
        return events, auth_statuses
    if frame[4] != _FRAME_VERSION:
        return events, auth_statuses

    data = bytes(frame[6:])
    if frame[5] == _ZLIB_FLAG:
        data = zlib.decompress(data)

    idx = 0
    while idx + 3 <= len(data):
        pkt_len = struct.unpack_from("<h", data, idx)[0]
        if pkt_len <= 0:
            break
        pkt = data[idx : idx + pkt_len]
        idx += pkt_len
        pkt_type = struct.unpack_from("b", pkt, 2)[0]

        if pkt_type == _PKT_EVENTS:
            msg_len = _DEFAULT_MESSAGE_LEN
            pos = 3
            while pos < len(pkt):
                key = pkt[pos]
                pos += 1
                if key == _KEY_MSG_LEN:
                    msg_len = struct.unpack_from("<H", pkt, pos)[0]
                    pos += 2
                elif key == _KEY_MESSAGE:
                    raw = pkt[pos : pos + msg_len]
                    events.append(raw.rstrip(b"\x00").decode("utf-8", errors="replace"))
                    pos += msg_len
                else:
                    break  # unknown key: its length is unknown, stop reading
        elif pkt_type == _PKT_AUTH:
            pos = 3
            while pos + 1 < len(pkt):
                key = pkt[pos]
                if key != _KEY_AUTH_STATUS:
                    break
                auth_statuses.append(pkt[pos + 1])
                pos += 2

    return events, auth_statuses


class TradejiniOrderUpdateAdapter(BaseOrderUpdateAdapter):
    """Order-update adapter for Tradejini (CubePlus stream, dedicated socket)."""

    def __init__(self, user_id: str, api_key: str, access_token: str):
        super().__init__(broker_name="tradejini", user_id=user_id)
        self.api_key = api_key
        self.access_token = access_token

    def _stream_token(self) -> str:
        """APIkey:accessToken, built like tradejini_adapter.py. The access token
        is re-read on every (re)connect because it is baked into the URL and
        rolls over daily; the last known one is kept if the read fails."""
        try:
            fresh = get_auth_token(self.user_id, bypass_cache=True)
        except Exception:
            self.logger.debug("Re-reading the Tradejini token failed", exc_info=True)
            fresh = None
        if fresh:
            self.access_token = fresh
        token = self.access_token
        if self.api_key and ":" not in token:
            return f"{self.api_key}:{token}"
        return token

    def get_ws_url(self) -> str:
        # Same URL NxtradStream builds (no URL-encoding of the token, as the SDK).
        return (
            f"wss://{TRADEJINI_STREAM_HOST}/v2.1/stream"
            f"?token={self._stream_token()}&version={TRADEJINI_STREAM_VERSION}"
        )

    def get_headers(self):
        return None  # authenticated by the token query parameter

    def on_open_extra(self, ws) -> None:
        self._watch_auth_close(ws)
        # NxtradStream.subscribeEvents + __send_data: JSON plus a newline.
        request = {"type": "event", "action": "sub", "events": ORDER_EVENTS}
        ws.send(json.dumps(request) + "\n")
        self.logger.info("Sent Tradejini order-event subscribe")

    def _watch_auth_close(self, ws) -> None:
        """Stand down on close code 4001 instead of reconnecting.

        12-websocket-sdks.md: an expired or invalid token is closed with 4001
        ("Unauthorized Access"), and reconnecting with the same token fails the
        same way. The upgrade itself succeeds, so the base class sees an
        ordinary close and would retry forever. WebSocketApp looks on_close up
        when the socket closes, so wrapping it here covers this connection.
        """
        original = ws.on_close

        def on_close(app, close_status_code, close_reason):
            if close_status_code == _CLOSE_UNAUTHORIZED and self._ws is app:
                self.logger.warning(
                    f"Tradejini order-update stream refused the session ({self.user_id}): "
                    f"{close_reason or 'Unauthorized Access'}. "
                    "Not retrying until the next broker login."
                )
                self._auth_rejected = True
            if original:
                original(app, close_status_code, close_reason)

        ws.on_close = on_close

    def _stand_down_after_auth_failure(self, status) -> None:
        self.logger.warning(
            f"Tradejini order-update stream refused the session ({self.user_id}), "
            f"auth_status={status}. Not retrying until the next broker login."
        )
        self._auth_rejected = True
        ws = self._ws
        if ws is not None:
            try:
                ws.close()
            except Exception:
                self.logger.debug("Closing the refused Tradejini socket failed", exc_info=True)

    def normalize_frame(self, raw_message) -> list[dict]:
        """Every order event in one binary frame, normalized."""
        if isinstance(raw_message, str):
            # Event JSON handed in directly (tests); the live stream is binary.
            return [e for e in (self.normalize_event(raw_message),) if e]
        try:
            events, auth_statuses = decode_stream_frame(raw_message)
        except (struct.error, zlib.error, IndexError) as e:
            self.logger.debug(f"Undecodable Tradejini stream frame: {e}")
            return []
        for status in auth_statuses:
            if status != 1:
                self._stand_down_after_auth_failure(status)
                return []
        out = []
        for event in events:
            # One malformed event must not cost the rest of the frame.
            try:
                fields = self.normalize_event(event)
            except (ValueError, TypeError) as e:
                self.logger.debug(f"Skipping undecodable Tradejini order event: {e}")
                continue
            if fields:
                out.append(fields)
        return out

    def normalize(self, raw_message):
        normalized = self.normalize_frame(raw_message)
        return normalized[0] if normalized else None

    def _handle_message(self, raw_message) -> None:
        # One frame can carry several event packets, so publish each one
        # rather than only the first that normalize() returns.
        try:
            normalized = self.normalize_frame(raw_message)
        except Exception as e:
            self.logger.debug(f"Failed to normalize Tradejini order event: {e}")
            return
        for fields in normalized:
            self._publish_event_fields(fields)

    def normalize_event(self, event) -> dict | None:
        """Map one decoded event (JSON text or dict) to OrderUpdateEvent kwargs."""
        if isinstance(event, str):
            try:
                event = json.loads(event)
            except json.JSONDecodeError:
                self.logger.debug(f"Tradejini event is not JSON: {event[:200]}")
                return None
        if not isinstance(event, dict):
            return None
        if str(event.get("evntType") or "").lower() != "orders":
            return None  # positions/trades are not subscribed; ignore if sent

        raw_status = str(event.get("status") or "").strip().lower().replace("_", " ")
        order_status = _STATUS_MAP.get(raw_status, raw_status)

        exchange = str(event.get("exch") or "")
        # The order book maps the symId (the brsymbol in SymToken) and the
        # event documents only trdSym; use symId if the broker sends it.
        sym_id = str(event.get("symId") or "")
        trd_sym = str(event.get("trdSym") or "")
        symbol = ""
        for candidate in (sym_id, trd_sym):
            if candidate:
                mapped = to_openalgo_symbol(candidate, exchange)
                if mapped != candidate:
                    symbol = mapped
                    break
        if not symbol:
            # No master-contract match: report the broker's own symbol.
            symbol = trd_sym or sym_id

        side = str(event.get("side") or "")
        product = str(event.get("product") or "")
        order_type = str(event.get("type") or "")

        fields = {
            "orderid": str(event.get("orderId") or ""),
            "symbol": symbol,
            "exchange": exchange,
            "action": _ACTION_MAP.get(side.lower(), side.upper()),
            "pricetype": reverse_map_order_type(order_type) if order_type else "",
            "product": (reverse_map_product_type(product) or product.upper()) if product else "",
            "order_status": order_status,
        }

        if _present(event, "qty"):
            fields["quantity"] = int(float(event["qty"]))
        if _present(event, "price"):
            fields["price"] = float(event["price"])
        # Not in the documented event field list; read under the order book's
        # names when the broker includes them.
        if _present(event, "trigPrice"):
            fields["trigger_price"] = float(event["trigPrice"])
        if _present(event, "avgPrice"):
            fields["average_price"] = float(event["avgPrice"])
        if _present(event, "fillQty"):
            fields["filled_quantity"] = int(float(event["fillQty"]))
        if _present(event, "pendingQty"):
            fields["pending_quantity"] = int(float(event["pendingQty"]))

        if order_status == "rejected":
            fields["rejection_reason"] = str(event.get("reason") or "").strip()

        return fields


def create_tradejini_order_adapter(user_id: str) -> "TradejiniOrderUpdateAdapter | None":
    """Factory: build a TradejiniOrderUpdateAdapter for user_id, or None when
    there is no session to connect with."""
    from broker.tradejini.api.auth_api import get_api_key

    access_token = get_auth_token(user_id, bypass_cache=True)
    if not access_token:
        logger.warning(
            f"No Tradejini access token for user {user_id}; order-update adapter not started"
        )
        return None

    api_key = get_api_key()
    if not api_key and ":" not in access_token:
        logger.warning(
            f"No Tradejini API key configured; order-update adapter not started for {user_id}"
        )
        return None

    return TradejiniOrderUpdateAdapter(user_id=user_id, api_key=api_key, access_token=access_token)
