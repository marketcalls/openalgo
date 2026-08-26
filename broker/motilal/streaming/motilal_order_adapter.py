"""
Motilal Oswal order-update adapter — dedicated Trade/Order WebSocket.

Docs: broker-api-docs/motilaloswal-api-docs/34-trade-websocket.md.
Endpoint: wss://openapi.motilaloswal.com/ws  (UAT: wss://uatopenapi.motilaloswal.com/ws)

Unlike Fyers/Zerodha, Motilal authenticates with an in-band JSON message rather
than a handshake header, and subscriptions are explicit:

    1. connect
    2. {"clientid": "<client code>", "authtoken": "<AuthToken>", "apikey": "<API key>"}
    3. {"clientid": "<client code>", "action": "OrderSubscribe"}

Other documented actions: TradeSubscribe, TradeUnsubscribe, OrderUnsubscribe,
logout, heartbeat. Only the order stream is subscribed here - its frames already
carry the fill state (qtytradedtoday / totalqtyremaining / averageprice), so the
trade stream would only duplicate events.

PRICE SCALE: the REST books scale prices by 10**precision (doc 18: tradeprice
278400 with precision 2 == Rs 2784.00), but the WebSocket does NOT. Doc 34's own
trade frame carries "precision": 2 alongside "tradeprice": 3597.05 - already
rupees. WS prices are therefore passed through unscaled.

NOTE: doc 34 marks the *live* endpoint "(WIP)" while documenting the UAT one as
final. If the live socket is not yet enabled for an account, the base adapter's
backoff loop simply keeps retrying in the background; order updates then fall
back to nothing until Motilal enables it. Nothing else in OpenAlgo is affected.

WebSocket error codes (doc 34): MO1001 Invalid User Id Or Auth Token,
MO8000 Technical Error, MO2012 Invalid Action Request.
"""

import json
import os

from broker.motilal.api.baseurl import get_base_url, get_ws_trade_url, split_auth_token
from broker.motilal.mapping.transform_data import (
    reverse_map_exchange,
    reverse_map_product_type,
)
from database.auth_db import get_auth_token, get_user_id
from utils.logging import get_logger
from websocket_proxy.order_adapter import BaseOrderUpdateAdapter, to_openalgo_symbol

logger = get_logger(__name__)

# Motilal order statuses (doc 32-parameters-constants.md / doc 34 samples):
# Unknown, Sent, Confirm, Cancel, Partial, Traded, Rejected, Error.
# Casing varies by channel (doc 17 "Error" vs doc 34 uppercase), so lookups are
# done on a lower-cased key. Target vocabulary is OpenAlgo's lowercase set.
_STATUS_MAP = {
    "traded": "complete",
    "complete": "complete",
    "sent": "open",
    "confirm": "open",
    "open": "open",
    "partial": "open",  # live, partially filled -> still working
    "unknown": "open",  # transient pre-confirmation state
    "rejected": "rejected",
    "error": "rejected",
    "cancel": "cancelled",
    "cancelled": "cancelled",
}

# doc 34 WebSocket error frames carry an errorcode instead of an order record.
_WS_ERROR_CODES = {
    "MO1001": "Invalid User Id Or Auth Token",
    "MO8000": "Technical Error",
    "MO2012": "Invalid Action Request",
}

# Heartbeat cadence. Doc 34 documents the "heartbeat" action but no interval;
# 30s matches the market-data client's keepalive spacing.
_HEARTBEAT_SECONDS = 30


