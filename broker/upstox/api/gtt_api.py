# Upstox GTT REST integration.
# Upstox GTT reference: https://upstox.com/developer/api-documentation/gtt-orders
# Local doc set: broker-api-docs/upstox-api-docs/14a-gtt-place.md,
# 14b-gtt-modify.md, 14c-gtt-cancel.md, 14d-gtt-get-details.md
#
# Endpoints (all v3, unlike the v2 order endpoints in order_api.py):
#   POST   /v3/order/gtt/place
#   PUT    /v3/order/gtt/modify
#   DELETE /v3/order/gtt/cancel     (gtt_order_id travels in the JSON body)
#   GET    /v3/order/gtt            (no query param = whole GTT book)
#
# Two Upstox quirks shape this module:
#   1. There is no limit-price field anywhere in the GTT payload - the child
#      order fires at the rule's trigger_price, optionally widened by
#      ``market_protection``. MARKET is rejected (UDAPI1158), so a MARKET
#      request becomes a market_protection percentage instead of a
#      zerodha-style MPP limit (see broker/upstox/mapping/gtt_data.py).
#   2. Every GTT must carry an ENTRY rule (UDAPI1141), and a MULTIPLE needs
#      2-3 rules (UDAPI1137), so no rule combination omits the entry. Upstox
#      therefore has no exit-only two-leg product: its MULTIPLE GTT is a
#      BRACKET (entry, then target/stop-loss attached to it), which is also
#      what Upstox Pro's own GTT ticket builds. OpenAlgo's OCO is an
#      exit-only pair on a position assumed to already exist, so mapping it
#      here adds an ENTRY rule Upstox will act on: the position gets opened,
#      then bracketed. Logged loudly at place time.
#
#      Note what is NOT forced: the ENTRY rule accepts BELOW / ABOVE /
#      IMMEDIATE, and only NON-ENTRY rules are pinned to IMMEDIATE
#      (UDAPI1143). We send IMMEDIATE purely because an OpenAlgo OCO payload
#      carries no entry price to trigger on. Supporting Upstox's bracket GTT
#      properly needs a distinct OpenAlgo request shape with its own entry
#      trigger -- not a re-reading of OCO. A stop or target on an existing
#      holding needs none of this: that is a SINGLE sell GTT.

import json

from broker.upstox.mapping.gtt_data import (
    map_gtt_book,
    transform_modify_gtt,
    transform_place_gtt,
)
from database.token_db import get_token
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)

# Same host the rest of broker/upstox/api uses (order_api.get_api_response).
_BASE = "https://api.upstox.com"
_GTT_BASE = f"{_BASE}/v3/order/gtt"


class _FakeResponse:
    """Minimal stand-in so the service layer's ``res.status`` access keeps working
    when we short-circuit before issuing the HTTP call."""

    def __init__(self, status_code):
        self.status_code = status_code
        self.status = status_code
        self.text = ""


