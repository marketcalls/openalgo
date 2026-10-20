# Upstox GTT payload transforms (OpenAlgo GTT <-> Upstox v3 GTT).
# Upstox GTT reference: https://upstox.com/developer/api-documentation/gtt-orders
# Local doc set: broker-api-docs/upstox-api-docs/14a-gtt-place.md,
# 14b-gtt-modify.md, 14c-gtt-cancel.md, 14d-gtt-get-details.md

from datetime import UTC, datetime

from broker.upstox.mapping.transform_data import map_product_type, reverse_map_product_type
from broker.upstox.streaming.upstox_mapping import UpstoxExchangeMapper
from database.token_db import get_oa_symbol, get_token
from database.token_db_enhanced import get_symbol_info
from utils.logging import get_logger
from utils.mpp_slab import get_instrument_type_from_symbol, get_mpp_percentage

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# OpenAlgo GTT  ->  Upstox v3 GTT rule mapping
# ---------------------------------------------------------------------------
# Upstox's GTT body is flat (type / quantity / product / instrument_token /
# transaction_type) plus a ``rules[]`` array. There is NO per-rule limit price
# field: the child order is placed at that rule's ``trigger_price``, optionally
# widened by ``market_protection`` (a percentage band, 0-25). Two consequences:
#
#   * OpenAlgo's ``price`` (SINGLE) and ``stoploss`` / ``target`` (OCO) limit
#     prices cannot be transmitted - the trigger price doubles as the limit.
#     We log whenever a caller-supplied limit is dropped.
#   * MARKET child orders are rejected outright (UDAPI1158 "Market orders
#     blocked; use limit orders with market protection"). Rather than
#     zerodha-style MPP - which would compute a protected limit that has
#     nowhere to go in this payload - a MARKET request is expressed with
#     Upstox's own ``market_protection``, sized from the very same slab table
#     zerodha's MPP helper uses (utils.mpp_slab.get_mpp_percentage).
#
# SINGLE -> type="SINGLE", exactly one ENTRY rule (UDAPI1136).
#     transaction_type = OpenAlgo ``action``
#     trigger_price    = triggerprice_sl or triggerprice_tg (whichever is set;
#                        legacy ``trigger_price`` alias wins if present)
#     trigger_type     = BELOW when trigger < LTP, ABOVE when trigger > LTP,
#                        IMMEDIATE when they are equal. Upstox validates the
#                        direction against the live LTP, so the direction is
#                        derived from the LTP rather than from which OpenAlgo
#                        field was populated (the field is only the fallback
#                        when the LTP could not be fetched).
#
# OCO -> type="MULTIPLE" with THREE rules: ENTRY + TARGET + STOPLOSS.
#     Upstox has no standalone two-leg-exit product. ENTRY is mandatory for
#     every GTT (UDAPI1141) and MULTIPLE needs 2-3 rules (UDAPI1137), so the
#     TARGET/STOPLOSS pair can only exist hanging off an ENTRY. Non-ENTRY
#     strategies additionally accept only IMMEDIATE (UDAPI1143) - their
#     trigger_price is the exit price, not a separate arming condition.
#
#     OpenAlgo's OCO ``action`` is the side of BOTH exit legs, so the Upstox
#     top-level transaction_type (which is the ENTRY side) is its opposite:
#         action=SELL (exiting a long)  -> ENTRY BUY
#         action=BUY  (covering a short) -> ENTRY SELL
#     and the exit legs then flip with the entry side, because "target" means
#     the profitable direction:
#         ENTRY BUY  (long)  -> TARGET = triggerprice_tg (above),
#                               STOPLOSS = triggerprice_sl (below)
#         ENTRY SELL (short) -> TARGET = triggerprice_sl (below),
#                               STOPLOSS = triggerprice_tg (above)
#     The ENTRY rule is sent as IMMEDIATE at the LTP, so placing an OpenAlgo
#     OCO on Upstox OPENS the entry position at market before arming the pair.
#
#     Be precise about what is forced here and what is not:
#       * Mandatory ENTRY rule -- broker constraint (UDAPI1141). There is no
#         rule combination that omits it, so Upstox genuinely has no
#         exit-only two-leg product the way zerodha/dhan do.
#       * IMMEDIATE on that ENTRY -- OUR choice, NOT a broker constraint. The
#         ENTRY rule accepts BELOW / ABOVE / IMMEDIATE; only NON-ENTRY rules
#         are restricted to IMMEDIATE (UDAPI1143). Upstox Pro's own GTT ticket
#         places a conditional entry ("If price is below X") with optional
#         stop-loss and target attached, which is the same MULTIPLE shape.
#
#     IMMEDIATE is used only because an OpenAlgo OCO payload carries no entry
#     price to put in that rule -- it describes exits on a position assumed to
#     already exist. Making the ENTRY conditional would not close that gap, it
#     would just move it: we would have to invent a trigger price instead of a
#     trigger type. Exposing Upstox's bracket GTT honestly needs a distinct
#     OpenAlgo request shape carrying its own entry trigger.
#
#     Meanwhile the everyday case is already covered without any of this: a
#     stop or a target on an existing holding is a SINGLE sell GTT.
# ---------------------------------------------------------------------------


