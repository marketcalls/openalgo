"""Angel One (SmartAPI) GTT REST integration.

SmartAPI GTT reference: https://smartapi.angelone.in/docs  (section "GTT")

Endpoints (all POST, all under ``/rest/secure/angelbroking/gtt/v1/``)::

    createRule   create a rule            -> data.id
    modifyRule   modify an existing rule  -> data.id
    cancelRule   cancel an existing rule  -> data.id
    ruleDetails  one rule by id
    ruleList     paged list, filtered by a ``status`` array in the body

Native OCO
----------
One OpenAlgo GTT is one Angel rule. An OCO is created with ``gttType: "OCO"``:
the target leg rides in ``triggerprice``/``price`` and the stop-loss leg in
``stoplosstriggerprice``/``stoplossprice``, and Angel cancels the other leg
when one fires. The trigger id is Angel's rule id.

Before this, OpenAlgo built an OCO from two independent single rules and
returned ``"<stoploss_rule_id>-<target_rule_id>"``. Angel did not link them, so
both legs could fire and sell twice. Such composite ids can still be cancelled
(both rules); modifying one is refused (cancel and re-place).

Other Angel-specific quirks handled here:

* Angel GTT has no ``ordertype`` field — a rule always carries an explicit
  ``price`` and fires a **LIMIT** child order (AB9008 "Invalid Price" if the
  price is bogus). A MARKET request is therefore converted to an MPP-protected
  LIMIT, exactly as the zerodha module does.
* ``cancelRule`` needs ``symboltoken`` + ``exchange``, but OpenAlgo's
  ``cancel_gtt_order(trigger_id, auth)`` only receives the id — so the rule is
  looked up through ``ruleDetails`` first. ``modify`` reads it too, to refuse
  a SINGLE <-> OCO change Angel cannot make.
* Headers (Bearer token, X-PrivateKey, X-ClientLocalIP, X-ClientPublicIP,
  X-MACAddress, X-UserType, X-SourceID) are built by the broker's existing
  :func:`broker.angel.api.order_api.get_api_response`, which is reused for
  every call here rather than hand-rolling a second header block.
"""

import json

from broker.angel.api.order_api import get_api_response
from broker.angel.mapping.gtt_data import (
    ACTIVE_GTT_STATUSES,
    is_oco,
    map_gtt_book,
    transform_modify_gtt,
    transform_place_gtt,
)
from database.token_db import get_token
from database.token_db_enhanced import get_symbol_info
from utils.logging import get_logger
from utils.mpp_slab import calculate_protected_price, get_instrument_type_from_symbol

logger = get_logger(__name__)

_GTT_BASE = "/rest/secure/angelbroking/gtt/v1"

# Delimiter of the legacy two-rule OCO trigger id ("<sl_id>-<tg_id>"). Angel rule
# ids are numeric, so "-" can never occur inside one.
_COMPOSITE_DELIMITER = "-"

# ruleList is paged. Angel's own sample uses count=10 (AB9018 is "Invalid Count
# Value", and 10 is the only page size the docs demonstrate), so we page with
# that and stop at a sane ceiling instead of looping forever.
_RULE_LIST_PAGE_SIZE = 10
_RULE_LIST_MAX_PAGES = 25

# Angel GTT error codes -> HTTP-ish status codes. SmartAPI answers business
# failures with HTTP 200 and an ``errorcode``, and the shared
# ``get_api_response`` helper hands back the parsed body only, so this table is
# what the service layer's status_code ends up being.
_ERROR_STATUS = {
    "AB9000": 500,  # Internal Server Error
    "AB9002": 405,  # Method Not Allowed
    "AB9003": 401,  # Invalid Client ID
    "AB9005": 401,  # Invalid Session ID
    "AB9013": 404,  # Invalid Rule ID
}
_DEFAULT_ERROR_STATUS = 400  # AB9001/AB9004/AB9006..AB9012/AB9014..AB9018


class _FakeResponse:
    """Minimal stand-in exposing ``.status`` / ``.status_code`` / ``.text``.

    Angel's shared :func:`get_api_response` returns the parsed body rather than
    an httpx response, so ``place_gtt_order`` synthesises its response object.
    """

    def __init__(self, status_code, text=""):
        self.status_code = status_code
        self.status = status_code
        self.text = text


