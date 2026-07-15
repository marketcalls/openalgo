"""
Broker postback (webhook) receivers for real-time order updates.

Public POST routes at /postback/<broker> — brokers cannot authenticate with
OpenAlgo sessions, so these are CSRF-exempt (see app.py) and validated per
broker instead:
- the <broker> in the URL must match the instance's active broker session
  (single-user-per-deployment, per CLAUDE.md), and
- Zerodha payloads carry a SHA-256 checksum (order_id + order_timestamp +
  api_secret) that is verified against BROKER_API_SECRET.

Each route parses the broker payload, normalizes it into OpenAlgo's common
order-update format (reusing the status/pricetype/product tables from the
corresponding broker/*/streaming/*_order_adapter.py — single source of
truth), and publishes events.OrderUpdateEvent on the in-process event bus.
The registered subscribers fan out to socketio + the websocket_proxy relay,
identical to the order-WebSocket ingestion path.

This is the production-friendly *secondary* path: postbacks require a public
HTTPS URL registered with the broker (rejected for localhost), while the
dedicated order-WebSocket adapters work everywhere. If both are configured,
clients may see duplicate updates for the same transition — deduplicate on
(orderid, order_status, filled_quantity).
"""

import hashlib
import os

from flask import Blueprint, jsonify, request

from database.auth_db import Auth
from utils.event_bus import bus
from utils.logging import get_logger
from websocket_proxy.order_adapter import to_openalgo_symbol

logger = get_logger(__name__)

postback_bp = Blueprint("postback_bp", __name__, url_prefix="/postback")

SUPPORTED_BROKERS = {"zerodha", "dhan", "fyers", "upstox", "angel", "aliceblue"}

# Dhan REST-postback vocabulary differs from its order-WS single-letter codes
# (12-postback.md: full-word product/orderType). Everything else reuses the
# adapter modules' tables.
_DHAN_POSTBACK_PRODUCT_MAP = {"CNC": "CNC", "INTRADAY": "MIS", "MARGIN": "NRML", "MTF": "NRML"}
_DHAN_POSTBACK_PRICETYPE_MAP = {
    "MARKET": "MARKET",
    "LIMIT": "LIMIT",
    "STOP_LOSS": "SL",
    "STOP_LOSS_MARKET": "SL-M",
}
_DHAN_POSTBACK_EXCHANGE_MAP = {
    "NSE_EQ": "NSE",
    "NSE_FNO": "NFO",
    "NSE_CURRENCY": "CDS",
    "BSE_EQ": "BSE",
    "BSE_FNO": "BFO",
    "BSE_CURRENCY": "BCD",
    "MCX_COMM": "MCX",
}


def _get_active_session() -> Auth | None:
    """Return the instance's active (non-revoked) broker session, if any."""
    try:
        return Auth.query.filter_by(is_revoked=False).first()
    except Exception:
        logger.exception("Postback: failed to read active broker session")
        return None


def _publish(user_id: str, broker: str, fields: dict) -> None:
    from events import OrderUpdateEvent

    fields.setdefault("mode", "live")
    fields.setdefault("broker", broker)
    fields.setdefault("api_type", f"{broker}.postback")
    fields.setdefault("request_data", {"user_id": user_id})
    bus.publish(OrderUpdateEvent(**fields))


# --- per-broker payload normalizers ------------------------------------------
# Each returns OrderUpdateEvent kwargs or None if the payload is not an order
# event. They reuse the _STATUS_MAP/_PRICETYPE_MAP/_PRODUCT_MAP tables defined
# in the corresponding streaming order adapters.


def _normalize_zerodha(data: dict) -> dict | None:
    from broker.zerodha.streaming.zerodha_order_adapter import _STATUS_MAP

    raw_status = str(data.get("status", "")).upper()
    order_status = _STATUS_MAP.get(raw_status, raw_status.lower() or "open")
    exchange = data.get("exchange", "")
    return {
        "orderid": str(data.get("order_id", "")),
        "symbol": to_openalgo_symbol(data.get("tradingsymbol", ""), exchange),
        "exchange": exchange,
        "action": str(data.get("transaction_type", "")).upper(),
        "quantity": int(data.get("quantity") or 0),
        "price": float(data.get("price") or 0),
        "trigger_price": float(data.get("trigger_price") or 0),
        "pricetype": data.get("order_type", ""),
        "product": data.get("product", ""),
        "order_status": order_status,
        "filled_quantity": int(data.get("filled_quantity") or 0),
        "pending_quantity": int(
            data.get("pending_quantity") or data.get("unfilled_quantity") or 0
        ),
        "average_price": float(data.get("average_price") or 0),
        "rejection_reason": (data.get("status_message") or "")
        if order_status == "rejected"
        else "",
    }


