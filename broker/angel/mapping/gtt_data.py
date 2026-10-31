# Angel One (SmartAPI) GTT payload transforms (OpenAlgo <-> Angel).
# SmartAPI GTT reference: https://smartapi.angelone.in/docs  (section "GTT")
#
# One OpenAlgo GTT is one Angel rule. A SINGLE rule carries one trigger
# (``triggerprice``/``price``). An OCO rule (``gttType: "OCO"``) carries the
# target leg in ``triggerprice``/``price`` and the stop-loss leg in
# ``stoplosstriggerprice``/``stoplossprice``; Angel cancels the other leg when
# one fires.

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
# accepted on the cash segment. The generic order mapper yields DELIVERY /
# CARRYFORWARD / INTRADAY, so on cash CARRYFORWARD (NRML) is folded onto
# MARGIN — Angel's cash-segment leveraged product — and INTRADAY onto MARGIN as
# well. Derivatives keep CARRYFORWARD, the product Angel uses for an NRML F&O
# position (an OCO rule on an NFO option with CARRYFORWARD was accepted and
# stored as such). MIS is rejected upstream by the GTT schema.
_GTT_PRODUCT_OVERRIDE = {
    "CARRYFORWARD": "MARGIN",
    "INTRADAY": "MARGIN",
}

_CASH_EXCHANGES = ("NSE", "BSE")

_GTT_REVERSE_PRODUCT_OVERRIDE = {
    "MARGIN": "NRML",
}


def map_gtt_product_type(product, exchange):
    """Map an OpenAlgo product (CNC/NRML) to an Angel *GTT* producttype.

    Reuses the broker's existing :func:`map_product_type` and then applies the
    cash-only narrowing documented above (AB9015 "Invalid Product Type" is what
    Angel returns if CARRYFORWARD reaches the GTT endpoint for a cash symbol).
    """
    angel_product = map_product_type(product)
    if exchange not in _CASH_EXCHANGES:
        return angel_product
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


def is_oco(data):
    return (data.get("trigger_type") or "").upper() == "OCO"


def _trigger_fields(data):
    """The price fields of one Angel rule body.

    SINGLE -> ``triggerprice``/``price``. OCO -> ``gttType: OCO`` with the
    target leg in ``triggerprice``/``price`` and the stop-loss leg in
    ``stoplosstriggerprice``/``stoplossprice``.
    """
    if is_oco(data):
        return {
            "gttType": "OCO",
            "price": _fmt(data["target"]),
            "triggerprice": _fmt(data["triggerprice_tg"]),
            "stoplossprice": _fmt(data["stoploss"]),
            "stoplosstriggerprice": _fmt(data["triggerprice_sl"]),
        }
    return {
        "price": _fmt(data.get("price") or 0),
        "triggerprice": _fmt(_resolve_single_trigger(data)),
    }


def transform_place_gtt(data, token):
    """Build the Angel ``gtt/v1/createRule`` body for an OpenAlgo place-GTT payload.

    ``token`` is the instrument's Angel ``symboltoken``, resolved by the caller
    via ``database.token_db.get_token``.
    """
    return {
        "tradingsymbol": get_br_symbol(data["symbol"], data["exchange"]),
        "symboltoken": str(token),
        "exchange": data["exchange"],
        "transactiontype": data["action"].upper(),
        "producttype": map_gtt_product_type(data["product"], data["exchange"]),
        **_trigger_fields(data),
        "qty": _fmt(data["quantity"]),
        "disclosedqty": _fmt(data.get("disclosed_quantity") or 0),
        "timeperiod": DEFAULT_TIME_PERIOD_DAYS,
    }


def transform_modify_gtt(data, token, rule_id):
    """Build the Angel ``gtt/v1/modifyRule`` body for an existing rule.

    Angel's modify body is a subset of create: it carries neither
    ``tradingsymbol`` nor ``transactiontype`` nor ``producttype``, so those
    cannot be changed once a rule exists, and neither can SINGLE vs OCO.
    """
    return {
        "id": str(rule_id),
        "symboltoken": str(token),
        "exchange": data["exchange"],
        **_trigger_fields(data),
        "qty": _fmt(data["quantity"]),
        "disclosedqty": _fmt(data.get("disclosed_quantity") or 0),
        "timeperiod": DEFAULT_TIME_PERIOD_DAYS,
    }


def map_gtt_book(rules):
    """Normalise Angel's ``gtt/v1/ruleList`` rows into the OpenAlgo GTT shape.

    A SINGLE rule becomes one ``single`` entry; an OCO rule becomes one
    ``two-leg`` entry whose ``trigger_prices`` and ``legs`` are sorted by
    trigger, ascending, as for every broker (a SELL OCO's stop-loss leg comes
    first, a BUY OCO's target leg). ``last_price`` is 0: Angel's rule rows carry
    no LTP.
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

        def leg(price, rule=rule):
            return {
                "action": (rule.get("transactiontype", "") or "").upper(),
                "quantity": int(float(rule.get("qty", 0) or 0)),
                "price": float(price or 0),
                # Angel GTT rules always fire a LIMIT child order.
                "pricetype": GTT_CHILD_PRICETYPE,
                "product": reverse_map_gtt_product_type(rule.get("producttype", "")),
            }

        pairs = [(float(rule.get("triggerprice", 0) or 0), leg(rule.get("price")))]
        trigger_type = "single"
        if (rule.get("gttType") or "").upper() == "OCO":
            trigger_type = "two-leg"
            pairs.append(
                (float(rule.get("stoplosstriggerprice", 0) or 0), leg(rule.get("stoplossprice")))
            )
            pairs.sort(key=lambda pair: pair[0])

        normalised.append(
            {
                # Angel's published ruleList sample omits the id; the live API
                # returns it as "id". Fall back to the other spellings seen in
                # the SmartAPI SDK rather than emitting a book row with no id.
                "trigger_id": str(rule.get("id") or rule.get("gttid") or rule.get("ruleid") or ""),
                "trigger_type": trigger_type,
                "status": _STATUS_MAP.get(status_raw, status_raw.lower()),
                "symbol": oa_symbol or br_symbol,
                "exchange": exchange,
                "trigger_prices": [trigger for trigger, _ in pairs],
                "last_price": 0,  # Angel does not return LTP on GTT rules
                "legs": [leg_ for _, leg_ in pairs],
                "created_at": rule.get("createddate", "") or "",
                "updated_at": rule.get("updateddate", "") or "",
                "expires_at": rule.get("expirydate", "") or "",
            }
        )

    return normalised
