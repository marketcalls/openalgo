# Zerodha GTT payload transforms (OpenAlgo ⇄ Kite).
# Kite Connect GTT API reference: https://kite.trade/docs/connect/v3/gtt/

from database.token_db import get_br_symbol, get_oa_symbol


def _build_order(data, price, tradingsymbol, exchange):
    """Build one Kite `orders[]` entry sharing action/qty/product/pricetype across legs."""
    return {
        "exchange": exchange,
        "tradingsymbol": tradingsymbol,
        "transaction_type": data["action"].upper(),
        "quantity": int(data["quantity"]),
        "order_type": data.get("pricetype", "LIMIT"),
        "product": data["product"],
        "price": float(price),
    }


def _resolve_single_trigger(data):
    """For SINGLE GTT, resolve the active trigger from new fields if the legacy
    ``trigger_price`` alias was not pre-populated by the schema (e.g., the UI
    modify route bypasses schema)."""
    if data.get("trigger_price") not in (None, "", 0, 0.0):
        return float(data["trigger_price"])
    sl = data.get("triggerprice_sl") or 0
    tg = data.get("triggerprice_tg") or 0
    return float(sl) if float(sl) > 0 else float(tg)


def transform_place_gtt(data):
    """Transform an OpenAlgo flat place-GTT payload into Kite's `{type, condition, orders}`.

    Expected ``data`` keys (post-schema):
        symbol, exchange, trigger_type ("SINGLE" | "OCO"), action, product,
        quantity, pricetype, price, last_price, and:
        - SINGLE → trigger_price (legacy alias resolved by the schema).
        - OCO    → triggerprice_sl + stoploss + triggerprice_tg + target.

    Mapping:
        SINGLE → trigger=trigger_price, limit=price.
        OCO    → stoploss leg (trigger=triggerprice_sl, limit=stoploss) +
                 target   leg (trigger=triggerprice_tg, limit=target).
                 trigger_values is sorted low→high as Kite requires.

    Caller is responsible for JSON-encoding ``condition`` and ``orders`` and
    URL-encoding the form.
    """
    tradingsymbol = get_br_symbol(data["symbol"], data["exchange"])
    exchange = data["exchange"]
    trigger_type_oa = (data.get("trigger_type") or "").upper()

    if trigger_type_oa == "OCO":
        kite_type = "two-leg"
        trigger_values = [float(data["triggerprice_sl"]), float(data["triggerprice_tg"])]
        orders = [
            _build_order(data, data["stoploss"], tradingsymbol, exchange),
            _build_order(data, data["target"], tradingsymbol, exchange),
        ]
    else:  # SINGLE
        kite_type = "single"
        trigger_values = [_resolve_single_trigger(data)]
        orders = [_build_order(data, data["price"], tradingsymbol, exchange)]

    condition = {
        "exchange": exchange,
        "tradingsymbol": tradingsymbol,
        "trigger_values": trigger_values,
        "last_price": float(data["last_price"]),
    }

    return {"type": kite_type, "condition": condition, "orders": orders}


def transform_modify_gtt(data):
    """Transform an OpenAlgo modify-GTT payload (flat shape) into Kite's body.

    Kite's PUT /gtt/triggers/:id takes the same ``{type, condition, orders}``
    shape as POST, so the place transform is reused.
    """
    return transform_place_gtt(data)


def map_gtt_book(gtt_data):
    """Normalise Kite's GET /gtt/triggers response into an OpenAlgo-shaped list.

    Kite returns ``{"status": "success", "data": [{...}, ...]}``. Each GTT has
    ``id``, ``user_id``, ``type``, ``status``, ``condition``, ``orders``, ``created_at``, ``updated_at``,
    ``expires_at``, ``meta``. We flatten to a broker-neutral shape and translate the
    Kite tradingsymbol back to OpenAlgo's symbol.
    """
    if not isinstance(gtt_data, dict):
        return []

    data = gtt_data.get("data") or []
    normalised = []

    # Active-only filter: drop triggered/disabled/expired/cancelled/rejected/
    # deleted at the broker mapper so the orderbook UI shows only triggers
    # that can still fire. Kite's GTT statuses: active, triggered, disabled,
    # expired, cancelled, rejected, deleted.
    for gtt in data:
        if (gtt.get("status") or "").lower() != "active":
            continue
        condition = gtt.get("condition") or {}
        orders = gtt.get("orders") or []
        exchange = condition.get("exchange", "")
        br_symbol = condition.get("tradingsymbol", "")
        oa_symbol = get_oa_symbol(brsymbol=br_symbol, exchange=exchange) if br_symbol else ""

        legs = []
        for order in orders:
            legs.append(
                {
                    "action": order.get("transaction_type", ""),
                    "quantity": order.get("quantity", 0),
                    "price": order.get("price", 0),
                    "pricetype": order.get("order_type", "LIMIT"),
                    "product": order.get("product", ""),
                }
            )

        normalised.append(
            {
                "trigger_id": str(gtt.get("id", "")),
                "trigger_type": gtt.get("type", ""),
                "status": gtt.get("status", ""),
                "symbol": oa_symbol or br_symbol,
                "exchange": exchange,
                "trigger_prices": condition.get("trigger_values", []),
                "last_price": condition.get("last_price", 0),
                "legs": legs,
                "created_at": gtt.get("created_at", ""),
                "updated_at": gtt.get("updated_at", ""),
                "expires_at": gtt.get("expires_at", ""),
            }
        )

    return normalised
