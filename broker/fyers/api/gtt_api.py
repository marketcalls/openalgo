"""Fyers GTT (Good Till Trigger) REST integration.

Fyers API v3 GTT reference: fyers-api-docs/FYERS_API_v3.md -> "GTT Orders"
(GTT Single, GTT OCO, GTT Modify Order, GTT Cancel Order, GTT Order Book).

Endpoints (same host and auth-header format as every other Fyers call, see
``broker/fyers/api/order_api.py``):

    POST   /api/v3/gtt/orders/sync   -- place  (leg1 only = GTT, leg1+leg2 = OCO)
    PATCH  /api/v3/gtt/orders/sync   -- modify (id + orderInfo only)
    DELETE /api/v3/gtt/orders/sync   -- cancel (id in the JSON body)
    GET    /api/v3/gtt/orders        -- book

All four share the process-wide Fyers rate-limit budget (10 req/sec per API
key across every endpoint), so they go through
``broker.fyers.api.rate_limiter`` exactly like ``get_api_response`` does,
including the 429 retry with Retry-After honouring.
"""

import json
import os
import time

import httpx

from broker.fyers.api.rate_limiter import (
    MAX_RETRIES,
    apply_rate_limit,
    retry_delay_from_headers,
)
from broker.fyers.mapping.gtt_data import (
    map_gtt_book,
    transform_cancel_gtt,
    transform_modify_gtt,
    transform_place_gtt,
)
from database.token_db_enhanced import get_symbol_info
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger
from utils.mpp_slab import calculate_protected_price, get_instrument_type_from_symbol

logger = get_logger(__name__)

_BASE = "https://api-t1.fyers.in"
_GTT_SYNC = "/api/v3/gtt/orders/sync"
_GTT_BOOK = "/api/v3/gtt/orders"

# Fyers GTT success codes: 1101 place, 1102 modify, 1103 cancel, 201 in-transit,
# 200 for the GTT order book.
_GTT_OK_CODES = (200, 201, 1101, 1102, 1103)


class _FakeResponse:
    """Minimal stand-in so the service layer's ``res.status`` access keeps
    working when we short-circuit before issuing the HTTP call."""

    def __init__(self, status_code, text=""):
        self.status_code = status_code
        self.status = status_code
        self.text = text


def _headers(auth):
    """Fyers auth header is ``Authorization: <app_id>:<access_token>``.

    Built the same way as ``order_api.place_order_api`` -- the app id comes
    from the ``BROKER_API_KEY`` env var, never from the request payload.
    """
    api_key = os.getenv("BROKER_API_KEY")
    return {
        "Authorization": f"{api_key}:{auth}",
        "Content-Type": "application/json",
    }


def _request(method, path, auth, payload=None, _retry_count=0):
    """Issue one rate-limited Fyers GTT request, retrying on HTTP 429.

    Mirrors ``order_api.get_api_response``: pace against the shared
    process-wide budget first, then back off on 429 using the Retry-After /
    X-Retry-After-Ms headers rather than surfacing the failure immediately.
    ``httpx`` has no body-carrying ``delete()``, so DELETE goes through
    ``client.request`` like ``order_api.cancel_order`` does.
    """
    client = get_httpx_client()
    url = f"{_BASE}{path}"

    apply_rate_limit()

    if method == "GET":
        response = client.request("GET", url, headers=_headers(auth))
    else:
        response = client.request(method, url, headers=_headers(auth), json=payload)

    response.status = response.status_code  # parity with the other order APIs

    if response.status_code == 429 and _retry_count < MAX_RETRIES:
        delay = retry_delay_from_headers(response.headers, _retry_count)
        logger.warning(
            f"Fyers GTT rate limited (429) on {path}. Retrying in {delay:.2f}s "
            f"(attempt {_retry_count + 1}/{MAX_RETRIES})"
        )
        time.sleep(delay)
        return _request(method, path, auth, payload, _retry_count + 1)

    return response


def _parse(response):
    """Parse a Fyers response body, never letting a non-JSON body raise."""
    try:
        return response.json()
    except Exception:
        return {"s": "error", "message": response.text or "Invalid response"}


def _is_ok(response_data):
    """Fyers signals success with ``s == "ok"``.

    The numeric ``code`` (1101 placed / 1102 modified / 1103 cancelled, 201
    in-transit, 200 for the book) is treated as a secondary confirmation for
    the rare responses that omit ``s``.
    """
    status = (response_data.get("s") or "").lower()
    if status == "ok":
        return True
    if status == "error":
        return False
    return response_data.get("code") in _GTT_OK_CODES