# Upstox rule statuses (14d-gtt-get-details.md): SCHEDULED, TRIGGERED, EXPIRED,
# OPEN, COMPLETED, CANCELLED, PENDING, FAILED, INACTIVE. A GTT is still live
# while any of its rules can still fire. INACTIVE is included because the
# TARGET/STOPLOSS rules of a MULTIPLE sit INACTIVE until the ENTRY triggers.
_LIVE_RULE_STATUSES = {"SCHEDULED", "PENDING", "OPEN", "INACTIVE"}

# Upstox stamps created_at / expires_at as a bare epoch integer. The docs type
# them only as "string" and never name the unit, and observed values are epoch
# MICROSECONDS -- 1000x what a millisecond reader expects, which renders as the
# year 58623 instead of 2026. Every other broker hands the GTT book an ISO 8601
# string (Kite's "2020-11-16T14:19:51Z"), and the frontend's formatDateTime
# does `new Date(value)`, so the unit is normalised here rather than in the UI:
# the mapper owns broker-shape -> OpenAlgo-shape, and /gttorderbook plus its CSV
# export would otherwise still carry the raw integer.
#
# Rather than hard-coding microseconds, the unit is inferred from magnitude, so
# a future Upstox change to seconds or milliseconds keeps working. Bounds are
# generous (roughly year 2001 to 2286 in each unit) and non-overlapping.
_EPOCH_UNIT_DIVISORS = (
    (1e18, 1e9),  # nanoseconds
    (1e15, 1e6),  # microseconds  <- what Upstox currently sends
    (1e12, 1e3),  # milliseconds
    (1e9, 1.0),  # seconds
)


def _iso_timestamp(value):
    """Normalise an Upstox GTT timestamp to an ISO 8601 UTC string.

    Accepts an epoch integer (or its string form) in seconds, milliseconds,
    microseconds or nanoseconds and returns e.g. ``"2026-08-27T12:33:12Z"``.
    A value that is already an ISO string is passed through untouched, and
    anything unparseable degrades to ``""`` so the UI shows "-" rather than a
    nonsense date.
    """
    if value in (None, ""):
        return ""

    if isinstance(value, str):
        stripped = value.strip()
        # Already a formatted timestamp (any non-digit means it is not an epoch).
        if not stripped.lstrip("-").isdigit():
            return stripped
        value = stripped

    try:
        epoch = float(value)
    except (TypeError, ValueError):
        return str(value)

    if epoch <= 0:
        return ""

    for threshold, divisor in _EPOCH_UNIT_DIVISORS:
        if epoch >= threshold:
            seconds = epoch / divisor
            break
    else:
        # Below the seconds floor: too small to be a plausible timestamp.
        logger.warning(f"Upstox GTT: implausible epoch timestamp {value!r}; dropping")
        return ""

    try:
        return (
            datetime.fromtimestamp(seconds, tz=UTC)
            .replace(microsecond=0)
            .strftime("%Y-%m-%dT%H:%M:%SZ")
        )
    except (OverflowError, OSError, ValueError):
        logger.warning(f"Upstox GTT: could not convert epoch timestamp {value!r}")
        return ""