def _is_ok(response_data):
    """Angel signals success with ``status: true`` (a real bool) + ``message: SUCCESS``.

    ``get_api_response`` returns ``{"status": "error", ...}`` for transport /
    parse failures, and that string is truthy, so the identity check matters.
    """
    return isinstance(response_data, dict) and response_data.get("status") is True


def _error_message(response_data, fallback):
    if not isinstance(response_data, dict):
        return fallback
    return response_data.get("message") or fallback


def _error_status(response_data):
    if not isinstance(response_data, dict):
        return _DEFAULT_ERROR_STATUS
    return _ERROR_STATUS.get(response_data.get("errorcode") or "", _DEFAULT_ERROR_STATUS)


def _gtt_request(path, auth, body, max_retries=0):
    """POST one GTT body and return the parsed Angel response.

    ``max_retries`` defaults to 0 for the mutating endpoints: the shared helper
    retries on transport errors, and a retried ``createRule`` would silently
    create a duplicate GTT. Only the read-only endpoints opt back into retries.
    """
    payload = json.dumps(body)
    logger.info(f"Angel gtt {path} payload: {payload}")
    response_data = get_api_response(
        f"{_GTT_BASE}/{path}", auth, method="POST", payload=payload, max_retries=max_retries
    )
    logger.info(f"Angel gtt {path} raw: {response_data}")
    return response_data


def _rule_id(response_data):
    """Pull ``data.id`` out of a create/modify/cancel response."""
    data = response_data.get("data") or {}
    if not isinstance(data, dict):
        return None
    return str(data.get("id") or "") or None


def _encode_trigger_id(rule_ids):
    """Join Angel rule ids into an OpenAlgo trigger id (two only for a legacy OCO)."""
    return _COMPOSITE_DELIMITER.join(str(rid) for rid in rule_ids)


def _decode_trigger_id(trigger_id):
    """Split an OpenAlgo trigger id back into its Angel rule ids (2 for a legacy OCO)."""
    return [part for part in str(trigger_id).split(_COMPOSITE_DELIMITER) if part]


def _fetch_last_price(symbol, exchange, auth):
    """Fetch LTP from Angel's quote endpoint via the broker's own data handler.

    Only needed for a MARKET SINGLE GTT, where MPP has to buffer around the
    live price (Angel's rule body has no MARKET child-order option).
    """
    from broker.angel.api.data import BrokerData

    try:
        quotes = BrokerData(auth).get_quotes(symbol, exchange)
    except Exception as exc:
        logger.warning(f"Angel gtt: LTP fetch failed for {symbol}@{exchange}: {exc}")
        return None
    if not isinstance(quotes, dict):
        return None
    ltp = quotes.get("ltp")
    return float(ltp) if ltp else None


def _apply_mpp_if_market(data, last_price):
    """Convert MARKET pricetype -> MPP-protected LIMIT.

    Angel's GTT rule carries no ordertype: it always fires a LIMIT child order
    built from the rule's ``price``. So when the user asks for MARKET we mirror
    the zerodha/flattrade pattern: fetch tick_size, compute a Market-Price-
    Protection buffer around the relevant base price, override the limit
    fields, and force pricetype=LIMIT.

    SINGLE -> buffer applied to ``last_price``; ``data["price"]`` overridden.
    OCO    -> buffer applied to each leg's trigger price; ``data["stoploss"]``
              and ``data["target"]`` overridden (action determines buy/sell
              direction for both legs).
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
        if last_price and last_price > 0:
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
        f"Angel GTT MARKET->LIMIT: trigger_type={trigger_type}, action={action}, "
        f"symbol={symbol}, instrument_type={instrument_type}, tick_size={tick_size}, "
        f"price={data.get('price')}, stoploss={data.get('stoploss')}, "
        f"target={data.get('target')}"
    )


def _prepare_market(data, auth):
    """Resolve the LTP a MARKET SINGLE needs, then run MPP.

    Returns an error message string on failure, ``None`` on success. OCO does
    not need an LTP — MPP buffers around each leg's own trigger price.
    """
    if (data.get("pricetype") or "").upper() != "MARKET":
        return None

    last_price = data.get("last_price")
    if (data.get("trigger_type") or "").upper() != "OCO" and not last_price:
        last_price = _fetch_last_price(data["symbol"], data["exchange"], auth)
        if not last_price:
            return "Failed to fetch last_price from Angel quotes"
        data["last_price"] = last_price

    _apply_mpp_if_market(data, last_price)
    return None


def _resolve_token(data):
    """Resolve the Angel ``symboltoken`` for the payload's symbol/exchange."""
    token = get_token(data["symbol"], data["exchange"])
    if token in (None, ""):
        return None
    return token


