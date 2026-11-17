"""Pocketful GTT (Good Till Triggered) rules.

Routes, from Pocketful's docs and the SDK 0.1.2 route table:

    POST   /api/v1/event/gtt                       create-gtt-order.md; SDK api.gtt.create
    PUT    /api/v1/event/gtt                       modify-gtt-order.md; SDK api.gtt.order.modify
    DELETE /api/v1/event/gtt/{client_id}/{id}      cancel-gtt-order.md; SDK api.gtt.order.cancel
    GET    /api/v1/event/gtt/{client_id}           fetch-gtt-order.md

The fetch route is where the two sources part: the docs give the client id as
a path segment (and list it again under "Query Params"), the SDK's route sends
it only as ``?client_id=``. The docs are followed, and the query parameter the
same page lists is sent too.

What is supported and refused, and why, is in mapping/gtt_data.py: SINGLE
only, MARKET sent as an MPP-protected LIMIT measured from the trigger.

Contract (services/*gtt*_service.py):

    place_gtt_order(data, auth)   -> (response, data, trigger_id)
    modify_gtt_order(data, auth)  -> (data, status_code)
    cancel_gtt_order(id, auth)    -> (data, status_code)
    get_gtt_book(auth, include_history=False) -> (data, status_code)

A create, modify or cancel that was sent but not answered may have reached
Pocketful, so it is never retried here: the trader is told to check the GTT
list before trying again.
"""

from urllib.parse import quote

from broker.pocketful.api.baseurl import client_id, pocketful_request
from broker.pocketful.mapping.gtt_data import (
    ACTION_TYPE,
    GttRefused,
    broker_reason,
    build_gtt_order,
    expiry_date,
    gtt_rows,
    map_gtt_book,
    row_status,
    today_ist,
    valid_trigger_id,
)
from utils.logging import get_logger

logger = get_logger(__name__)

GTT_PATH = "/api/v1/event/gtt"

NO_CLIENT_ID = "Your Pocketful session carries no client id. Log in to Pocketful again and retry."
BAD_ID = "That GTT id is not one Pocketful issued. Copy the id from the GTT list and retry."
NO_GTT_DATA = "no gtt data found"


class GttAnswer:
    """The response object place_gtt_order hands the service (it reads ``.status``)."""

    def __init__(self, status_code):
        self.status_code = status_code
        self.status = status_code


def _failed_status(response):
    return response.status_code if response.status_code >= 400 else 400


def _refusal_text(response, action):
    reason = broker_reason(response.message)
    if reason:
        return f"Pocketful refused to {action} the GTT: {reason}"
    return f"Pocketful refused to {action} the GTT without giving a reason. Try again in a moment."


def _read_rules(auth, account):
    """(rows, None) from Pocketful's GTT list, or (None, (error dict, status))."""
    path = f"{GTT_PATH}/{quote(account, safe='')}"
    try:
        response = pocketful_request("GET", path, auth, params={"client_id": account})
    except Exception:
        logger.exception("Pocketful GTT list could not be read")
        return None, (
            {
                "status": "error",
                "message": "OpenAlgo could not reach Pocketful for the GTT list. "
                "Check your connection and try again.",
            },
            502,
        )

    if response.data is None:
        return None, (
            {
                "status": "error",
                "message": "Pocketful sent the GTT list in a form OpenAlgo could not read. "
                "Try again in a moment.",
            },
            502,
        )

    if not response.ok:
        # The docs' fetch error example is "Error from backend: (500)-no gtt
        # data found": an account with no rules, not a failure.
        if NO_GTT_DATA in response.message.lower():
            return [], None
        logger.error(
            f"Pocketful GTT list read failed: HTTP {response.status_code}, {response.message!r}"
        )
        return None, (
            {"status": "error", "message": _refusal_text(response, "list")},
            _failed_status(response),
        )

    return gtt_rows(response.payload), None


def place_gtt_order(data, auth):
    """Create a SINGLE GTT rule. Returns (response, response_dict, trigger_id)."""
    account = client_id(auth)
    if not account:
        return GttAnswer(400), {"status": "error", "message": NO_CLIENT_ID}, None

    try:
        order, info = build_gtt_order(data, account)
        expiry = expiry_date(data, info, today_ist())
    except GttRefused as refusal:
        logger.info(f"Pocketful GTT not sent: {refusal}")
        return GttAnswer(refusal.status_code), {"status": "error", "message": str(refusal)}, None

    body = {"action_type": ACTION_TYPE, "expiry_time": expiry, "order": order}
    logger.info(
        f"Pocketful GTT create: {data.get('exchange')}:{data.get('symbol')} "
        f"{order['order_side']} {order['quantity']} trigger={order['trigger_price']} "
        f"limit={order['price']} expiry={expiry}"
    )

    try:
        response = pocketful_request("POST", GTT_PATH, auth, payload=body)
    except Exception:
        logger.exception("Pocketful GTT create: no answer")
        return (
            GttAnswer(502),
            {
                "status": "error",
                "message": "Pocketful did not answer, so the GTT may or may not have been "
                "created. Check the GTT list before placing it again.",
            },
            None,
        )

    if response.data is None:
        return (
            GttAnswer(502),
            {
                "status": "error",
                "message": "Pocketful's answer could not be read, so the GTT may or may not "
                "have been created. Check the GTT list before placing it again.",
            },
            None,
        )

    if not response.ok:
        logger.error(
            f"Pocketful GTT create refused: HTTP {response.status_code}, {response.message!r}"
        )
        return (
            GttAnswer(_failed_status(response)),
            {"status": "error", "message": _refusal_text(response, "place")},
            None,
        )

    payload = response.payload if isinstance(response.payload, dict) else {}
    trigger_id = str(payload.get("id") or "")
    if not trigger_id:
        logger.error("Pocketful GTT create succeeded without a GTT id")
        return (
            GttAnswer(502),
            {
                "status": "error",
                "message": "Pocketful accepted the GTT but did not return its id. Check "
                "the GTT list before placing it again.",
            },
            None,
        )

    return GttAnswer(200), {"status": "success", "trigger_id": trigger_id}, trigger_id