def _resolve_single_trigger(data):
    """For SINGLE GTT, resolve the active trigger from new fields if the legacy
    ``trigger_price`` alias was not pre-populated by the schema (e.g., the UI
    modify route bypasses schema)."""
    if data.get("trigger_price") not in (None, "", 0, 0.0):
        return float(data["trigger_price"])
    sl = data.get("triggerprice_sl") or 0
    tg = data.get("triggerprice_tg") or 0
    return float(sl) if float(sl) > 0 else float(tg)


def _single_trigger_direction(data, trigger_price):
    """Pick Upstox's ``trigger_type`` for the SINGLE ENTRY rule.

    Preference order: compare against the live LTP (what Upstox itself
    validates), else fall back to the OpenAlgo field semantics
    (``triggerprice_sl`` = below LTP, ``triggerprice_tg`` = above LTP).
    """
    last_price = float(data.get("last_price") or 0)
    if last_price > 0:
        if trigger_price < last_price:
            return "BELOW"
        if trigger_price > last_price:
            return "ABOVE"
        return "IMMEDIATE"

    if float(data.get("triggerprice_tg") or 0) > 0:
        return "ABOVE"
    if float(data.get("triggerprice_sl") or 0) > 0:
        return "BELOW"
    logger.warning(
        "Upstox GTT: no last_price and no triggerprice_sl/tg to infer direction; "
        "defaulting trigger_type=BELOW"
    )
    return "BELOW"


def _market_protection(data, base_price):
    """Upstox ``market_protection`` percentage for a MARKET request, else None.

    Upstox rejects MARKET GTT child orders (UDAPI1158) and instead offers a
    percentage protection band around the trigger. The percentage is taken
    from OpenAlgo's shared MPP slab table so a MARKET GTT gets the same
    protection width here as the LIMIT price zerodha would have computed.
    Range is clamped to Upstox's documented 1..25.
    """
    if (data.get("pricetype") or "LIMIT").upper() != "MARKET":
        return None

    symbol = data.get("symbol") or ""
    exchange = data.get("exchange") or ""

    sym_info = get_symbol_info(symbol, exchange) if symbol and exchange else None
    instrument_type = (
        getattr(sym_info, "instrumenttype", None) if sym_info else None
    ) or get_instrument_type_from_symbol(symbol)

    pct = get_mpp_percentage(float(base_price or 0), instrument_type) or 1.0
    protection = max(1, min(25, int(round(pct))))
    logger.info(
        f"Upstox GTT MARKET -> market_protection={protection}% "
        f"(symbol={symbol}, instrument_type={instrument_type}, base_price={base_price})"
    )
    return protection


def _rule(strategy, trigger_type, trigger_price, market_protection=None):
    """Build one Upstox ``rules[]`` entry."""
    rule = {
        "strategy": strategy,
        "trigger_type": trigger_type,
        "trigger_price": float(trigger_price),
    }
    if market_protection is not None:
        rule["market_protection"] = int(market_protection)
    return rule