def _lookup_rule(rule_id, auth):
    """Fetch one rule through ``ruleDetails``; returns the rule dict or None.

    Used by :func:`cancel_gtt_order`, which only receives a trigger id but
    needs ``symboltoken`` + ``exchange`` for Angel's cancel body.
    """
    response_data = _gtt_request("ruleDetails", auth, {"id": str(rule_id)}, max_retries=2)
    if not _is_ok(response_data):
        return None
    rule = response_data.get("data")
    return rule if isinstance(rule, dict) else None


def _cancel_rule(rule_id, symboltoken, exchange, auth):
    """Cancel one Angel rule. Returns ``(ok, response_data)``."""
    body = {"id": str(rule_id), "symboltoken": str(symboltoken), "exchange": exchange}
    response_data = _gtt_request("cancelRule", auth, body)
    return _is_ok(response_data), response_data


def place_gtt_order(data, auth):
    """Create a GTT on Angel. Returns ``(response, response_dict, trigger_id)``.

    SINGLE and OCO are each one ``createRule``; the trigger id is the rule id.
    """
    error = _prepare_market(data, auth)
    if error:
        return _FakeResponse(502), {"status": "error", "message": error}, None

    token = _resolve_token(data)
    if not token:
        message = (
            f"Could not resolve Angel symboltoken for {data.get('symbol')}/{data.get('exchange')}"
        )
        logger.error(message)
        return _FakeResponse(400), {"status": "error", "message": message}, None

    response_data = _gtt_request("createRule", auth, transform_place_gtt(data, token))
    if not _is_ok(response_data):
        return (
            _FakeResponse(_error_status(response_data), json.dumps(response_data)),
            {
                "status": "error",
                "message": _error_message(response_data, "Failed to create GTT rule"),
            },
            None,
        )

    rule_id = _rule_id(response_data)
    if not rule_id:
        message = "Angel returned no rule id"
        logger.error(f"{message}: {response_data}")
        return (
            _FakeResponse(502, json.dumps(response_data)),
            {"status": "error", "message": message},
            None,
        )

    logger.info(f"Angel place_gtt created rule id={rule_id}")
    return _FakeResponse(200, json.dumps(response_data)), response_data, rule_id


def modify_gtt_order(data, auth):
    """Modify an active GTT on Angel. Returns ``(response_dict, status_code)``.

    The rule is read back first: Angel cannot turn a SINGLE rule into an OCO or
    back, and its ``symboltoken``/``exchange`` are what ``modifyRule`` needs.
    A legacy two-rule OCO id is refused (cancel and re-place it).

    Angel's modify body cannot change ``transactiontype``, ``producttype`` or
    ``tradingsymbol``; only prices, quantity and disclosed quantity are
    editable. Those fields in ``data`` are ignored by the broker.
    """
    trigger_id = data.get("trigger_id")
    if not trigger_id:
        return {"status": "error", "message": "trigger_id is required"}, 400

    rule_ids = _decode_trigger_id(trigger_id)
    if len(rule_ids) != 1:
        return (
            {
                "status": "error",
                "message": (
                    f"trigger_id '{trigger_id}' is a legacy two-rule OCO; Angel cannot modify "
                    f"it as one GTT. Cancel it and place a new OCO."
                ),
            },
            400,
        )

    rule = _lookup_rule(rule_ids[0], auth)
    if not rule:
        return {"status": "error", "message": f"Could not fetch Angel GTT rule {trigger_id}"}, 404

    stored_oco = (rule.get("gttType") or "").upper() == "OCO"
    if stored_oco != is_oco(data):
        stored, asked = ("OCO", "SINGLE") if stored_oco else ("SINGLE", "OCO")
        return (
            {
                "status": "error",
                "message": (
                    f"GTT {trigger_id} is {stored} on Angel but the request is {asked}. Angel "
                    f"cannot convert a rule between SINGLE and OCO — cancel and re-place instead."
                ),
            },
            400,
        )

    error = _prepare_market(data, auth)
    if error:
        return {"status": "error", "message": error}, 502

    token = rule.get("symboltoken") or _resolve_token(data)
    response_data = _gtt_request("modifyRule", auth, transform_modify_gtt(data, token, rule_ids[0]))
    if not _is_ok(response_data):
        message = _error_message(response_data, "Failed to modify GTT rule")
        return {"status": "error", "message": message}, _error_status(response_data)

    return {"status": "success", "trigger_id": _rule_id(response_data) or rule_ids[0]}, 200


