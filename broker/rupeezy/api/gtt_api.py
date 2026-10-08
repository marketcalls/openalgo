# broker/rupeezy/api/gtt_api.py
#
# GTT (single and OCO) over the Vortex GTT API
# (https://vortex.rupeezy.in/docs/latest/gtt-order/). Plugs into OpenAlgo's
# placegttorder / modifygttorder / cancelgttorder / gttorderbook endpoints.
#
# Vortex triggers on its own LTP, so unlike Kite no `last_price` is needed.

from broker.rupeezy.api.client import request_json
from broker.rupeezy.mapping.gtt_data import map_gtt_book, transform_modify_gtt, transform_place_gtt
from utils.logging import get_logger

logger = get_logger(__name__)

_GTT = "/trading/orders/gtt"


class _LocalResponse:
    """Response-like object for requests refused before reaching Vortex."""

    def __init__(self, status_code):
        self.status_code = status_code
        self.status = status_code


def place_gtt_order(data, auth):
    """Create a GTT. Returns (response, response_dict, trigger_id)."""
    try:
        body = transform_place_gtt(data)
    except ValueError as e:
        return _LocalResponse(400), {"status": "error", "message": str(e)}, None

    logger.debug(f"Rupeezy place GTT payload: {body}")
    payload = request_json("POST", _GTT, auth, payload=body)
    if payload.get("status") == "success":
        trigger_id = str((payload.get("data") or {}).get("order_id") or "")
        return _LocalResponse(200), payload, trigger_id or None
    return (
        _LocalResponse(400),
        {"status": "error", "message": payload.get("message", "Failed to place GTT")},
        None,
    )


def _fetch_raw_book(auth):
    return request_json("GET", _GTT, auth)


def modify_gtt_order(data, auth):
    """Modify an active GTT. Returns (response_dict, status_code).

    Vortex modifies leg by leg (each needs its leg id), so the GTT is read from
    the book first.
    """
    trigger_id = data.get("trigger_id")
    if not trigger_id:
        return {"status": "error", "message": "trigger_id is required"}, 400

    raw = _fetch_raw_book(auth)
    if raw.get("status") != "success":
        return {
            "status": "error",
            "message": raw.get("message", "Failed to read the GTT book"),
        }, 502
    existing = next((g for g in raw.get("data") or [] if str(g.get("id")) == str(trigger_id)), None)
    if existing is None:
        return {"status": "error", "message": f"GTT {trigger_id} was not found."}, 404

    try:
        body = transform_modify_gtt(data, existing)
    except ValueError as e:
        return {"status": "error", "message": str(e)}, 400

    logger.debug(f"Rupeezy modify GTT {trigger_id} payload: {body}")
    payload = request_json("PUT", f"{_GTT}/{trigger_id}", auth, payload=body)
    if payload.get("status") == "success":
        return {"status": "success", "trigger_id": str(trigger_id)}, 200
    return {"status": "error", "message": payload.get("message", "Failed to modify GTT")}, 400


def cancel_gtt_order(trigger_id, auth):
    """Cancel a GTT. Returns (response_dict, status_code)."""
    if not trigger_id:
        return {"status": "error", "message": "trigger_id is required"}, 400
    payload = request_json("DELETE", f"{_GTT}/{trigger_id}", auth)
    if payload.get("status") == "success":
        return {"status": "success", "trigger_id": str(trigger_id)}, 200
    return {"status": "error", "message": payload.get("message", "Failed to cancel GTT")}, 400


def get_gtt_book(auth, include_history=False):
    """GTT book. Returns (response_dict, status_code)."""
    raw = _fetch_raw_book(auth)
    if raw.get("status") != "success":
        return {"status": "error", "message": raw.get("message", "Failed to fetch GTT book")}, 400
    return {"status": "success", "data": map_gtt_book(raw, include_history=include_history)}, 200
