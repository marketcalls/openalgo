"""
AliceBlue order-update adapter — dedicated Order Status Feed WebSocket.

Docs: broker-api-docs/aliceblue-api-docs/10-webhooks.md, "Order Status Feed
WebSocket API" section.
Auth flow:
    1. GET open-api/order-notify/ws/createWsToken with Authorization: Bearer
       <token> -> {"result": [{"orderToken": "..."}]}.
    2. Connect to wss://a3.aliceblueonline.com/open-api/order-notify/websocket
       and send {"orderToken": ..., "userId": ...} to subscribe.
    3. Send {"heartbeat": "h", "userId": ...} every 60s or the connection is
       dropped by AliceBlue.

userId here is the numeric UCC (client_id) — same resolution as
broker/aliceblue/streaming/aliceblue_adapter.py (get_user_id, falling back to
decoding the "ucc" claim from the JWT auth token).
"""

import base64
import json

from database.auth_db import get_auth_token, get_user_id
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger
from websocket_proxy.order_adapter import BaseOrderUpdateAdapter, to_openalgo_symbol

logger = get_logger(__name__)

# Host matters here. ant.aliceblueonline.com + /open-api/order-notify/... does
# NOT 404 - it answers 200 with the SPA's index.html, so raise_for_status()
# passes and json() dies on "<!DOCTYPE html>" with
# "Expecting value: line 1 column 1 (char 0)". Verified against a live account:
#   ant + /open-api/order-notify/ws/createWsToken -> 200 text/html  (3784 bytes)
#   ant + /order-notify/ws/createWsToken          -> 200 JSON, orderToken
#   a3  + /open-api/order-notify/ws/createWsToken -> 200 JSON, orderToken
# a3 is used here to match ALICEBLUE_ORDER_UPDATE_WS_URL below - one host for
# both legs of the same feed.
ALICEBLUE_CREATE_WS_TOKEN_URL = "https://a3.aliceblueonline.com/open-api/order-notify/ws/createWsToken"
ALICEBLUE_ORDER_UPDATE_WS_URL = "wss://a3.aliceblueonline.com/open-api/order-notify/websocket"
ALICEBLUE_HEARTBEAT_INTERVAL_SECONDS = 55  # under the 60s server timeout

# AliceBlue is Noren-lineage — "status"/"reporttype" free text (Noren
# convention: New/Replaced/Complete/Rejected/Cancelled/...) -> OpenAlgo's
# lowercase order_status vocabulary. Case-insensitive match.
_STATUS_MAP = {
    "open": "open",
    "new": "open",
    "trigger_pending": "trigger pending",
    "trigger pending": "trigger pending",
    "replaced": "open",
    "complete": "complete",
    "rejected": "rejected",
    "cancelled": "cancelled",
    "canceled": "cancelled",
}

# Matches broker/aliceblue/mapping/order_data.py's REST Prctype mapping (the
# verified source of truth for this broker's price-type codes).
_PRICETYPE_MAP = {"MKT": "MARKET", "L": "LIMIT", "SL": "SL", "SL-M": "SL-M"}

_ACTION_MAP = {"B": "BUY", "S": "SELL"}

#: Give up after this many consecutive token failures. An account without the
#: Order Status Feed fails identically every time, so retrying past this only
#: produces a 60s log storm for the life of the worker.
MAX_CONSECUTIVE_TOKEN_FAILURES = 5


class OrderTokenUnavailable(RuntimeError):
    """createWsToken did not yield a usable orderToken.

    Distinct from a transport error so the adapter can tell "AliceBlue says no"
    apart from "the network blipped", and stop rather than retry forever.
    """


