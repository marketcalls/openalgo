# Fyers GTT payload transforms (OpenAlgo <-> Fyers API v3).
# Fyers GTT reference: fyers-api-docs/FYERS_API_v3.md -> "GTT Orders"
# (GTT Single / GTT OCO / GTT Modify Order / GTT Cancel Order / GTT Order Book)

from broker.fyers.mapping.order_data import get_exchange
from broker.fyers.mapping.transform_data import (
    map_action,
    map_product_type,
    reverse_map_product_type,
)
from database.token_db import get_br_symbol, get_oa_symbol
from utils.logging import get_logger

logger = get_logger(__name__)


# Fyers `orderBook[].ord_status` codes (see "GTT Order Book" response attributes).
# 1: Cancelled, 2: Traded/Filled, 3: reserved, 4: Transit, 5: Rejected, 6: Pending.
GTT_STATUS_MAP = {
    1: "cancelled",
    2: "triggered",
    3: "unknown",
    4: "transit",
    5: "rejected",
    6: "active",
}

# Only these can still fire, so only these belong in the OpenAlgo GTT book.
ACTIVE_GTT_STATUSES = (4, 6)

# Fyers `gtt_oco_ind`: 1 = plain GTT (leg1 only), 2 = OCO (leg1 + leg2).
# Mapped to the OpenAlgo book vocabulary rather than Fyers' own, because the
# GTT tab keys OCO off the literal "two-leg" (Kite's spelling, which zerodha
# passes through and dhan normalises to) — see frontend GttTab.tsx.
GTT_OCO_IND_MAP = {1: "single", 2: "two-leg"}


def _resolve_single_trigger(data):
    """For SINGLE GTT, resolve the active trigger from the new fields if the
    legacy ``trigger_price`` alias was not pre-populated by the schema (e.g. the
    UI modify route bypasses the marshmallow schema).

    Identical fallback order to zerodha's ``_resolve_single_trigger`` so both
    brokers behave the same for the same request body.
    """
    if data.get("trigger_price") not in (None, "", 0, 0.0):
        return float(data["trigger_price"])
    sl = data.get("triggerprice_sl") or 0
    tg = data.get("triggerprice_tg") or 0
    return float(sl) if float(sl) > 0 else float(tg)


def _leg(price, trigger_price, quantity):
    """Build one Fyers ``orderInfo`` leg.

    A Fyers GTT leg carries only ``price`` / ``triggerPrice`` / ``qty`` -- there
    is no per-leg order-type field, which is why the child order is always a
    LIMIT and MARKET has to be MPP-converted upstream (see gtt_api).
    """
    return {
        "price": float(price or 0),
        "triggerPrice": float(trigger_price or 0),
        "qty": int(float(quantity or 0)),
    }


def build_order_info(data):
    """Build the Fyers ``orderInfo`` object (leg1, and leg2 for OCO).

    Leg ordering is the single most error-prone part of this integration.
    Fyers documents, for both GTT Single and GTT OCO:

        leg1.triggerPrice -- "for OCO order this leg trigger price should be
                              always above LTP"
        leg2.triggerPrice -- "for OCO order this leg trigger price should be
                              always below LTP"

    OpenAlgo's contract defines ``triggerprice_tg`` as the trigger ABOVE the LTP
    and ``triggerprice_sl`` as the trigger BELOW it, with the invariant
    ``triggerprice_sl < triggerprice_tg``. Therefore:

        leg1 <- target   leg (triggerprice_tg / target)     -- above LTP
        leg2 <- stoploss leg (triggerprice_sl / stoploss)   -- below LTP

    If a caller violates the invariant (sl >= tg) we swap the legs and warn,
    because sending them in the documented-wrong order gets the whole GTT
    rejected by Fyers rather than just the offending leg.

    SINGLE simply uses leg1 with the resolved single trigger; the above/below
    rule is an OCO-only constraint, so a SINGLE trigger below the LTP is fine
    in leg1.
    """
    quantity = data["quantity"]
    trigger_type = (data.get("trigger_type") or "").upper()

    if trigger_type != "OCO":
        return {"leg1": _leg(data.get("price"), _resolve_single_trigger(data), quantity)}

    tg_trigger = float(data.get("triggerprice_tg") or 0)
    sl_trigger = float(data.get("triggerprice_sl") or 0)
    tg_price = data.get("target")
    sl_price = data.get("stoploss")

    if sl_trigger >= tg_trigger:
        logger.warning(
            f"Fyers GTT OCO: triggerprice_sl ({sl_trigger}) >= triggerprice_tg "
            f"({tg_trigger}) breaks the OpenAlgo invariant; swapping so leg1 "
            f"stays the higher (above-LTP) trigger as Fyers requires."
        )
        tg_trigger, sl_trigger = sl_trigger, tg_trigger
        tg_price, sl_price = sl_price, tg_price

    return {
        "leg1": _leg(tg_price, tg_trigger, quantity),  # above LTP
        "leg2": _leg(sl_price, sl_trigger, quantity),  # below LTP
    }


