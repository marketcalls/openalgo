# Angel One (SmartAPI) GTT payload transforms (OpenAlgo <-> Angel).
# SmartAPI GTT reference: https://smartapi.angelone.in/docs  (section "GTT")
#
# Angel's GTT rule is a *single* trigger: one triggerprice, one child order.
# There is no native OCO rule type, so OpenAlgo's OCO is expressed as two
# independent Angel rules (see the module docstring of api/gtt_api.py).
# The transforms below therefore always return a *list* of (leg_label, body)
# pairs so the API layer can drive one or two HTTP calls uniformly.

from broker.angel.mapping.transform_data import map_product_type, reverse_map_product_type
from database.token_db import get_br_symbol, get_oa_symbol

# Angel's GTT engine has no ordertype field: a rule always carries an explicit
# `price` and fires a LIMIT child order. Exposed here so the book mapper and
# the MPP logic in gtt_api.py agree on what Angel actually stores.
GTT_CHILD_PRICETYPE = "LIMIT"

# Angel's create-rule payload carries a validity in days. It is not shown in the
# published request sample but error code AB9016 ("Invalid Time Period") proves
# the field is validated server-side, so we always send an explicit value rather
# than relying on an undocumented default.
DEFAULT_TIME_PERIOD_DAYS = 365

# The only GTT statuses Angel's docs name are the five in the ruleList request
# sample: NEW, CANCELLED, ACTIVE, SENTTOEXCHANGE, FORALL (FORALL reads as a
# request-side wildcard, not a state a rule is ever in). Of the real states,
# only these three describe a rule that can still fire, so only these three are
# ever asked for -- which is what makes the OpenAlgo GTT book active-only for
# Angel (see docs/api/order-management/gttorderbook.md).
ACTIVE_GTT_STATUSES = ("NEW", "ACTIVE", "SENTTOEXCHANGE")

# Display mapping. EXPIRED / TRIGGERED / REJECTED are NOT documented by Angel;
# they are carried defensively in case the live API reports a terminal state the
# docs omit. They can only ever be hit if ACTIVE_GTT_STATUSES is widened -- the
# mapper drops any status absent from ACTIVE_GTT_STATUSES regardless.
_STATUS_MAP = {
    "NEW": "active",
    "ACTIVE": "active",
    "SENTTOEXCHANGE": "active",
    "CANCELLED": "cancelled",
    "EXPIRED": "expired",
    "TRIGGERED": "triggered",
    "REJECTED": "rejected",
}

# Angel's GTT docs state that only DELIVERY and MARGIN product types are
# accepted (the engine currently covers NSE/BSE cash only). The generic order
# mapper yields DELIVERY / CARRYFORWARD / INTRADAY, so CARRYFORWARD (NRML) is
# folded onto MARGIN — Angel's cash-segment leveraged product — and INTRADAY
# onto MARGIN as well. MIS is rejected upstream by the GTT schema, so in
# practice only CNC -> DELIVERY and NRML -> MARGIN occur.
_GTT_PRODUCT_OVERRIDE = {
    "CARRYFORWARD": "MARGIN",
    "INTRADAY": "MARGIN",
}

_GTT_REVERSE_PRODUCT_OVERRIDE = {
    "MARGIN": "NRML",
}


def map_gtt_product_type(product):
    """Map an OpenAlgo product (CNC/NRML) to an Angel *GTT* producttype.

    Reuses the broker's existing :func:`map_product_type` and then applies the
    GTT-only narrowing documented above (AB9015 "Invalid Product Type" is what
    Angel returns if CARRYFORWARD reaches the GTT endpoint).
    """
    angel_product = map_product_type(product)
    return _GTT_PRODUCT_OVERRIDE.get(angel_product, angel_product)


def reverse_map_gtt_product_type(producttype):
    """Map an Angel GTT producttype back to an OpenAlgo product."""
    producttype = (producttype or "").upper()
    if producttype in _GTT_REVERSE_PRODUCT_OVERRIDE:
        return _GTT_REVERSE_PRODUCT_OVERRIDE[producttype]
    return reverse_map_product_type(producttype) or "CNC"


def _fmt(value):
    """Angel's GTT payloads carry every numeric as a string ("qty":"1").

    Integral values are rendered without a decimal tail so the wire format
    matches the published samples exactly ("195", not "195.0").
    """
    number = float(value or 0)
    return str(int(number)) if number.is_integer() else str(number)


def _resolve_single_trigger(data):
    """For SINGLE GTT, resolve the active trigger from new fields if the legacy
    ``trigger_price`` alias was not pre-populated by the schema (e.g., the UI
    modify route bypasses schema)."""
    if data.get("trigger_price") not in (None, "", 0, 0.0):
        return float(data["trigger_price"])
    sl = data.get("triggerprice_sl") or 0
    tg = data.get("triggerprice_tg") or 0
    return float(sl) if float(sl) > 0 else float(tg)


def _legs(data):
    """Resolve the (leg_label, trigger, limit_price) tuples for this payload.

    SINGLE -> one leg. OCO -> the stop-loss leg first (lower trigger), then the
    target leg, so the ordering of the two Angel rule ids inside a composite
    trigger id is always ``<sl_rule_id>-<tg_rule_id>``.
    """
    if (data.get("trigger_type") or "").upper() == "OCO":
        return [
            ("SL", float(data["triggerprice_sl"]), float(data["stoploss"])),
            ("TG", float(data["triggerprice_tg"]), float(data["target"])),
        ]
    return [("SINGLE", _resolve_single_trigger(data), float(data.get("price") or 0))]


