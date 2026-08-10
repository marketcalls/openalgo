"""SMIFS God Quant order operations for OpenAlgo.

Every function receives the decrypted SMIFS access token as `auth` and puts
it in the `access-token` header. Symbol/token translation uses OpenAlgo's
shared master-contract helpers (get_token / get_symbol).
"""
import json

from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

from broker.smifs.api.baseurl import get_url
from broker.smifs.mapping.transform_data import (
    transform_data, transform_modify_order_data, map_exchange, reverse_map_product_type,
)
from database.token_db import get_token

logger = get_logger(__name__)


def _headers(auth):
    return {"access-token": auth, "Content-Type": "application/json"}


def _get(path, auth):
    client = get_httpx_client()
    r = client.get(get_url(path), headers=_headers(auth))
    r.status = r.status_code
    try:
        return r, r.json()
    except Exception:  # noqa: BLE001
        return r, {}


def get_order_book(auth):
    _, data = _get("/v1/orders", auth)
    return data


def get_trade_book(auth):
    _, data = _get("/v1/orders/trades", auth)
    return data


def get_positions(auth):
    _, data = _get("/v1/positions", auth)
    return data


def get_holdings(auth):
    _, data = _get("/v1/holdings", auth)
    return data


def get_open_position(tradingsymbol, exchange, product, auth):
    token = get_token(tradingsymbol, exchange)
    positions = get_positions(auth)
    for p in (positions or []):
        if str(p.get("securityId")) == str(token) and p.get("productType") == product:
            return str(p.get("netQty", "0"))
    return "0"


def place_order_api(data, auth):
    token = get_token(data["symbol"], data["exchange"])
    payload = transform_data(data, token)
    client = get_httpx_client()
    r = client.post(get_url("/v1/orders"), headers=_headers(auth), content=json.dumps(payload))
    r.status = r.status_code
    try:
        response = r.json()
    except Exception:  # noqa: BLE001
        response = {}
    orderid = response.get("orderId")
    return r, response, orderid


def place_smartorder_api(data, auth):
    """Position-delta order: reduce to a target quantity, then place the difference."""
    target = int(data.get("position_size", 0))
    current = int(get_open_position(data["symbol"], data["exchange"],
                                    map_product_delta(data.get("product", "MIS")), auth) or 0)
    delta = target - current
    if delta == 0:
        class _R:  # minimal shim so callers can read .status
            status = 200
        return _R(), {"status": "success", "message": "no change"}, None
    order = dict(data)
    order["action"] = "BUY" if delta > 0 else "SELL"
    order["quantity"] = abs(delta)
    return place_order_api(order, auth)


def map_product_delta(product):
    return {"CNC": "CNC", "MIS": "INTRADAY", "NRML": "MARGIN"}.get((product or "MIS").upper(), "INTRADAY")


def modify_order(data, auth):
    payload = transform_modify_order_data(data)
    orderid = data["orderid"]
    client = get_httpx_client()
    r = client.put(get_url(f"/v1/orders/{orderid}"), headers=_headers(auth), content=json.dumps(payload))
    if r.status_code == 200:
        return {"status": "success", "orderid": orderid}, 200
    return {"status": "error", "message": _msg(r)}, r.status_code


def cancel_order(orderid, auth):
    client = get_httpx_client()
    r = client.delete(get_url(f"/v1/orders/{orderid}"), headers=_headers(auth))
    if r.status_code == 200:
        return {"status": "success", "orderid": orderid}, 200
    return {"status": "error", "message": _msg(r)}, r.status_code


def cancel_all_orders_api(data, auth):
    orders = get_order_book(auth) or []
    canceled, failed = [], []
    for o in orders:
        status = str(o.get("orderStatus", "")).upper()
        if status in ("TRANSIT", "PENDING", "PARTIALLY_FILLED"):
            oid = o.get("orderId")
            res, code = cancel_order(oid, auth)
            (canceled if code == 200 else failed).append(oid)
    return canceled, failed


def close_all_positions(current_api_key, auth):
    positions = get_positions(auth) or []
    for p in positions:
        net = int(p.get("netQty", 0) or 0)
        if net == 0:
            continue
        order = {
            "symbol": p.get("tradingSymbol"),
            "exchange": map_exchange(p.get("exchangeSegment")),
            "action": "SELL" if net > 0 else "BUY",
            "quantity": abs(net),
            "pricetype": "MARKET",
            # close in the SAME product the position is held in, else an
            # intraday offset is placed while the real position stays open
            "product": reverse_map_product_type(p.get("productType")),
        }
        place_order_api(order, auth)
    return {"status": "success", "message": "positions squared off"}, 200


def _msg(r):
    try:
        return r.json().get("errorMessage", f"HTTP {r.status_code}")
    except Exception:  # noqa: BLE001
        return f"HTTP {r.status_code}"