def transform_place_gtt(data, order_tag=None):
    """Transform an OpenAlgo flat place-GTT payload into a Fyers GTT body.

    Fyers ``POST /api/v3/gtt/orders/sync`` takes::

        {"side": 1|-1, "symbol": "NSE:SBIN-EQ", "productType": "CNC",
         "orderInfo": {"leg1": {...}, "leg2": {...}}, "orderTag": "..."}

    There is no separate OCO endpoint or type flag -- the presence of ``leg2``
    is what makes it an OCO. ``side`` applies to both legs, which lines up with
    OpenAlgo sending a single ``action`` for the whole OCO.

    Product mapping reuses the existing ``map_product_type`` (CNC -> CNC,
    NRML -> MARGIN). Fyers GTT accepts only CNC / MARGIN / MTF, and OpenAlgo
    rejects MIS for GTT upstream, so INTRADAY never reaches here in practice.
    """
    payload = {
        "side": map_action((data.get("action") or "").upper()),
        "symbol": get_br_symbol(data["symbol"], data["exchange"]),
        "productType": map_product_type(data["product"]),
        "orderInfo": build_order_info(data),
    }
    if order_tag:
        # Fyers prefixes "1:GTT" to whatever tag the user supplies.
        payload["orderTag"] = order_tag
    return payload


def transform_modify_gtt(data):
    """Transform an OpenAlgo modify-GTT payload into a Fyers GTT modify body.

    ``PATCH /api/v3/gtt/orders/sync`` accepts only ``id`` + ``orderInfo``:
    side / symbol / productType are NOT modifiable on an existing Fyers GTT,
    so those fields are deliberately dropped here even though OpenAlgo's modify
    request carries them. Fyers keeps the original values for anything omitted.
    """
    return {
        "id": str(data["trigger_id"]),
        "orderInfo": build_order_info(data),
    }


def transform_cancel_gtt(trigger_id):
    """Body for ``DELETE /api/v3/gtt/orders/sync`` -- just the GTT id."""
    return {"id": str(trigger_id)}


def _leg_from_book(action, product, price, quantity):
    return {
        "action": action,
        "quantity": int(float(quantity or 0)),
        "price": float(price or 0),
        # A Fyers GTT child order is always a limit order (a leg only has
        # price/triggerPrice/qty), so the normalised pricetype is always LIMIT.
        "pricetype": "LIMIT",
        "product": product,
    }


def map_gtt_book(gtt_data):
    """Normalise Fyers ``GET /api/v3/gtt/orders`` into the OpenAlgo GTT shape.

    Fyers returns ``{"s": "ok", "code": 200, "orderBook": [...]}`` where each
    entry is ONE GTT that already carries both legs inline
    (``price_limit``/``price_trigger``/``qty`` for leg1 and
    ``price2_limit``/``price2_trigger``/``qty2`` for leg2). So an OCO is a
    single row, not two rows to stitch together -- ``gtt_oco_ind`` (1 = GTT,
    2 = OCO) tells us whether leg2 is real.

    Only pending/transit triggers are returned; cancelled, triggered and
    rejected rows are dropped, matching zerodha's active-only filter.
    """
    if not isinstance(gtt_data, dict):
        return []

    order_book = gtt_data.get("orderBook") or []
    normalised = []

    for order in order_book:
        if not isinstance(order, dict):
            logger.warning(f"Fyers GTT book: expected a dict, got {type(order)}. Skipping.")
            continue

        ord_status = order.get("ord_status")
        if ord_status not in ACTIVE_GTT_STATUSES:
            continue

        exchange = get_exchange(order.get("exchange"), order.get("segment"))
        br_symbol = order.get("symbol", "")
        oa_symbol = get_oa_symbol(brsymbol=br_symbol, exchange=exchange) if br_symbol else ""

        action = "BUY" if order.get("tran_side") == 1 else "SELL"
        product = reverse_map_product_type(order.get("product_type")) or order.get(
            "product_type", ""
        )

        oco_ind = order.get("gtt_oco_ind")
        legs = [_leg_from_book(action, product, order.get("price_limit"), order.get("qty"))]
        trigger_prices = [float(order.get("price_trigger") or 0)]

        if oco_ind == 2:
            legs.append(
                _leg_from_book(action, product, order.get("price2_limit"), order.get("qty2"))
            )
            trigger_prices.append(float(order.get("price2_trigger") or 0))
            # OpenAlgo presents trigger prices low -> high; Fyers stores leg1
            # (above LTP) first, so sort rather than assume the API's ordering.
            trigger_prices.sort()

        normalised.append(
            {
                "trigger_id": str(order.get("id", "")),
                "trigger_type": GTT_OCO_IND_MAP.get(oco_ind, "SINGLE"),
                "status": GTT_STATUS_MAP.get(ord_status, "unknown"),
                "symbol": oa_symbol or br_symbol,
                "exchange": exchange,
                "trigger_prices": trigger_prices,
                "last_price": float(order.get("ltp") or 0),
                "legs": legs,
                "created_at": order.get("create_time", ""),
                # Fyers' GTT book exposes no modification timestamp and no
                # expiry field (GTTs live up to one year), so these stay blank
                # rather than being invented.
                "updated_at": "",
                "expires_at": "",
            }
        )

    return normalised
