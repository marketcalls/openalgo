# Mapping OpenAlgo API Request https://openalgo.in/docs
# Mapping Rupeezy Vortex Parameters https://vortex.rupeezy.in/docs/latest/regular-order/
#
#   action    : BUY / SELL                 -> transaction_type BUY / SELL
#   pricetype : MARKET / LIMIT / SL / SL-M -> variety RL-MKT / RL / SL / SL-MKT
#   product   : CNC / NRML / MIS           -> DELIVERY / DELIVERY / INTRADAY
#
# Vortex has a single carry-forward product (DELIVERY) for both cash and F&O;
# the OpenAlgo product is recovered from the exchange on the way back.

from broker.rupeezy.mapping.exchange import build_ticker, to_vortex_quantity
from database.token_db import get_symbol_info

_VARIETY_MAP = {
    "MARKET": "RL-MKT",
    "LIMIT": "RL",
    "SL": "SL",
    "SL-M": "SL-MKT",
}

_REVERSE_VARIETY_MAP = {v: k for k, v in _VARIETY_MAP.items()}

_PRODUCT_MAP = {
    "CNC": "DELIVERY",
    "NRML": "DELIVERY",
    "MIS": "INTRADAY",
}

_CASH_EXCHANGES = {"NSE", "BSE", "NSE_EQ", "BSE_EQ"}


def map_variety(pricetype):
    return _VARIETY_MAP.get(str(pricetype).upper(), "RL-MKT")


def reverse_map_variety(variety):
    return _REVERSE_VARIETY_MAP.get(str(variety).upper(), variety)


def map_product_type(product):
    return _PRODUCT_MAP.get(str(product).upper(), "INTRADAY")


def reverse_map_product_type(exchange, product):
    """Vortex product -> OpenAlgo product. DELIVERY is CNC on cash segments and
    NRML on derivatives; MTF and BTST are cash-only delivery variants."""
    product = str(product or "").upper()
    if product == "INTRADAY":
        return "MIS"
    if product in ("DELIVERY", "MTF", "BTST"):
        return "CNC" if str(exchange).upper() in _CASH_EXCHANGES else "NRML"
    return product or None


def resolve_instrument(symbol, exchange):
    """OpenAlgo (symbol, exchange) -> (ticker, brexchange, lotsize).

    Raises ValueError if the symbol is not in the master contract.
    """
    info = get_symbol_info(symbol, exchange)
    if not info:
        raise ValueError(f"Symbol {symbol} not found on {exchange}. Download the master contract.")
    return build_ticker(info.brexchange, info.brsymbol), info.brexchange, info.lotsize or 1


def _price(value):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def transform_data(data):
    """OpenAlgo place-order dict -> Vortex /trading/orders/regular payload."""
    ticker, brexchange, lotsize = resolve_instrument(data["symbol"], data["exchange"])
    variety = map_variety(data["pricetype"])

    payload = {
        "ticker": ticker,
        "transaction_type": str(data["action"]).upper(),
        "product": map_product_type(data["product"]),
        "variety": variety,
        "quantity": to_vortex_quantity(data["quantity"], brexchange, lotsize),
        # Market orders are sent with price 0 (docs: "In case of market orders,
        # you should send the Last Trade Price as 0").
        "price": 0.0 if variety in ("RL-MKT", "SL-MKT") else _price(data.get("price")),
        "trigger_price": _price(data.get("trigger_price")) if variety in ("SL", "SL-MKT") else 0.0,
        "disclosed_quantity": int(data.get("disclosed_quantity") or 0),
        "validity": "DAY",
        "is_amo": False,
        # Max 50 chars; free text that comes back on the order book.
        "order_identifier": str(data.get("strategy") or "openalgo")[:50],
    }
    return payload


def transform_modify_order_data(data, traded_quantity, brexchange, lotsize):
    """OpenAlgo modify-order dict -> Vortex PUT /trading/orders/regular/{id} payload.

    `traded_quantity` must be the latest value from the order book (in Vortex
    units), otherwise Vortex grows the order by the already-traded quantity.
    """
    variety = map_variety(data["pricetype"])
    return {
        "variety": variety,
        "quantity": to_vortex_quantity(data["quantity"], brexchange, lotsize),
        "traded_quantity": int(traded_quantity or 0),
        "price": 0.0 if variety in ("RL-MKT", "SL-MKT") else _price(data.get("price")),
        "trigger_price": _price(data.get("trigger_price")) if variety in ("SL", "SL-MKT") else 0.0,
        "disclosed_quantity": int(data.get("disclosed_quantity") or 0),
        "validity": "DAY",
    }
