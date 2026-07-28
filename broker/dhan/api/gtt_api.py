# Dhan Forever Order REST integration.
# Dhan v2 reference: https://dhanhq.co/docs/v2/forever/

import json
import os

import httpx

from broker.dhan.api.baseurl import get_url
from broker.dhan.mapping.gtt_data import (
    map_gtt_book,
    transform_modify_gtt,
    transform_place_gtt,
)
from database.auth_db import get_user_id, verify_api_key
from utils.logging import get_logger

logger = get_logger(__name__)


# Dedicated HTTP/1.1-only client for Dhan Forever Orders. Their AWS ELB returns
# bogus 301s (Location: https://api.dhan.co:443/v2/) on HTTP/2 POST/PUT/DELETE
# to /v2/forever/orders. Dhan's own SDK uses `requests` (HTTP/1.1), which works.
_dhan_gtt_client = None


def _get_client():
    global _dhan_gtt_client
    if _dhan_gtt_client is None:
        _dhan_gtt_client = httpx.Client(http2=False, timeout=30.0)
    return _dhan_gtt_client


class _FakeResponse:
    """Minimal stand-in so the service layer's ``res.status`` access keeps working
    when we short-circuit before issuing the HTTP call."""

    def __init__(self, status_code):
        self.status_code = status_code
        self.status = status_code
        self.text = ""


def _resolve_client_id(api_key):
    """Resolve dhanClientId from BROKER_API_KEY env (``client_id:::api_key``) or DB."""
    broker_api_key = os.getenv("BROKER_API_KEY", "")
    if ":::" in broker_api_key:
        return broker_api_key.split(":::")[0]
    if api_key:
        user_id = verify_api_key(api_key)
        if user_id:
            return get_user_id(user_id)
    return None