def _headers(auth):
    """Upstox auth header set - identical to order_api.place_order_api."""
    return {
        "Authorization": f"Bearer {auth}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _parse(response):
    """Parse an Upstox response body, never raising on a non-JSON payload."""
    try:
        return response.json()
    except Exception:
        return {"status": "error", "message": response.text or "Invalid response"}


def _error_message(payload, default):
    """Pull a human message out of Upstox's ``errors[]`` envelope.

    Failures come back as ``{"status": "error", "errors": [{"error_code",
    "message", ...}]}``; a few gateway-level failures use a flat ``message``
    instead, so both shapes are handled.
    """
    if isinstance(payload, dict):
        errors = payload.get("errors")
        if isinstance(errors, list) and errors:
            parts = []
            for err in errors:
                if not isinstance(err, dict):
                    continue
                code = err.get("error_code") or ""
                msg = err.get("message") or ""
                parts.append(f"{code}: {msg}".strip(": ") if code else msg)
            parts = [p for p in parts if p]
            if parts:
                return "; ".join(parts)
        if payload.get("message"):
            return str(payload["message"])
    return default


def _extract_gtt_order_id(payload, fallback=None):
    """Upstox returns ``data.gtt_order_ids: ["GTT-..."]`` on place/modify/cancel."""
    if isinstance(payload, dict):
        data = payload.get("data") or {}
        if isinstance(data, dict):
            ids = data.get("gtt_order_ids") or []
            if isinstance(ids, list) and ids:
                return str(ids[0])
            if data.get("gtt_order_id"):
                return str(data["gtt_order_id"])
    return str(fallback) if fallback else None


def _fetch_last_price(symbol, exchange, auth):
    """Fetch LTP from Upstox via the broker's own data handler.

    The LTP decides each ENTRY rule's ``trigger_type`` (BELOW / ABOVE /
    IMMEDIATE) and is the ENTRY trigger price for the OCO form, so the broker
    layer resolves it just-in-time - clients never send it.
    """
    try:
        from broker.upstox.api.data import BrokerData

        quotes = BrokerData(auth).get_quotes(symbol, exchange)
        ltp = quotes.get("ltp") if isinstance(quotes, dict) else None
        return float(ltp) if ltp else None
    except Exception:
        logger.exception(f"Upstox GTT: failed to fetch LTP for {symbol}@{exchange}")
        return None


def _prepare(data, auth):
    """Resolve instrument_token + last_price on ``data`` in place.

    Returns ``(error_message, status_code)`` on failure, ``(None, None)`` on
    success. The instrument token is Upstox's instrument key (e.g.
    ``NSE_EQ|INE002A01018``) resolved exactly the way order_api does.
    """
    token = data.get("instrument_token") or get_token(data["symbol"], data["exchange"])
    if not token:
        return f"Instrument token not found for {data.get('symbol')}", 404
    data["instrument_token"] = token

    if not data.get("last_price"):
        ltp = _fetch_last_price(data["symbol"], data["exchange"], auth)
        if ltp:
            data["last_price"] = ltp
        elif (data.get("trigger_type") or "").upper() == "OCO":
            # The OCO form needs a positive ENTRY trigger price and Upstox
            # rejects non-positive triggers, so there is no safe fallback.
            return "Failed to fetch last_price from Upstox quotes", 502
        else:
            logger.warning(
                f"Upstox GTT: no LTP for {data.get('symbol')}@{data.get('exchange')}; "
                f"falling back to triggerprice_sl/tg to pick the trigger direction"
            )

    return None, None


def place_gtt_order(data, auth):
    """Create a GTT on Upstox. Returns ``(response, response_dict, trigger_id)``.

    ``instrument_token`` and ``last_price`` are resolved server-side before the
    mapper builds the body. OCO placements emit a warning because Upstox's
    MULTIPLE form opens the ENTRY position before bracketing it (see the module
    docstring).
    """
    err, code = _prepare(data, auth)
    if err:
        return _FakeResponse(code), {"status": "error", "message": err}, None

    if (data.get("trigger_type") or "").upper() == "OCO":
        logger.warning(
            "Upstox GTT OCO -> MULTIPLE: Upstox has no exit-only two-leg GTT - every "
            "GTT must carry an ENTRY rule (UDAPI1141), so its MULTIPLE form is a "
            "bracket, not an OCO. This GTT will OPEN the entry position at market "
            "(ENTRY sent as IMMEDIATE at LTP, because an OpenAlgo OCO payload carries "
            "no entry price) and only then arm the TARGET/STOPLOSS pair. If you meant "
            "to set a stop or target on a holding you ALREADY own, cancel this and "
            "place a SINGLE GTT instead."
        )

    payload = json.dumps(transform_place_gtt(data))
    logger.info(f"Upstox place_gtt payload: {payload}")

    client = get_httpx_client()
    response = client.post(f"{_GTT_BASE}/place", headers=_headers(auth), content=payload)
    response.status = response.status_code  # parity with other order APIs
    logger.info(f"Upstox place_gtt raw: status={response.status_code}, body={response.text}")

    response_data = _parse(response)

    trigger_id = None
    if isinstance(response_data, dict) and response_data.get("status") == "success":
        trigger_id = _extract_gtt_order_id(response_data)
    else:
        # The service layer surfaces response_data["message"]; Upstox puts the
        # reason inside errors[], so normalise it here.
        message = _error_message(response_data, "Failed to place GTT")
        if isinstance(response_data, dict):
            response_data["message"] = message
        else:
            response_data = {"status": "error", "message": message}

    return response, response_data, trigger_id


def modify_gtt_order(data, auth):
    """Modify an active GTT on Upstox. Returns ``(response_dict, status_code)``.

    ``data`` must include ``trigger_id`` plus the flat replacement body
    (trigger_type, action, quantity, pricetype and the trigger prices).
    Upstox's PUT replaces ``type`` + ``rules`` wholesale but cannot change
    instrument_token, product or transaction_type, and rejects a quantity
    change once the GTT has reached OPEN status (UDAPI1150 territory) - such
    rejections are passed through as-is.
    """
    trigger_id = data.get("trigger_id")
    if not trigger_id:
        return {"status": "error", "message": "trigger_id is required"}, 400

    err, code = _prepare(data, auth)
    if err:
        return {"status": "error", "message": err}, code

    payload = json.dumps(transform_modify_gtt(data))
    logger.info(f"Upstox modify_gtt payload ({trigger_id}): {payload}")

    client = get_httpx_client()
    response = client.put(f"{_GTT_BASE}/modify", headers=_headers(auth), content=payload)
    logger.info(f"Upstox modify_gtt raw: status={response.status_code}, body={response.text}")

    response_data = _parse(response)

    if isinstance(response_data, dict) and response_data.get("status") == "success":
        return (
            {
                "status": "success",
                "trigger_id": _extract_gtt_order_id(response_data, trigger_id),
            },
            200,
        )

    return (
        {"status": "error", "message": _error_message(response_data, "Failed to modify GTT")},
        response.status_code,
    )


def cancel_gtt_order(trigger_id, auth):
    """Cancel an active GTT on Upstox. Returns ``(response_dict, status_code)``.

    Upstox's cancel is a DELETE that carries ``{"gtt_order_id": ...}`` in the
    request body, so it goes through ``client.request`` - httpx's ``delete()``
    helper does not accept a body.
    """
    if not trigger_id:
        return {"status": "error", "message": "trigger_id is required"}, 400

    payload = json.dumps({"gtt_order_id": str(trigger_id)})
    logger.info(f"Upstox cancel_gtt payload: {payload}")

    client = get_httpx_client()
    response = client.request(
        "DELETE", f"{_GTT_BASE}/cancel", headers=_headers(auth), content=payload
    )
    logger.info(f"Upstox cancel_gtt raw: status={response.status_code}, body={response.text}")

    response_data = _parse(response)

    if isinstance(response_data, dict) and response_data.get("status") == "success":
        return (
            {
                "status": "success",
                "trigger_id": _extract_gtt_order_id(response_data, trigger_id),
            },
            200,
        )

    return (
        {"status": "error", "message": _error_message(response_data, "Failed to cancel GTT")},
        response.status_code,
    )


def get_gtt_book(auth):
    """List all GTTs for the user. Returns ``(response_dict, status_code)``.

    ``GET /v3/order/gtt`` without ``gtt_order_id`` returns the whole book. The
    returned dict has ``status`` and ``data`` where ``data`` is the list of
    OpenAlgo-normalised GTT objects (see :func:`map_gtt_book`), already
    filtered to triggers that can still fire.
    """
    client = get_httpx_client()
    response = client.get(_GTT_BASE, headers=_headers(auth))
    logger.info(f"Upstox gtt_book raw: status={response.status_code}, body={response.text}")

    raw = _parse(response)

    if not isinstance(raw, dict) or raw.get("status") != "success":
        return (
            {"status": "error", "message": _error_message(raw, "Failed to fetch GTT book")},
            response.status_code,
        )

    return {"status": "success", "data": map_gtt_book(raw)}, 200