def _to_int(value, default=0):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _to_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class MotilalOrderUpdateAdapter(BaseOrderUpdateAdapter):
    """Order-update adapter for Motilal Oswal (doc 34 trade WebSocket)."""

    def __init__(self, user_id: str, client_code: str, auth_token: str, api_key: str,
                 use_uat: bool = False):
        super().__init__(broker_name="motilal", user_id=user_id)
        self.client_code = client_code
        self.auth_token = auth_token
        self.api_key = api_key
        self.use_uat = use_uat

    # -- connection ----------------------------------------------------------

    def get_ws_url(self) -> str:
        return get_ws_trade_url(self.use_uat)

    def get_headers(self):
        return None  # doc 34: authentication is an in-band JSON message

    def on_open_extra(self, ws) -> None:
        # 1) authorize, 2) subscribe. Doc 34 documents no ack for either, so the
        # subscribe follows immediately; an auth failure comes back as an
        # MO1001 error frame, which normalize() logs.
        ws.send(
            json.dumps(
                {
                    "clientid": self.client_code,
                    "authtoken": self.auth_token,
                    "apikey": self.api_key,
                }
            )
        )
        ws.send(json.dumps({"clientid": self.client_code, "action": "OrderSubscribe"}))
        self.logger.info(f"Sent Motilal OrderSubscribe for client {self.client_code}")

    def heartbeat_interval(self):
        return _HEARTBEAT_SECONDS

    def send_heartbeat(self, ws) -> None:
        ws.send(json.dumps({"clientid": self.client_code, "action": "heartbeat"}))

    def disconnect(self) -> None:
        # Doc 34 defines an explicit logout action; best-effort before closing.
        ws = self._ws
        if ws is not None:
            try:
                ws.send(json.dumps({"clientid": self.client_code, "action": "logout"}))
            except Exception:
                pass
        super().disconnect()

    # -- message handling ----------------------------------------------------

    def normalize(self, raw_message):
        if isinstance(raw_message, (bytes, bytearray)):
            return None  # the order socket is JSON text only

        try:
            message = json.loads(raw_message)
        except (json.JSONDecodeError, TypeError):
            return None

        if not isinstance(message, dict):
            return None

        # Error / status frames (doc 34's error codes, doc 04's envelope).
        errorcode = str(message.get("errorcode", "") or "").strip()
        if errorcode:
            self.logger.warning(
                "Motilal order WS error %s: %s",
                errorcode,
                message.get("message") or _WS_ERROR_CODES.get(errorcode, "unknown error"),
            )
            return None

        # Trade frames carry tradeno/tradeprice; the order frames carry the full
        # order state, so trades are ignored to avoid duplicate events.
        if "tradeno" in message and "orderstatus" not in message:
            self.logger.debug("Ignoring Motilal trade frame for %s", message.get("uniqueorderid"))
            return None

        if "orderstatus" not in message or not message.get("uniqueorderid"):
            return None  # ack / heartbeat / unrelated frame

        return self._normalize_order(message)

    def _normalize_order(self, data: dict):
        motilal_exchange = data.get("exchange", "") or ""
        exchange = reverse_map_exchange(motilal_exchange)

        # Motilal's WS symbol is the raw scripname ("ACC EQ", "BANKNIFTY
        # 03-Feb-2022 PE 32300"), which never matches an OpenAlgo symbol - the
        # symboltoken lookup is the reliable one, exactly as the REST book
        # mappings do. to_openalgo_symbol tries the token first.
        symbol = to_openalgo_symbol(
            str(data.get("symbol", "") or ""), exchange, token=str(data.get("symboltoken", "") or "")
        )

        raw_status = str(data.get("orderstatus", "") or "").strip().lower()
        order_status = _STATUS_MAP.get(raw_status)
        if order_status is None:
            self.logger.warning(
                "Unrecognised Motilal order status %r; treating as open", data.get("orderstatus")
            )
            order_status = "open"

        # Prices are already in rupees on this channel (see the module docstring).
        price = _to_float(data.get("price"))
        trigger_price = _to_float(data.get("triggerprice"))
        average_price = _to_float(data.get("averageprice"))

        # doc 32: Ordertype is LIMIT / MARKET / STOPLOSS; doc 34 sends "Market".
        # OpenAlgo splits STOPLOSS into SL (with a limit price) and SL-M.
        pricetype = str(data.get("ordertype", "") or "").strip().upper()
        if pricetype == "STOPLOSS":
            pricetype = "SL" if price > 0 else "SL-M"

        quantity = _to_int(data.get("orderqty"))
        filled_quantity = _to_int(data.get("qtytradedtoday") or data.get("totalqtytraded"))
        pending_quantity = _to_int(
            data.get("totalqtyremaining"), max(quantity - filled_quantity, 0)
        )

        return {
            "orderid": str(data.get("uniqueorderid", "") or ""),
            "symbol": symbol,
            "exchange": exchange,
            "action": str(data.get("buyorsell", "") or "").strip().upper(),
            "quantity": quantity,
            "price": price,
            "trigger_price": trigger_price,
            "pricetype": pricetype,
            "product": reverse_map_product_type(data.get("producttype", "") or "", exchange),
            "order_status": order_status,
            "filled_quantity": filled_quantity,
            "pending_quantity": pending_quantity,
            "average_price": average_price,
            "rejection_reason": (data.get("error") or "") if order_status == "rejected" else "",
        }


def create_motilal_order_adapter(user_id: str) -> "MotilalOrderUpdateAdapter | None":
    """
    Factory: build a MotilalOrderUpdateAdapter for user_id.

    Credentials (doc 34's authorization message):
      clientid  - the Motilal client code, stored at login as the auth record's
                  user_id (see blueprints/brlogin.py's motilal branch).
      authtoken - the AuthToken half of the stored auth string.
      apikey    - BROKER_API_KEY, the app API key (same value as the ApiKey
                  header, per the standard OpenAlgo env convention).
    """
    stored_auth = get_auth_token(user_id, bypass_cache=True)
    if not stored_auth:
        logger.warning(
            f"No Motilal auth token found for user {user_id}; order-update adapter not started"
        )
        return None

    auth_token, _access_token = split_auth_token(stored_auth)
    if not auth_token:
        logger.warning(
            f"Motilal auth token for user {user_id} is empty; order-update adapter not started"
        )
        return None

    api_key = os.getenv("BROKER_API_KEY")
    if not api_key:
        logger.warning("BROKER_API_KEY not set; Motilal order-update adapter not started")
        return None

    client_code = get_user_id(user_id)
    if not client_code:
        # Sessions created before the client code was persisted have none.
        logger.warning(
            f"No Motilal client code stored for user {user_id}; order-update adapter not "
            "started. Log in again so the client code is saved."
        )
        return None

    use_uat = "uat" in get_base_url().lower()

    return MotilalOrderUpdateAdapter(
        user_id=user_id,
        client_code=client_code,
        auth_token=auth_token,
        api_key=api_key,
        use_uat=use_uat,
    )