def _headers(auth, client_id=None):
    headers = {
        "access-token": auth,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if client_id:
        headers["client-id"] = client_id
    return headers


def place_gtt_order(data, auth):
    """Create a Forever Order on Dhan. Returns ``(response, response_dict, trigger_id)``.

    Mirrors ``place_order_api``: the dhanClientId is resolved from
    ``BROKER_API_KEY`` (or DB fallback) and injected before the mapper builds
    the JSON body.
    """
    client_id = _resolve_client_id(data.get("apikey"))
    if not client_id:
        return (
            _FakeResponse(401),
            {"status": "error", "message": "Could not resolve Dhan client id"},
            None,
        )
    data["dhan_client_id"] = client_id

    payload = json.dumps(transform_place_gtt(data))
    logger.info(f"Dhan place_gtt payload: {payload}")

    client = _get_client()
    response = client.post(
        get_url("/v2/forever/orders"),
        headers=_headers(auth, client_id=client_id),
        content=payload,
    )
    response.status = response.status_code  # parity with other order APIs
    logger.info(
        f"Dhan place_gtt raw: status={response.status_code}, "
        f"location={response.headers.get('location')}, "
        f"server={response.headers.get('server')}, body={response.text[:300]}"
    )

    try:
        response_data = json.loads(response.text)
    except json.JSONDecodeError:
        return (
            response,
            {"status": "error", "message": response.text or "Invalid response"},
            None,
        )

    trigger_id = None
    if response.status_code in (200, 201) and isinstance(response_data, dict):
        trigger_id = str(response_data.get("orderId") or "") or None

    return response, response_data, trigger_id


def _lookup_existing_legs(trigger_id, auth):
    """Fetch the live Forever Order and return list of (legName, price) tuples
    matching the given orderId. Used by modify to align legName with whatever
    Dhan actually stored (the published docs say ENTRY_LEG/TARGET_LEG/
    STOP_LOSS_LEG, but live data shows SINGLE BUYs may be stored as
    STOP_LOSS_LEG)."""
    try:
        client = _get_client()
        response = client.get(get_url("/v2/forever/orders"), headers=_headers(auth))
        if response.status_code != 200:
            return []
        raw = json.loads(response.text)
    except (json.JSONDecodeError, Exception) as exc:
        logger.warning(f"Dhan modify_gtt: legName lookup failed: {exc}")
        return []

    if not isinstance(raw, list):
        return []
    matches = []
    for order in raw:
        if str(order.get("orderId", "")) == str(trigger_id):
            matches.append(
                (
                    (order.get("legName") or "").upper(),
                    float(order.get("price", 0) or 0),
                )
            )
    return matches


def modify_gtt_order(data, auth):
    """Modify a Forever Order on Dhan. Returns ``(response_dict, status_code)``.

    Dhan's PUT modifies one leg at a time. For OCO we send two sequential PUTs
    (``STOP_LOSS_LEG`` then ``TARGET_LEG``); for SINGLE we look up the leg
    Dhan actually stored (it can be ENTRY_LEG/STOP_LOSS_LEG/TARGET_LEG
    depending on the action + trigger relative to LTP at place-time) and PUT
    that one. We bail on the first leg failure for OCO.
    """
    trigger_id = data.get("trigger_id")
    if not trigger_id:
        return {"status": "error", "message": "trigger_id is required"}, 400

    client_id = _resolve_client_id(data.get("apikey"))
    if not client_id:
        return {"status": "error", "message": "Could not resolve Dhan client id"}, 401
    data["dhan_client_id"] = client_id

    trigger_type = (data.get("trigger_type") or "").upper()

    if trigger_type == "OCO":
        leg_names = ["STOP_LOSS_LEG", "TARGET_LEG"]
    else:
        existing = _lookup_existing_legs(trigger_id, auth)
        if existing:
            single_leg = existing[0][0] or "ENTRY_LEG"
            logger.info(
                f"Dhan modify_gtt: resolved SINGLE legName={single_leg} from forever book"
            )
            leg_names = [single_leg]
        else:
            logger.warning(
                f"Dhan modify_gtt: could not resolve legName for {trigger_id}, "
                f"falling back to ENTRY_LEG"
            )
            leg_names = ["ENTRY_LEG"]

    # SINGLE-only: if user-submitted pricetype is LIMIT but price is 0, coerce
    # to MARKET — Dhan rejects LIMIT+price=0 with DH-905 even though place
    # accepts it for MARKET GTTs. UI clients may default to LIMIT regardless
    # of how the order was originally placed. (For OCO, data["price"] is
    # unused; both legs use stoploss/target as their limits.)
    if (
        trigger_type != "OCO"
        and (data.get("pricetype") or "").upper() == "LIMIT"
        and float(data.get("price") or 0) == 0
    ):
        logger.info(
            "Dhan modify_gtt: coercing pricetype LIMIT→MARKET (SINGLE price=0 invalid for LIMIT)"
        )
        data["pricetype"] = "MARKET"

    headers = _headers(auth, client_id=client_id)
    client = _get_client()
    url = get_url(f"/v2/forever/orders/{trigger_id}")

    last_response_data = {}
    last_status = 200
    for leg_name in leg_names:
        payload = json.dumps(transform_modify_gtt(data, leg_name))
        logger.info(f"Dhan modify_gtt ({trigger_id}, {leg_name}) payload: {payload}")

        response = client.put(url, headers=headers, content=payload)
        logger.info(
            f"Dhan modify_gtt ({leg_name}) raw: status={response.status_code}, "
            f"location={response.headers.get('location')}, body={response.text[:300]}"
        )

        try:
            response_data = json.loads(response.text)
        except json.JSONDecodeError:
            return (
                {"status": "error", "message": f"{leg_name}: invalid response"},
                response.status_code,
            )

        if response.status_code != 200 or not (
            isinstance(response_data, dict) and response_data.get("orderId")
        ):
            msg = (
                response_data.get("errorMessage")
                or response_data.get("message")
                or f"Failed to modify {leg_name}"
            )
            return {"status": "error", "message": msg}, response.status_code

        last_response_data = response_data
        last_status = response.status_code

    return (
        {
            "status": "success",
            "trigger_id": str(last_response_data.get("orderId", trigger_id)),
        },
        last_status,
    )


def cancel_gtt_order(trigger_id, auth):
    """Cancel a Forever Order on Dhan. Returns ``(response_dict, status_code)``."""
    if not trigger_id:
        return {"status": "error", "message": "trigger_id is required"}, 400

    client = _get_client()
    response = client.delete(
        get_url(f"/v2/forever/orders/{trigger_id}"),
        headers=_headers(auth),
    )
    logger.info(
        f"Dhan cancel_gtt raw: status={response.status_code}, "
        f"location={response.headers.get('location')}, body={response.text[:300]}"
    )

    try:
        response_data = json.loads(response.text)
    except json.JSONDecodeError:
        return (
            {"status": "error", "message": response.text or "Invalid response"},
            response.status_code,
        )

    if (
        response.status_code == 200
        and isinstance(response_data, dict)
        and response_data.get("orderId")
    ):
        return {"status": "success", "trigger_id": str(response_data["orderId"])}, 200

    msg = (
        response_data.get("errorMessage")
        or response_data.get("message")
        or "Failed to cancel GTT"
    )
    return {"status": "error", "message": msg}, response.status_code


def get_gtt_book(auth):
    """List all Forever Orders for the user. Returns ``(response_dict, status_code)``.

    The returned dict has ``status`` and ``data`` where ``data`` is the
    OpenAlgo-normalised list (see :func:`map_gtt_book`).
    """
    # Dhan's published docs say GET /v2/forever/all but their official SDK
    # and live API use GET /v2/forever/orders. /all returns 404.
    client = _get_client()
    response = client.get(
        get_url("/v2/forever/orders"),
        headers=_headers(auth),
    )
    logger.info(
        f"Dhan gtt_book raw: status={response.status_code}, "
        f"location={response.headers.get('location')}, "
        f"server={response.headers.get('server')}, "
        f"content_type={response.headers.get('content-type')}, "
        f"body_len={len(response.text)}"
    )
    logger.info(f"Dhan gtt_book raw body: {response.text}")

    try:
        raw = json.loads(response.text)
    except json.JSONDecodeError:
        return (
            {"status": "error", "message": response.text or "Invalid response"},
            response.status_code,
        )

    if response.status_code != 200:
        msg = raw.get("errorMessage") if isinstance(raw, dict) else None
        return (
            {"status": "error", "message": msg or "Failed to fetch Forever orders"},
            response.status_code,
        )

    # Dhan returns a bare list; some endpoints wrap in {data: [...]}.
    payload = raw if isinstance(raw, list) else raw.get("data", [])
    return {"status": "success", "data": map_gtt_book(payload)}, 200
