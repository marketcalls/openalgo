# Mapping OpenAlgo API Request https://openalgo.in/docs
# Mapping TradeSmart (Noren v2) order parameters

from database.token_db import get_br_symbol
from utils.logging import get_logger
from utils.mpp_slab import calculate_protected_price, get_instrument_type_from_symbol

logger = get_logger(__name__)


def transform_data(data, token=None, uid="", auth_token=None):
    """Transform an OpenAlgo order request into a TradeSmart PlaceOrder payload.

    TradeSmart's OMS rejects market-type orders placed via the API
    ("ALGO_CHK: MKT Order type not allowed for API order"), so we apply Market
    Price Protection: MARKET -> LMT and SL-M -> SL-LMT, priced from the live LTP
    (or trigger price for SL-M) with a slab-based protection buffer rounded to
    the tick size. ``auth_token`` is needed to fetch the quote.

    ``uid`` is the resolved client/account id (caller supplies it).
    """
    symbol = get_br_symbol(data["symbol"], data["exchange"])
    # URL-encode ampersand for symbols like M&M-EQ (-> M%26M-EQ)
    if symbol and "&" in symbol:
        symbol = symbol.replace("&", "%26")

    action = data["action"].upper()
    pricetype = data["pricetype"]
    order_type = map_order_type(pricetype)
    userid = uid
    price = str(data.get("price", "0"))

    # Market Price Protection: convert disallowed market-type orders to limit-type
    if pricetype in ("MARKET", "SL-M"):
        order_type, price = _apply_mpp(data, action, pricetype, price, auth_token)

    transformed = {
        "uid": userid,
        "actid": userid,
        "exch": data["exchange"],
        "tsym": symbol,
        "qty": str(data["quantity"]),
        "prc": price,
        "trgprc": str(data.get("trigger_price", "0")),
        "dscqty": str(data.get("disclosed_quantity", "0")),
        "prd": map_product_type(data["product"]),
        "trantype": "B" if action == "BUY" else "S",
        "prctyp": order_type,
        "ret": "DAY",
        "ordersource": "API",
    }

    # Log without sensitive fields (uid/actid carry the client id)
    safe_log = {k: v for k, v in transformed.items() if k not in ("uid", "actid")}
    logger.info(f"Transformed order data: {safe_log}")
    return transformed


def transform_modify_order_data(data, token=None, uid=""):
    """Build the ModifyOrder payload (price/qty/type changes)."""
    symbol = data["symbol"]
    if symbol and "&" in symbol:
        symbol = symbol.replace("&", "%26")

    result = {
        "uid": uid,
        "exch": data["exchange"],
        "norenordno": data["orderid"],
        "prctyp": map_order_type(data["pricetype"]),
        "prc": str(data["price"]),
        "qty": str(data["quantity"]),
        "tsym": symbol,
        "ret": "DAY",
        "dscqty": str(data.get("disclosed_quantity") or 0),
    }

    # Only send trigger price for stop orders — sending trgprc=0 for a LIMIT
    # order triggers "Trigger price invalid - 0.00" on Noren.
    if data["pricetype"] in ["SL", "SL-M"]:
        result["trgprc"] = str(data.get("trigger_price") or 0)

    return result


def map_order_type(pricetype):
    """OpenAlgo price type -> TradeSmart price type."""
    order_type_mapping = {"MARKET": "MKT", "LIMIT": "LMT", "SL": "SL-LMT", "SL-M": "SL-MKT"}
    return order_type_mapping.get(pricetype, "MKT")


def map_product_type(product):
    """OpenAlgo product -> TradeSmart product (C=CNC, M=NRML, I=MIS)."""
    product_type_mapping = {"CNC": "C", "NRML": "M", "MIS": "I"}
    return product_type_mapping.get(product, "I")


def reverse_map_product_type(product):
    """TradeSmart product -> OpenAlgo product."""
    reverse_product_type_mapping = {"C": "CNC", "M": "NRML", "I": "MIS"}
    return reverse_product_type_mapping.get(product)


def _apply_mpp(data, action, pricetype, supplied_price, auth_token):
    """Convert a market-type order to its limit-type equivalent with a protected price.

    Returns ``(order_type, price)``:
      * MARKET -> ("LMT", protected price based on LTP)
      * SL-M   -> ("SL-LMT", protected price based on the trigger price)

    Always returns the converted ``order_type`` (even if the quote can't be
    fetched) so the order never goes out as MKT/SL-MKT, which TradeSmart rejects.
    """
    target_type = "LMT" if pricetype == "MARKET" else "SL-LMT"
    fallback_price = (
        supplied_price
        if pricetype == "MARKET"
        else str(data.get("trigger_price", "0") or "0")
    )

    if not auth_token:
        logger.warning(
            f"MPP: no auth token for {data['symbol']}; converting "
            f"{pricetype}->{target_type} at supplied price {fallback_price}"
        )
        return target_type, fallback_price

    try:
        from broker.tradesmart.api.data import BrokerData

        quote = BrokerData(auth_token).get_quotes(data["symbol"], data["exchange"])
        ltp = float(quote.get("ltp", 0))
        tick_size = quote.get("tick_size")
        instrument_type = get_instrument_type_from_symbol(data["symbol"])

        # MARKET prices off LTP; SL-M prices off the trigger (fall back to LTP)
        if pricetype == "MARKET":
            basis = ltp
        else:
            basis = float(data.get("trigger_price", 0) or 0) or ltp

        if basis and basis > 0:
            protected = calculate_protected_price(
                price=basis,
                action=action,
                symbol=data["symbol"],
                instrument_type=instrument_type,
                tick_size=tick_size,
            )
            logger.info(
                f"MPP: {pricetype}->{target_type} {data['symbol']} "
                f"basis={basis} protected={protected}"
            )
            return target_type, str(protected)

        logger.warning(
            f"MPP: LTP/basis unavailable for {data['symbol']}; converting "
            f"{pricetype}->{target_type} at supplied price {fallback_price}"
        )
        return target_type, fallback_price
    except Exception as e:
        logger.error(
            f"MPP error for {data['symbol']}: {e}; converting "
            f"{pricetype}->{target_type} at supplied price {fallback_price}"
        )
        return target_type, fallback_price