def transform_place_gtt(data, token):
    """Build Angel ``gtt/v1/createRule`` bodies for an OpenAlgo place-GTT payload.

    Returns ``[(leg_label, body), ...]`` — one entry for SINGLE, two for OCO
    (stop-loss leg first). Angel's create-rule body is flat:
    ``tradingsymbol, symboltoken, exchange, transactiontype, producttype,
    price, qty, triggerprice, disclosedqty`` (+ ``timeperiod``).

    ``token`` is the instrument's Angel ``symboltoken``, resolved by the caller
    via ``database.token_db.get_token``.
    """
    tradingsymbol = get_br_symbol(data["symbol"], data["exchange"])
    exchange = data["exchange"]
    qty = _fmt(data["quantity"])
    disclosed_qty = _fmt(data.get("disclosed_quantity") or 0)
    producttype = map_gtt_product_type(data["product"])
    transactiontype = data["action"].upper()

    bodies = []
    for leg_label, trigger, price in _legs(data):
        bodies.append(
            (
                leg_label,
                {
                    "tradingsymbol": tradingsymbol,
                    "symboltoken": str(token),
                    "exchange": exchange,
                    "transactiontype": transactiontype,
                    "producttype": producttype,
                    "price": _fmt(price),
                    "qty": qty,
                    "triggerprice": _fmt(trigger),
                    "disclosedqty": disclosed_qty,
                    "timeperiod": DEFAULT_TIME_PERIOD_DAYS,
                },
            )
        )
    return bodies


def transform_modify_gtt(data, token, rule_ids):
    """Build Angel ``gtt/v1/modifyRule`` bodies, one per existing rule id.

    Angel's modify body is a strict subset of create — ``id, symboltoken,
    exchange, price, qty, triggerprice, disclosedqty``. Notably it carries
    neither ``tradingsymbol`` nor ``transactiontype`` nor ``producttype``,
    so those cannot be changed once a rule exists.

    ``rule_ids`` must be positionally aligned with the legs implied by
    ``data['trigger_type']`` (1 id for SINGLE, 2 ids ``[sl, tg]`` for OCO); the
    caller obtains them by decoding the composite trigger id.
    """
    exchange = data["exchange"]
    qty = _fmt(data["quantity"])
    disclosed_qty = _fmt(data.get("disclosed_quantity") or 0)

    bodies = []
    for (leg_label, trigger, price), rule_id in zip(_legs(data), rule_ids, strict=True):
        bodies.append(
            (
                leg_label,
                {
                    "id": str(rule_id),
                    "symboltoken": str(token),
                    "exchange": exchange,
                    "price": _fmt(price),
                    "qty": qty,
                    "triggerprice": _fmt(trigger),
                    "disclosedqty": disclosed_qty,
                    "timeperiod": DEFAULT_TIME_PERIOD_DAYS,
                },
            )
        )
    return bodies


def map_gtt_book(rules):
    """Normalise Angel's ``gtt/v1/ruleList`` rows into the OpenAlgo GTT shape.

    Each Angel row is one single-trigger rule, so every entry emitted here has
    exactly one trigger price and one leg. An OpenAlgo OCO placed through
    :func:`broker.angel.api.gtt_api.place_gtt_order` shows up as *two*
    independent rows — Angel stores no link between the pair, and inventing one
    from (symbol, side, qty, timestamp) would risk merging genuinely unrelated
    rules, so the pairing is deliberately not reconstructed here.

    ``last_price`` is 0: Angel's rule rows carry no LTP.
    """
    if not isinstance(rules, list):
        return []

    normalised = []
    for rule in rules:
        if not isinstance(rule, dict):
            continue

        status_raw = (rule.get("status") or "").upper()
        # Active-only filter: drop CANCELLED/EXPIRED/TRIGGERED/REJECTED at the
        # broker mapper so the orderbook UI shows only triggers that can fire.
        if status_raw not in ACTIVE_GTT_STATUSES:
            continue

        exchange = rule.get("exchange", "") or ""
        br_symbol = rule.get("tradingsymbol", "") or ""
        oa_symbol = (
            get_oa_symbol(brsymbol=br_symbol, exchange=exchange) if br_symbol and exchange else ""
        )

        leg = {
            "action": (rule.get("transactiontype", "") or "").upper(),
            "quantity": int(float(rule.get("qty", 0) or 0)),
            "price": float(rule.get("price", 0) or 0),
            # Angel GTT rules always fire a LIMIT child order.
            "pricetype": GTT_CHILD_PRICETYPE,
            "product": reverse_map_gtt_product_type(rule.get("producttype", "")),
        }

        normalised.append(
            {
                # Angel's published ruleList sample omits the id; the live API
                # returns it as "id". Fall back to the other spellings seen in
                # the SmartAPI SDK rather than emitting a book row with no id.
                "trigger_id": str(rule.get("id") or rule.get("gttid") or rule.get("ruleid") or ""),
                "trigger_type": "single",
                "status": _STATUS_MAP.get(status_raw, status_raw.lower()),
                "symbol": oa_symbol or br_symbol,
                "exchange": exchange,
                "trigger_prices": [float(rule.get("triggerprice", 0) or 0)],
                "last_price": 0,  # Angel does not return LTP on GTT rules
                "legs": [leg],
                "created_at": rule.get("createddate", "") or "",
                "updated_at": rule.get("updateddate", "") or "",
                "expires_at": rule.get("expirydate", "") or "",
            }
        )

    return normalised
