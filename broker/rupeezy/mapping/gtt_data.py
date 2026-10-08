# OpenAlgo <-> Vortex GTT transforms
# (https://vortex.rupeezy.in/docs/latest/gtt-order/).
#
# OpenAlgo OCO names its legs by price: `triggerprice_sl` / `stoploss` is the
# LOWER trigger and `triggerprice_tg` / `target` the HIGHER one (the schema
# enforces sl < tg). Vortex names them by role, and which role is lower
# depends on the side: "If transaction_type = BUY, stoploss.trigger_price
# should be > ltp and profit.trigger_price should be < ltp, and vice versa."
#   SELL GTT (exiting a long):  stoploss = lower,  profit = higher
#   BUY  GTT (exiting a short): stoploss = higher, profit = lower

from broker.rupeezy.mapping.exchange import (
    from_vortex_quantity,
    oa_exchange_for,
    split_ticker,
    to_vortex_quantity,
)
from broker.rupeezy.mapping.transform_data import (
    map_product_type,
    resolve_instrument,
    reverse_map_product_type,
)
from database.token_db import get_oa_symbol


def _f(value):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _variety(pricetype):
    """Vortex GTT varieties are RL and RL-MKT only."""
    return "RL-MKT" if str(pricetype or "").upper() == "MARKET" else "RL"


def _leg(quantity, price, trigger, variety):
    return {
        "quantity": quantity,
        "price": 0.0 if variety == "RL-MKT" else _f(price),
        "trigger_price": _f(trigger),
        "variety": variety,
    }


def _single_trigger(data):
    """SINGLE trigger: the schema's legacy `trigger_price` alias, else whichever
    of triggerprice_sl / triggerprice_tg is set (the UI modify route skips the
    schema)."""
    if _f(data.get("trigger_price")) > 0:
        return _f(data["trigger_price"])
    sl = _f(data.get("triggerprice_sl"))
    return sl if sl > 0 else _f(data.get("triggerprice_tg"))


def transform_place_gtt(data):
    """OpenAlgo place-GTT dict -> Vortex POST /trading/orders/gtt body.

    Raises ValueError for an MCX quantity that is not a whole number of lots.
    """
    ticker, brexchange, lotsize = resolve_instrument(data["symbol"], data["exchange"])
    action = str(data["action"]).upper()
    quantity = to_vortex_quantity(data["quantity"], brexchange, lotsize)
    variety = _variety(data.get("pricetype"))
    body = {
        "ticker": ticker,
        "transaction_type": action,
        "product": map_product_type(data.get("product", "CNC")),
    }

    if str(data.get("trigger_type") or "").upper() == "OCO":
        lower = _leg(quantity, data.get("stoploss"), data.get("triggerprice_sl"), variety)
        higher = _leg(quantity, data.get("target"), data.get("triggerprice_tg"), variety)
        stoploss, profit = (lower, higher) if action == "SELL" else (higher, lower)
        # TODO(rupeezy): the OCO body in the docs omits `product`; it is sent
        # anyway (the GTT book reports one). Confirm Vortex honours it.
        body.update({"gtt_trigger_type": "oco", "stoploss": stoploss, "profit": profit})
    else:
        body.update(
            {
                "gtt_trigger_type": "single",
                **_leg(quantity, data.get("price"), _single_trigger(data), variety),
            }
        )
    return body


def transform_modify_gtt(data, existing):
    """OpenAlgo modify-GTT dict + the GTT as it stands in the Vortex book ->
    Vortex PUT body (a list of legs, each carrying its leg `id`).

    Legs are matched by price order: the existing lower-trigger leg takes the
    new lower trigger (`triggerprice_sl` / `stoploss`), the higher one the new
    higher trigger. An existing trailing stop is kept (its type cannot change).
    """
    _, brexchange, lotsize = resolve_instrument(data["symbol"], data["exchange"])
    quantity = to_vortex_quantity(data["quantity"], brexchange, lotsize)
    variety = _variety(data.get("pricetype"))
    legs = sorted(existing.get("orders") or [], key=lambda o: _f(o.get("trigger_price")))

    if len(legs) >= 2:
        targets = [
            (data.get("stoploss"), data.get("triggerprice_sl")),
            (data.get("target"), data.get("triggerprice_tg")),
        ]
    else:
        targets = [(data.get("price"), _single_trigger(data))]

    body = []
    for leg, (price, trigger) in zip(legs, targets, strict=False):
        entry = {"id": leg.get("id"), **_leg(quantity, price, trigger, variety)}
        trail = leg.get("trail")
        if trail:
            entry["trail"] = {
                "id": trail.get("id"),
                "trail_jump_point": trail.get("trail_jump_point"),
                "trail_jump_type": trail.get("trail_jump_type"),
            }
        body.append(entry)
    return body


def _gtt_status(orders):
    statuses = [str(o.get("status") or "").lower() for o in orders]
    if "active" in statuses:
        return "active"
    return statuses[0] if statuses else ""


def map_gtt_book(raw, include_history=False):
    """Vortex GET /trading/orders/gtt -> OpenAlgo GTT book rows
    (same shape as broker/zerodha/mapping/gtt_data.map_gtt_book)."""
    if not isinstance(raw, dict):
        return []
    out = []
    for gtt in raw.get("data") or []:
        orders = sorted(gtt.get("orders") or [], key=lambda o: _f(o.get("trigger_price")))
        status = _gtt_status(orders)
        if not include_history and status != "active":
            continue

        vortex_exchange = gtt.get("exchange", "")
        oa_exchange = oa_exchange_for(vortex_exchange)
        brsymbol = split_ticker(gtt.get("ticker")) or gtt.get("symbol", "")
        symbol = get_oa_symbol(brsymbol=brsymbol, exchange=oa_exchange) or brsymbol
        product = reverse_map_product_type(oa_exchange, gtt.get("product")) or gtt.get(
            "product", ""
        )

        legs = [
            {
                "action": str(o.get("transaction_type") or gtt.get("transaction_type", "")).upper(),
                "quantity": from_vortex_quantity(
                    o.get("quantity"), vortex_exchange, gtt.get("lot_size")
                ),
                "price": _f(o.get("price")),
                "pricetype": "MARKET" if o.get("variety") == "RL-MKT" else "LIMIT",
                "product": product,
            }
            for o in orders
        ]
        first = orders[0] if orders else {}
        out.append(
            {
                "trigger_id": str(gtt.get("id", "")),
                "trigger_type": "two-leg"
                if str(gtt.get("trigger_type")).lower() == "oco"
                else "single",
                "status": status,
                "symbol": symbol,
                "exchange": oa_exchange,
                "trigger_prices": [_f(o.get("trigger_price")) for o in orders],
                "last_price": 0,
                "legs": legs,
                "created_at": first.get("created_at", ""),
                "updated_at": first.get("updated_at", ""),
                "expires_at": first.get("expires_at", ""),
            }
        )
    return out