def _order_tag(data):
    """Build the Fyers ``orderTag`` from the OpenAlgo strategy name.

    Fyers concatenates "1:GTT" to the front of whatever tag is supplied (the
    default is "2:GTTUntagged"), and rejects tags carrying punctuation, so the
    strategy is reduced to alphanumerics and capped. Falls back to the same
    "openalgo" tag ``transform_data`` uses for regular orders.
    """
    strategy = (data.get("strategy") or "").strip()
    cleaned = "".join(ch for ch in strategy if ch.isalnum())[:20]
    return cleaned or "openalgo"


def _fetch_last_price(symbol, exchange, auth):
    """Fetch the LTP through Fyers' own quote handler.

    Only needed for the SINGLE + MARKET case (see ``_apply_mpp_if_market``);
    the Fyers GTT payload itself never carries a last price, unlike Kite's
    ``condition.last_price``.
    """
    try:
        from broker.fyers.api.data import BrokerData

        quotes = BrokerData(auth).get_quotes(symbol, exchange)
    except Exception:
        logger.exception(f"Fyers GTT: failed to fetch LTP for {exchange}:{symbol}")
        return None

    if not isinstance(quotes, dict):
        return None
    ltp = quotes.get("ltp")
    return float(ltp) if ltp else None


def _apply_mpp_if_market(data, auth):
    """Convert MARKET pricetype -> MPP-protected LIMIT.

    A Fyers GTT leg carries only ``price`` / ``triggerPrice`` / ``qty`` -- there
    is no order-type field anywhere in the GTT request (see the GTT Single and
    GTT OCO request attributes), so the child order Fyers fires is always a
    LIMIT at ``price``. MARKET therefore has to be emulated the same way
    zerodha does it: compute a Market-Price-Protection buffer around the
    relevant base price, override the limit fields, and force pricetype=LIMIT.

    SINGLE -> buffer applied to the LTP (fetched here, since OpenAlgo clients
              no longer send ``last_price``); ``data["price"]`` overridden.
    OCO    -> buffer applied to each leg's trigger price; ``data["stoploss"]``
              and ``data["target"]`` overridden (the single ``action`` gives the
              buy/sell direction for both legs).
    """
    if (data.get("pricetype") or "").upper() != "MARKET":
        return

    action = (data.get("action") or "").upper()
    symbol = data.get("symbol")
    exchange = data.get("exchange")

    sym_info = get_symbol_info(symbol, exchange) if symbol and exchange else None
    tick_size = getattr(sym_info, "tick_size", None) if sym_info else None
    instrument_type = (
        getattr(sym_info, "instrumenttype", None) if sym_info else None
    ) or get_instrument_type_from_symbol(symbol or "")

    trigger_type = (data.get("trigger_type") or "").upper()

    if trigger_type == "OCO":
        sl_trigger = float(data.get("triggerprice_sl") or 0)
        tg_trigger = float(data.get("triggerprice_tg") or 0)
        if sl_trigger > 0:
            data["stoploss"] = calculate_protected_price(
                price=sl_trigger,
                action=action,
                symbol=symbol,
                instrument_type=instrument_type,
                tick_size=tick_size,
            )
        if tg_trigger > 0:
            data["target"] = calculate_protected_price(
                price=tg_trigger,
                action=action,
                symbol=symbol,
                instrument_type=instrument_type,
                tick_size=tick_size,
            )
    else:
        last_price = data.get("last_price") or _fetch_last_price(symbol, exchange, auth)
        if last_price and float(last_price) > 0:
            data["last_price"] = float(last_price)
            data["price"] = calculate_protected_price(
                price=float(last_price),
                action=action,
                symbol=symbol,
                instrument_type=instrument_type,
                tick_size=tick_size,
            )
        else:
            logger.warning(
                f"MPP: no last_price available for {symbol}@{exchange}; "
                f"sending raw price={data.get('price')} as LIMIT"
            )

    data["pricetype"] = "LIMIT"
    logger.info(
        f"Fyers GTT MARKET->LIMIT: trigger_type={trigger_type}, action={action}, "
        f"symbol={symbol}, instrument_type={instrument_type}, tick_size={tick_size}, "
        f"price={data.get('price')}, stoploss={data.get('stoploss')}, "
        f"target={data.get('target')}"
    )