def modify_gtt_order(data, auth):
    """Replace an active SINGLE GTT rule. Returns (response_dict, status_code).

    The rule is read first: it must still be active and a single trigger, its
    instrument and side cannot change (OpenAlgo's modify contract), and its
    expiry is kept, since OpenAlgo's modify request carries none.
    """
    trigger_id = str(data.get("trigger_id") or "")
    if not valid_trigger_id(trigger_id):
        return {"status": "error", "message": BAD_ID}, 400

    account = client_id(auth)
    if not account:
        return {"status": "error", "message": NO_CLIENT_ID}, 400

    try:
        order, _info = build_gtt_order(data, account)
    except GttRefused as refusal:
        logger.info(f"Pocketful GTT modify not sent: {refusal}")
        return {"status": "error", "message": str(refusal)}, refusal.status_code

    rows, failure = _read_rules(auth, account)
    if failure:
        return failure

    current = next((row for row in rows if str(row.get("id")) == trigger_id), None)
    if current is None or row_status(current) != "active":
        return {
            "status": "error",
            "message": "This GTT is no longer active at Pocketful: it may have fired, "
            "expired or been cancelled. Check the GTT list.",
        }, 404

    if current.get("action_type") != ACTION_TYPE:
        return {
            "status": "error",
            "message": "This GTT is not a single trigger, so it cannot be changed from "
            "OpenAlgo. Change it in Pocketful's app.",
        }, 400

    held = current.get("order") if isinstance(current.get("order"), dict) else {}
    held_token = str(held.get("token") or held.get("instrument_token") or "")
    held_side = str(held.get("order_side") or "").upper()
    if held_token != order["instrument_token"] or held_side != order["order_side"]:
        return {
            "status": "error",
            "message": "A GTT's symbol, exchange and side cannot be changed. Cancel it "
            "and place a new one.",
        }, 400

    expiry = str(current.get("expiry_time") or "")
    if not expiry:
        return {
            "status": "error",
            "message": "Pocketful did not report this GTT's expiry, so it was not changed. "
            "Change it in Pocketful's app.",
        }, 502

    order["device"] = "web"
    body = {"expiry_time": expiry, "action_type": ACTION_TYPE, "id": trigger_id, "order": order}
    logger.info(
        f"Pocketful GTT modify {trigger_id}: trigger={order['trigger_price']} "
        f"limit={order['price']} qty={order['quantity']}"
    )

    try:
        response = pocketful_request("PUT", GTT_PATH, auth, payload=body)
    except Exception:
        logger.exception("Pocketful GTT modify: no answer")
        return {
            "status": "error",
            "message": "Pocketful did not answer, so the change may or may not have been "
            "made. Check the GTT list before trying again.",
        }, 502

    if not response.ok:
        logger.error(
            f"Pocketful GTT modify refused: HTTP {response.status_code}, {response.message!r}"
        )
        if response.data is None:
            return {
                "status": "error",
                "message": "Pocketful's answer could not be read, so the change may or may "
                "not have been made. Check the GTT list before trying again.",
            }, 502
        return {
            "status": "error",
            "message": _refusal_text(response, "change"),
        }, _failed_status(response)

    payload = response.payload if isinstance(response.payload, dict) else {}
    return {"status": "success", "trigger_id": str(payload.get("id") or trigger_id)}, 200


def cancel_gtt_order(trigger_id, auth):
    """Cancel a GTT rule. Returns (response_dict, status_code)."""
    trigger_id = str(trigger_id or "")
    if not valid_trigger_id(trigger_id):
        return {"status": "error", "message": BAD_ID}, 400

    account = client_id(auth)
    if not account:
        return {"status": "error", "message": NO_CLIENT_ID}, 400

    path = f"{GTT_PATH}/{quote(account, safe='')}/{quote(trigger_id, safe='')}"
    try:
        response = pocketful_request("DELETE", path, auth)
    except Exception:
        logger.exception("Pocketful GTT cancel: no answer")
        return {
            "status": "error",
            "message": "Pocketful did not answer, so the GTT may or may not have been "
            "cancelled. Check the GTT list before trying again.",
        }, 502

    if not response.ok:
        logger.error(
            f"Pocketful GTT cancel refused: HTTP {response.status_code}, {response.message!r}"
        )
        if response.data is None:
            return {
                "status": "error",
                "message": "Pocketful's answer could not be read, so the GTT may or may not "
                "have been cancelled. Check the GTT list before trying again.",
            }, 502
        return {
            "status": "error",
            "message": _refusal_text(response, "cancel"),
        }, _failed_status(response)

    payload = response.payload if isinstance(response.payload, dict) else {}
    return {"status": "success", "trigger_id": str(payload.get("id") or trigger_id)}, 200


def get_gtt_book(auth, include_history=False):
    """Pocketful's GTT rules in OpenAlgo's GTT book shape. Returns (dict, status_code)."""
    account = client_id(auth)
    if not account:
        return {"status": "error", "message": NO_CLIENT_ID}, 400

    rows, failure = _read_rules(auth, account)
    if failure:
        return failure
    return {"status": "success", "data": map_gtt_book(rows, include_history=include_history)}, 200