class AliceBlueOrderUpdateAdapter(BaseOrderUpdateAdapter):
    """Dedicated order-update WebSocket adapter for AliceBlue."""

    def __init__(self, user_id: str, alice_ucc: str, auth_token: str):
        super().__init__(broker_name="aliceblue", user_id=user_id)
        self.alice_ucc = alice_ucc
        self.auth_token = auth_token
        self._order_token: str | None = None
        self._token_failures = 0

    def get_ws_url(self) -> str:
        try:
            self._order_token = self._fetch_order_token()
        except OrderTokenUnavailable as exc:
            self._token_failures += 1
            if self._token_failures >= MAX_CONSECUTIVE_TOKEN_FAILURES:
                # Permanent, not transient. Stop the adapter instead of
                # reconnecting every 60s for the life of the worker.
                self.disconnect()
                self.logger.error(
                    f"AliceBlue order updates disabled after "
                    f"{self._token_failures} consecutive token failures: {exc}"
                )
            else:
                self.logger.warning(
                    f"AliceBlue order token unavailable "
                    f"({self._token_failures}/{MAX_CONSECUTIVE_TOKEN_FAILURES}): {exc}"
                )
            raise
        self._token_failures = 0
        return ALICEBLUE_ORDER_UPDATE_WS_URL

    def get_headers(self):
        return None  # auth handshake happens via a post-connect message

    def _fetch_order_token(self) -> str:
        """Exchange the bearer token for a short-lived orderToken.

        createWsToken answers 200 with an EMPTY body when the account is not
        enabled for the Order Status Feed, so raise_for_status() passes and
        response.json() blows up with a bare
        "Expecting value: line 1 column 1 (char 0)". That told the operator
        nothing and, because every attempt failed identically, the adapter
        reconnected every 60s forever (observed past attempt 31).

        Parse defensively and raise something diagnosable instead. The
        consecutive-failure counter above turns a permanent misconfiguration
        into one loud message and a stopped adapter, rather than an endless
        60s retry loop.
        """
        client = get_httpx_client()
        response = client.get(
            ALICEBLUE_CREATE_WS_TOKEN_URL,
            headers={"Authorization": f"Bearer {self.auth_token}"},
            timeout=15,
        )
        response.raise_for_status()

        body = (response.text or "").strip()
        if not body:
            raise OrderTokenUnavailable(
                f"AliceBlue createWsToken returned HTTP {response.status_code} with an empty "
                f"body. The Order Status Feed is usually not enabled for this account - "
                f"subscribe to order updates with AliceBlue, or unset ORDER_UPDATES_ENABLED "
                f"to stop retrying. URL: {ALICEBLUE_CREATE_WS_TOKEN_URL}"
            )

        try:
            payload = response.json()
        except ValueError:
            raise OrderTokenUnavailable(
                f"AliceBlue createWsToken returned HTTP {response.status_code} with a "
                f"non-JSON body: {body[:200]!r}"
            ) from None

        results = payload.get("result") or []
        if not results or not results[0].get("orderToken"):
            raise OrderTokenUnavailable(
                f"AliceBlue createWsToken did not return an orderToken. "
                f"status={payload.get('status')!r} message={payload.get('message')!r}"
            )
        return results[0]["orderToken"]

    def on_open_extra(self, ws) -> None:
        sub_msg = {"orderToken": self._order_token, "userId": self.alice_ucc}
        ws.send(json.dumps(sub_msg))
        self.logger.info(f"Sent AliceBlue order-notify subscribe for UCC {self.alice_ucc}")

    def heartbeat_interval(self):
        return ALICEBLUE_HEARTBEAT_INTERVAL_SECONDS

    def send_heartbeat(self, ws) -> None:
        ws.send(json.dumps({"heartbeat": "h", "userId": self.alice_ucc}))

    def normalize(self, raw_message):
        try:
            data = json.loads(raw_message)
        except (json.JSONDecodeError, TypeError):
            return None

        if data.get("t") != "om":
            return None  # subscribe ack / other frame types

        raw_status = str(data.get("status", "")).strip().lower()
        order_status = _STATUS_MAP.get(raw_status, raw_status or "open")

        qty = int(data.get("qty") or 0)
        fillshares = int(data.get("fillshares") or 0)

        # Symbol -> OpenAlgo format (get_oa_symbol on Noren tsym, same as the
        # REST orderbook mapping), falling back to the broker symbol.
        exchange = data.get("exch", "")
        symbol = to_openalgo_symbol(data.get("tsym", ""), exchange)

        return {
            "orderid": data.get("norenordno", ""),
            "symbol": symbol,
            "exchange": exchange,
            "action": _ACTION_MAP.get(data.get("trantype", ""), data.get("trantype", "")),
            "quantity": qty,
            "price": float(data.get("prc") or 0),
            "trigger_price": float(data.get("trgprc") or 0),
            "pricetype": _PRICETYPE_MAP.get(data.get("prctyp", ""), data.get("prctyp", "")),
            "product": data.get("pcode", ""),
            "order_status": order_status,
            "filled_quantity": fillshares,
            "pending_quantity": max(qty - fillshares, 0),
            "average_price": float(data.get("avgprc") or 0),
            "rejection_reason": data.get("rejreason", "") if raw_status == "rejected" else "",
        }


def create_aliceblue_order_adapter(user_id: str) -> "AliceBlueOrderUpdateAdapter | None":
    """
    Factory: build an AliceBlueOrderUpdateAdapter for user_id. Resolves the
    numeric UCC the same way broker/aliceblue/streaming/aliceblue_adapter.py
    does: get_user_id(), falling back to decoding the "ucc" claim from the
    JWT auth token.
    """
    auth_token = get_auth_token(user_id, bypass_cache=True)
    if not auth_token:
        logger.warning(f"No AliceBlue auth token found for user {user_id}; order-update adapter not started")
        return None

    alice_ucc = get_user_id(user_id)
    if not alice_ucc:
        try:
            payload_b64 = auth_token.split(".")[1]
            payload_b64 += "=" * (-len(payload_b64) % 4)
            payload = json.loads(base64.urlsafe_b64decode(payload_b64))
            alice_ucc = payload.get("ucc")
        except Exception as e:
            logger.warning(f"Failed to extract UCC from AliceBlue JWT for user {user_id}: {e}")

    if not alice_ucc:
        logger.warning(f"No AliceBlue UCC found for user {user_id}; order-update adapter not started")
        return None

    return AliceBlueOrderUpdateAdapter(user_id=user_id, alice_ucc=alice_ucc, auth_token=auth_token)