def _normalize_dhan(data: dict) -> dict | None:
    from broker.dhan.streaming.dhan_order_adapter import _STATUS_MAP

    raw_status = str(data.get("orderStatus", "")).upper()
    order_status = _STATUS_MAP.get(raw_status, raw_status.lower() or "open")
    quantity = int(data.get("quantity") or 0)
    filled = int(data.get("filled_qty") or 0)
    exchange = _DHAN_POSTBACK_EXCHANGE_MAP.get(
        data.get("exchangeSegment", ""), data.get("exchangeSegment", "")
    )
    return {
        "orderid": str(data.get("orderId", "")),
        "symbol": to_openalgo_symbol(
            data.get("tradingSymbol", ""), exchange, token=data.get("securityId")
        ),
        "exchange": exchange,
        "action": str(data.get("transactionType", "")).upper(),
        "quantity": quantity,
        "price": float(data.get("price") or 0),
        "trigger_price": float(data.get("triggerPrice") or 0),
        "pricetype": _DHAN_POSTBACK_PRICETYPE_MAP.get(
            data.get("orderType", ""), data.get("orderType", "")
        ),
        "product": _DHAN_POSTBACK_PRODUCT_MAP.get(
            data.get("productType", ""), data.get("productType", "")
        ),
        "order_status": order_status,
        "filled_quantity": filled,
        "pending_quantity": max(quantity - filled, 0),
        "rejection_reason": (data.get("omsErrorDescription") or "")
        if order_status == "rejected"
        else "",
    }


def _normalize_fyers(data: dict) -> dict | None:
    from broker.fyers.streaming.fyers_order_adapter import (
        _ACTION_MAP,
        _PRICETYPE_MAP,
        _STATUS_MAP,
        _oa_exchange,
    )

    if "id" not in data or "status" not in data:
        return None
    raw_status = data.get("status")
    order_status = _STATUS_MAP.get(raw_status, str(raw_status))
    qty = int(data.get("qty") or 0)
    filled = int(data.get("filledQty") or 0)
    exchange = _oa_exchange(data)
    return {
        "orderid": str(data.get("id", "")),
        "symbol": to_openalgo_symbol(data.get("symbol", ""), exchange),
        "exchange": exchange,
        "action": _ACTION_MAP.get(data.get("side"), str(data.get("side", ""))),
        "quantity": qty,
        "price": float(data.get("limitPrice") or 0),
        "trigger_price": float(data.get("stopPrice") or 0),
        "pricetype": _PRICETYPE_MAP.get(data.get("type"), str(data.get("type", ""))),
        "product": data.get("productType", ""),
        "order_status": order_status,
        "filled_quantity": filled,
        "pending_quantity": int(data.get("remainingQuantity") or max(qty - filled, 0)),
        "average_price": float(data.get("tradedPrice") or 0),
        "rejection_reason": data.get("message", "") if raw_status == 5 else "",
    }


def _normalize_upstox(data: dict) -> dict | None:
    from broker.upstox.streaming.upstox_order_adapter import _PRODUCT_MAP, _STATUS_MAP

    if data.get("update_type") not in (None, "order"):
        return None
    raw_status = str(data.get("status", "")).lower()
    order_status = _STATUS_MAP.get(raw_status, raw_status or "open")
    quantity = int(data.get("quantity") or 0)
    filled = int(data.get("filled_quantity") or 0)
    exchange = data.get("exchange", "")
    return {
        "orderid": data.get("order_id", ""),
        "symbol": to_openalgo_symbol(
            data.get("trading_symbol", "") or data.get("tradingsymbol", ""),
            exchange,
            token=data.get("instrument_token") or data.get("instrument_key"),
        ),
        "exchange": exchange,
        "action": data.get("transaction_type", ""),
        "quantity": quantity,
        "price": float(data.get("price") or 0),
        "trigger_price": float(data.get("trigger_price") or 0),
        "pricetype": data.get("order_type", ""),
        "product": _PRODUCT_MAP.get(data.get("product", ""), data.get("product", "")),
        "order_status": order_status,
        "filled_quantity": filled,
        "pending_quantity": int(data.get("pending_quantity") or max(quantity - filled, 0)),
        "average_price": float(data.get("average_price") or 0),
        "rejection_reason": data.get("status", "") if raw_status == "rejected" else "",
    }