def _build_rules(data):
    """Build the Upstox ``rules[]`` array plus the ``type`` / ``transaction_type``
    pair implied by the OpenAlgo trigger type.

    Returns ``(gtt_type, transaction_type, rules)``. Shared by place and modify
    (modify ignores ``transaction_type`` - Upstox's PUT body has no such field).
    """
    action = (data.get("action") or "").upper()
    trigger_type_oa = (data.get("trigger_type") or "").upper()
    last_price = float(data.get("last_price") or 0)

    if trigger_type_oa == "OCO":
        sl_trigger = float(data["triggerprice_sl"])
        tg_trigger = float(data["triggerprice_tg"])

        # OpenAlgo's action is the EXIT side; Upstox's transaction_type is the
        # ENTRY side, hence the inversion.
        entry_side = "SELL" if action == "BUY" else "BUY"
        if entry_side == "BUY":  # long: profit above, stop below
            target_trigger, stop_trigger = tg_trigger, sl_trigger
        else:  # short: profit below, stop above
            target_trigger, stop_trigger = sl_trigger, tg_trigger

        if data.get("stoploss") or data.get("target"):
            logger.info(
                f"Upstox GTT: limit prices stoploss={data.get('stoploss')}, "
                f"target={data.get('target')} dropped - Upstox executes each rule "
                f"at its own trigger_price (no per-rule limit field)."
            )

        rules = [
            # ENTRY is mandatory (UDAPI1141); IMMEDIATE arms the bracket now.
            _rule("ENTRY", "IMMEDIATE", last_price, _market_protection(data, last_price)),
            # Non-ENTRY strategies accept IMMEDIATE only (UDAPI1143).
            _rule("TARGET", "IMMEDIATE", target_trigger, _market_protection(data, target_trigger)),
            _rule("STOPLOSS", "IMMEDIATE", stop_trigger, _market_protection(data, stop_trigger)),
        ]
        return "MULTIPLE", entry_side, rules

    # SINGLE
    trigger_price = _resolve_single_trigger(data)
    direction = _single_trigger_direction(data, trigger_price)

    if float(data.get("price") or 0) > 0 and float(data.get("price") or 0) != trigger_price:
        logger.info(
            f"Upstox GTT: limit price={data.get('price')} dropped - the ENTRY rule "
            f"executes at trigger_price={trigger_price} (no limit field in Upstox GTT)."
        )

    rules = [
        _rule("ENTRY", direction, trigger_price, _market_protection(data, trigger_price)),
    ]
    return "SINGLE", action, rules


def transform_place_gtt(data):
    """Transform an OpenAlgo flat place-GTT payload into Upstox's POST /v3/order/gtt/place body.

    Expected ``data`` keys (post-schema): symbol, exchange, trigger_type
    ("SINGLE" | "OCO"), action, product, quantity, pricetype, price,
    last_price, and either ``trigger_price``/``triggerprice_sl``/
    ``triggerprice_tg`` (SINGLE) or ``triggerprice_sl`` + ``triggerprice_tg``
    (OCO). ``data['instrument_token']`` may be pre-resolved by the caller;
    otherwise it is looked up here.

    See the mapping block at the top of this module for the SINGLE/OCO rule
    semantics.
    """
    instrument_token = data.get("instrument_token") or get_token(data["symbol"], data["exchange"])
    gtt_type, transaction_type, rules = _build_rules(data)

    return {
        "type": gtt_type,
        "quantity": int(float(data["quantity"])),
        "product": map_product_type(data["product"]),
        "instrument_token": str(instrument_token),
        "transaction_type": transaction_type,
        "rules": rules,
    }


def transform_modify_gtt(data):
    """Transform an OpenAlgo modify-GTT payload into Upstox's PUT /v3/order/gtt/modify body.

    Upstox's modify body is narrower than place: ``type``, ``quantity``,
    ``gtt_order_id`` and ``rules`` only - instrument_token, product and
    transaction_type are immutable and must not be sent. ``market_protection``
    is likewise not part of the documented modify contract (14b), so it is
    stripped from the rules here even for MARKET requests; the value set at
    place time stays in force.
    """
    gtt_type, _transaction_type, rules = _build_rules(data)
    for rule in rules:
        rule.pop("market_protection", None)

    return {
        "type": gtt_type,
        "quantity": int(float(data["quantity"])),
        "gtt_order_id": str(data["trigger_id"]),
        "rules": rules,
    }