def cancel_gtt_order(trigger_id, auth):
    """Cancel an active GTT on Angel. Returns ``(response_dict, status_code)``.

    A legacy two-rule OCO trigger id cancels both underlying rules, aborting on
    the first failure (the surviving leg is reported in the error message so
    the caller can retry it). Angel's ``cancelRule`` needs ``symboltoken`` +
    ``exchange``, which are not part of OpenAlgo's cancel contract, so each
    rule is first read back through ``ruleDetails``.
    """
    if not trigger_id:
        return {"status": "error", "message": "trigger_id is required"}, 400

    rule_ids = _decode_trigger_id(trigger_id)
    if not rule_ids:
        return {"status": "error", "message": "trigger_id is required"}, 400

    cancelled_ids = []
    for rule_id in rule_ids:
        rule = _lookup_rule(rule_id, auth)
        if not rule:
            message = f"Could not fetch Angel GTT rule {rule_id}"
            if cancelled_ids:
                message += f" (already cancelled: {', '.join(cancelled_ids)})"
            return {"status": "error", "message": message}, 404

        ok, response_data = _cancel_rule(
            rule_id, rule.get("symboltoken", ""), rule.get("exchange", ""), auth
        )
        if not ok:
            message = _error_message(response_data, f"Failed to cancel GTT rule {rule_id}")
            if cancelled_ids:
                message += f" (already cancelled: {', '.join(cancelled_ids)})"
            return {"status": "error", "message": message}, _error_status(response_data)

        cancelled_ids.append(_rule_id(response_data) or str(rule_id))

    return {"status": "success", "trigger_id": _encode_trigger_id(cancelled_ids)}, 200


def get_gtt_book(auth, include_history=False):
    # include_history is accepted for interface parity; this mapper still
    # returns active triggers only until its status vocabulary is mapped.
    """List the user's live GTTs. Returns ``(response_dict, status_code)``.

    Angel's ``ruleList`` takes the status filter in the request body, so only
    the statuses that can still fire (NEW / ACTIVE / SENTTOEXCHANGE) are asked
    for — CANCELLED, EXPIRED and TRIGGERED never reach the mapper. The endpoint
    is paged; pages are walked until a short page comes back (or the ceiling is
    hit).
    """
    rules = []
    page = 1
    last_response = {}

    while page <= _RULE_LIST_MAX_PAGES:
        body = {
            "status": list(ACTIVE_GTT_STATUSES),
            "page": page,
            "count": _RULE_LIST_PAGE_SIZE,
        }
        response_data = _gtt_request("ruleList", auth, body, max_retries=2)
        last_response = response_data

        if not _is_ok(response_data):
            if page > 1 and rules:
                # Partial listing beats no listing; log and use what we have.
                logger.warning(
                    f"Angel gtt_book: page {page} failed, returning {len(rules)} rules "
                    f"collected so far: {response_data}"
                )
                break
            return (
                {
                    "status": "error",
                    "message": _error_message(response_data, "Failed to fetch GTT book"),
                },
                _error_status(response_data),
            )

        # Angel's published sample shows ``data`` as a single object; the live
        # API returns a list. Accept both, and treat null as an empty page.
        page_data = response_data.get("data")
        if isinstance(page_data, dict):
            page_rules = [page_data]
        elif isinstance(page_data, list):
            page_rules = page_data
        else:
            page_rules = []

        rules.extend(page_rules)
        if len(page_rules) < _RULE_LIST_PAGE_SIZE:
            break
        page += 1
    else:
        logger.warning(
            f"Angel gtt_book: stopped at the {_RULE_LIST_MAX_PAGES}-page ceiling; "
            f"the book may be truncated. Last response: {last_response}"
        )

    return {"status": "success", "data": map_gtt_book(rules)}, 200