def _normalize_angel(data: dict) -> dict | None:
    from broker.angel.streaming.angel_order_adapter import (
        _PRICETYPE_MAP,
        _PRODUCT_MAP,
        _STATUS_TEXT_MAP,
    )

    if not data.get("orderid"):
        return None
    raw_text = str(data.get("orderstatus") or data.get("status") or "").strip().lower()
    order_status = _STATUS_TEXT_MAP.get(raw_text, raw_text or "open")
    filled = int(float(data.get("filledshares") or 0))
    unfilled = int(float(data.get("unfilledshares") or 0))
    exchange = data.get("exchange", "")
    return {
        "orderid": str(data.get("orderid", "")),
        "symbol": to_openalgo_symbol(
            data.get("tradingsymbol", ""), exchange, token=data.get("symboltoken")
        ),
        "exchange": exchange,
        "action": str(data.get("transactiontype", "")).upper(),
        "quantity": int(float(data.get("quantity") or 0)) or (filled + unfilled),
        "price": float(data.get("price") or 0),
        "trigger_price": float(data.get("triggerprice") or 0),
        "pricetype": _PRICETYPE_MAP.get(data.get("ordertype", ""), data.get("ordertype", "")),
        "product": _PRODUCT_MAP.get(data.get("producttype", ""), data.get("producttype", "")),
        "order_status": order_status,
        "filled_quantity": filled,
        "pending_quantity": unfilled,
        "average_price": float(data.get("averageprice") or 0),
        "rejection_reason": data.get("text", "") if order_status == "rejected" else "",
    }


def _normalize_aliceblue(data: dict) -> dict | None:
    from broker.aliceblue.streaming.aliceblue_order_adapter import (
        _ACTION_MAP,
        _PRICETYPE_MAP,
        _STATUS_MAP,
    )

    if not data.get("norenordno"):
        return None
    raw_status = str(data.get("status", "")).strip().lower()
    order_status = _STATUS_MAP.get(raw_status, raw_status or "open")
    qty = int(data.get("qty") or 0)
    fillshares = int(data.get("fillshares") or 0)
    exchange = data.get("exch", "")
    return {
        "orderid": data.get("norenordno", ""),
        "symbol": to_openalgo_symbol(data.get("tsym", ""), exchange),
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
        "rejection_reason": data.get("rejreason", "") if order_status == "rejected" else "",
    }


_NORMALIZERS = {
    "zerodha": _normalize_zerodha,
    "dhan": _normalize_dhan,
    "fyers": _normalize_fyers,
    "upstox": _normalize_upstox,
    "angel": _normalize_angel,
    "aliceblue": _normalize_aliceblue,
}


def _validate_zerodha_checksum(data: dict) -> bool:
    """Zerodha postbacks carry checksum = SHA-256(order_id + order_timestamp +
    api_secret) — see broker-api-docs/zerodha-api-docs/12-postbacks.md."""
    api_secret = os.getenv("BROKER_API_SECRET", "")
    checksum = data.get("checksum", "")
    order_id = str(data.get("order_id", ""))
    order_timestamp = str(data.get("order_timestamp", ""))
    if not (api_secret and checksum and order_id):
        return False
    expected = hashlib.sha256(
        f"{order_id}{order_timestamp}{api_secret}".encode()
    ).hexdigest()
    return checksum == expected


@postback_bp.route("/<broker>", methods=["POST"])
def broker_postback(broker: str):
    broker = broker.lower()
    if broker not in SUPPORTED_BROKERS:
        return jsonify({"status": "error", "message": f"Unsupported broker: {broker}"}), 404

    session_obj = _get_active_session()
    if session_obj is None or (session_obj.broker or "").lower() != broker:
        # Don't leak which broker IS active to unauthenticated callers.
        logger.warning(f"Postback for '{broker}' rejected — no matching active broker session")
        return jsonify({"status": "error", "message": "No matching broker session"}), 403

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        # Some brokers POST form-encoded payloads with a JSON body field.
        data = request.form.to_dict() or None
    if not isinstance(data, dict) or not data:
        return jsonify({"status": "error", "message": "Invalid payload"}), 400

    if broker == "zerodha" and not _validate_zerodha_checksum(data):
        logger.warning("Zerodha postback rejected — checksum validation failed")
        return jsonify({"status": "error", "message": "Checksum validation failed"}), 403

    try:
        fields = _NORMALIZERS[broker](data)
    except Exception:
        logger.exception(f"Postback normalization failed for {broker}")
        return jsonify({"status": "error", "message": "Payload normalization failed"}), 400

    if fields:
        _publish(session_obj.name, broker, fields)
        logger.info(
            f"Postback order update ({broker}): orderid={fields.get('orderid')} "
            f"status={fields.get('order_status')}"
        )

    return jsonify({"status": "success"}), 200