def map_gtt_book(gtt_data):
    """Normalise Upstox's GET /v3/order/gtt response into an OpenAlgo-shaped list.

    Upstox returns ``{"status": "success", "data": [{...}, ...]}`` where each
    entry is one GTT carrying ``type``, ``exchange`` (Upstox segment code such
    as ``NSE_EQ``), ``quantity``, ``product``, ``trading_symbol``,
    ``instrument_token``, ``gtt_order_id``, ``created_at``, ``expires_at`` and
    a multi-entry ``rules[]``. Each GTT is merged into ONE OpenAlgo item.

    Active-only filter: a GTT is kept when at least one of its rules is still
    able to fire (SCHEDULED / PENDING / OPEN / INACTIVE); fully
    TRIGGERED / COMPLETED / EXPIRED / CANCELLED / FAILED GTTs are dropped, the
    same way zerodha's mapper keeps only ``active``. The surfaced status is
    normalised to ``active`` because the frontend gates its Modify/Cancel
    actions on that exact string.

    For a MULTIPLE GTT the broker-mandated ENTRY rule is excluded from
    ``legs`` / ``trigger_prices`` so the item reads as a plain OCO pair
    ordered low -> high, which is what the OpenAlgo modify round-trip expects
    (``trigger_prices[0]`` -> triggerprice_sl, ``[1]`` -> triggerprice_tg).
    ``last_price`` is not returned by this endpoint, so it is left at 0.
    """
    if isinstance(gtt_data, dict):
        entries = gtt_data.get("data") or []
    elif isinstance(gtt_data, list):
        entries = gtt_data
    else:
        return []

    normalised = []
    for gtt in entries:
        if not isinstance(gtt, dict):
            continue

        rules = [r for r in (gtt.get("rules") or []) if isinstance(r, dict)]
        if not any((r.get("status") or "").upper() in _LIVE_RULE_STATUSES for r in rules):
            continue

        gtt_type = (gtt.get("type") or "SINGLE").upper()
        br_exchange = gtt.get("exchange") or ""
        exchange = UpstoxExchangeMapper.get_openalgo_exchange(br_exchange) or br_exchange
        br_symbol = gtt.get("trading_symbol") or ""
        oa_symbol = (
            get_oa_symbol(brsymbol=br_symbol, exchange=exchange) if br_symbol and exchange else ""
        )

        quantity = gtt.get("quantity", 0)
        product = reverse_map_product_type(exchange, gtt.get("product", "")) or ""

        # MULTIPLE carries a mandatory ENTRY rule that OpenAlgo's OCO shape has
        # no slot for - hide it so the pair reads as [stoploss, target].
        shown = (
            [r for r in rules if (r.get("strategy") or "").upper() != "ENTRY"]
            if gtt_type == "MULTIPLE"
            else rules
        )
        if not shown:
            shown = rules
        shown = sorted(shown, key=lambda r: float(r.get("trigger_price") or 0))

        legs = []
        for rule in shown:
            legs.append(
                {
                    "action": (rule.get("transaction_type") or "").upper(),
                    "quantity": quantity,
                    # Upstox GTT has no separate limit price - the child order
                    # is placed at the rule's trigger price.
                    "price": float(rule.get("trigger_price") or 0),
                    "pricetype": "LIMIT",
                    "product": product,
                }
            )

        normalised.append(
            {
                "trigger_id": str(gtt.get("gtt_order_id", "") or ""),
                # "two-leg" / "single" are the strings the OpenAlgo GTT UI keys
                # off (inherited from Kite), so Upstox's MULTIPLE/SINGLE is
                # translated rather than passed through raw.
                "trigger_type": "two-leg" if gtt_type == "MULTIPLE" else "single",
                "status": "active",
                "symbol": oa_symbol or br_symbol,
                "exchange": exchange,
                "trigger_prices": [float(r.get("trigger_price") or 0) for r in shown],
                "last_price": 0,  # not returned by GET /v3/order/gtt
                "legs": legs,
                "created_at": _iso_timestamp(gtt.get("created_at")),
                # Upstox does not expose a GTT update timestamp.
                "updated_at": "",
                "expires_at": _iso_timestamp(gtt.get("expires_at")),
            }
        )

    return normalised