def place_gtt_order(data, auth):
    """Create a GTT on Fyers. Returns ``(response, response_dict, trigger_id)``.

    SINGLE sends ``orderInfo.leg1`` only; OCO adds ``leg2``. There is no
    separate OCO endpoint -- the presence of leg2 is the OCO switch, and Fyers
    requires leg1's trigger to be above the LTP and leg2's below it (the
    mapper handles that ordering, see ``build_order_info``).

    MARKET is MPP-converted to LIMIT first because a Fyers GTT leg has no
    order-type field.
    """
    try:
        _apply_mpp_if_market(data, auth)

        payload = transform_place_gtt(data, order_tag=_order_tag(data))
        logger.info(f"Fyers place_gtt payload: {json.dumps(payload)}")

        response = _request("POST", _GTT_SYNC, auth, payload)
        logger.info(f"Fyers place_gtt raw: status={response.status_code}, body={response.text}")

        response_data = _parse(response)

        trigger_id = None
        if _is_ok(response_data) and response_data.get("id"):
            trigger_id = str(response_data["id"])
        else:
            logger.warning(
                f"Fyers GTT placement failed: {response_data.get('message', 'Unknown error')}"
            )

        return response, response_data, trigger_id

    except httpx.HTTPError as e:
        logger.exception("HTTP error during Fyers GTT placement")
        return _FakeResponse(500), {"s": "error", "message": f"HTTP error: {e}"}, None
    except Exception as e:
        logger.exception("Error during Fyers GTT placement")
        return _FakeResponse(500), {"s": "error", "message": f"General error: {e}"}, None


def modify_gtt_order(data, auth):
    """Modify a pending GTT on Fyers. Returns ``(response_dict, status_code)``.

    ``PATCH /api/v3/gtt/orders/sync`` accepts only ``id`` + ``orderInfo``:
    side, symbol and productType cannot be changed on an existing GTT, so those
    fields of the OpenAlgo modify request are ignored. Anything omitted keeps
    its original value at Fyers.
    """
    trigger_id = data.get("trigger_id")
    if not trigger_id:
        return {"status": "error", "message": "trigger_id is required"}, 400

    try:
        _apply_mpp_if_market(data, auth)

        payload = transform_modify_gtt(data)
        logger.info(f"Fyers modify_gtt payload ({trigger_id}): {json.dumps(payload)}")

        response = _request("PATCH", _GTT_SYNC, auth, payload)
        logger.info(f"Fyers modify_gtt raw: status={response.status_code}, body={response.text}")

        response_data = _parse(response)

        if _is_ok(response_data):
            return {
                "status": "success",
                "trigger_id": str(response_data.get("id", trigger_id)),
            }, 200

        return {
            "status": "error",
            "message": response_data.get("message", "Failed to modify GTT"),
        }, response.status_code

    except httpx.HTTPError as e:
        logger.exception("HTTP error during Fyers GTT modification")
        return {"status": "error", "message": f"HTTP error: {e}"}, 500
    except Exception as e:
        logger.exception("Error during Fyers GTT modification")
        return {"status": "error", "message": f"General error: {e}"}, 500


def cancel_gtt_order(trigger_id, auth):
    """Cancel a pending GTT on Fyers. Returns ``(response_dict, status_code)``.

    Fyers takes the id in the body of a DELETE (not the path), same as the
    regular ``cancel_order`` call.
    """
    if not trigger_id:
        return {"status": "error", "message": "trigger_id is required"}, 400

    try:
        payload = transform_cancel_gtt(trigger_id)
        logger.info(f"Fyers cancel_gtt payload: {json.dumps(payload)}")

        response = _request("DELETE", _GTT_SYNC, auth, payload)
        logger.info(f"Fyers cancel_gtt raw: status={response.status_code}, body={response.text}")

        response_data = _parse(response)

        if _is_ok(response_data):
            return {
                "status": "success",
                "trigger_id": str(response_data.get("id", trigger_id)),
            }, 200

        return {
            "status": "error",
            "message": response_data.get("message", "Failed to cancel GTT"),
        }, response.status_code

    except httpx.HTTPError as e:
        logger.exception("HTTP error during Fyers GTT cancellation")
        return {"status": "error", "message": f"HTTP error: {e}"}, 500
    except Exception as e:
        logger.exception("Error during Fyers GTT cancellation")
        return {"status": "error", "message": f"General error: {e}"}, 500


def get_gtt_book(auth):
    """List the user's GTTs. Returns ``(response_dict, status_code)``.

    ``data`` is a list of OpenAlgo-normalised GTT objects (see
    ``map_gtt_book``), filtered to pending/transit triggers only. Fyers returns
    one row per GTT with both legs inline, so an OCO is already a single item.
    """
    try:
        response = _request("GET", _GTT_BOOK, auth)
        logger.info(f"Fyers gtt_book raw: status={response.status_code}")

        raw = _parse(response)

        if not _is_ok(raw):
            return {
                "status": "error",
                "message": raw.get("message", "Failed to fetch GTT book"),
            }, response.status_code

        return {"status": "success", "data": map_gtt_book(raw)}, 200

    except httpx.HTTPError as e:
        logger.exception("HTTP error during Fyers GTT book fetch")
        return {"status": "error", "message": f"HTTP error: {e}"}, 500
    except Exception as e:
        logger.exception("Error during Fyers GTT book fetch")
        return {"status": "error", "message": f"General error: {e}"}, 500
