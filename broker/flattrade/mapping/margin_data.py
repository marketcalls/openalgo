# Mapping OpenAlgo API Request https://openalgo.in/docs
# Mapping Flattrade GetBasketMargin API

from broker.flattrade.mapping.transform_data import map_order_type, map_product_type
from database.token_db import get_br_symbol
from utils.logging import get_logger
from utils.mpp_slab import calculate_protected_price, get_instrument_type_from_symbol

logger = get_logger(__name__)


def _apply_mpp(position, auth_token):
    """
    Convert MARKET/SL-M to LMT/SL-LMT with a protected price for basket margin.

    GetBasketMargin rejects MKT/SL-MKT price types, so for MARKET/SL-M inputs we
    always return a converted order type (LMT or SL-LMT) even when MPP can't
    fetch an LTP. Fallback price:
      - MARKET -> position.price (user-supplied limit, may be 0)
      - SL-M   -> position.trigger_price (at trigger, SL-LMT becomes a LIMIT
                  at this level)
    """
    pricetype = position.get("pricetype", "MARKET")
    action = position["action"].upper()
    price = str(position.get("price", 0) or 0)
    order_type = map_order_type(pricetype)

    if pricetype not in ("MARKET", "SL-M"):
        return order_type, price

    original_type = pricetype
    converted_order_type = "LMT" if original_type == "MARKET" else "SL-LMT"
    fallback_price = (
        str(position.get("price", 0) or 0)
        if original_type == "MARKET"
        else str(position.get("trigger_price", 0) or 0)
    )

    logger.info(
        f"Margin MPP: {original_type} detected Symbol={position['symbol']}, "
        f"Exchange={position['exchange']}, Action={action}"
    )
    try:
        if not auth_token:
            logger.warning(
                f"Margin MPP: no auth token for Symbol={position['symbol']}; "
                f"converting {original_type}->{converted_order_type} at supplied price={fallback_price}"
            )
            return converted_order_type, fallback_price

        from broker.flattrade.api.data import BrokerData

        broker_data = BrokerData(auth_token)
        quote = broker_data.get_quotes(position["symbol"], position["exchange"])
        ltp = float(quote.get("ltp", 0))
        tick_size = quote.get("tick_size")
        instrument_type = get_instrument_type_from_symbol(position["symbol"])

        logger.info(
            f"Margin MPP Quote: Symbol={position['symbol']}, LTP={ltp}, "
            f"TickSize={tick_size}, InstrumentType={instrument_type}"
        )

        if ltp > 0:
            protected = calculate_protected_price(
                price=ltp,
                action=action,
                symbol=position["symbol"],
                instrument_type=instrument_type,
                tick_size=tick_size,
            )
            logger.info(
                f"Margin MPP Converted: {original_type}->{converted_order_type}, "
                f"FinalPrice={protected}"
            )
            return converted_order_type, str(protected)

        logger.warning(
            f"Margin MPP: LTP<=0 for Symbol={position['symbol']}; "
            f"converting {original_type}->{converted_order_type} at supplied price={fallback_price}"
        )
        return converted_order_type, fallback_price

    except Exception as e:
        logger.error(
            f"Margin MPP Error: Symbol={position['symbol']}, Error={e}. "
            f"Converting {original_type}->{converted_order_type} at supplied price={fallback_price}"
        )
        return converted_order_type, fallback_price


def _build_order(position, auth_token):
    oa_symbol = position["symbol"]
    exchange = position["exchange"]
    br_symbol = get_br_symbol(oa_symbol, exchange)
    if not br_symbol:
        logger.warning(f"Symbol not found for: {oa_symbol} on exchange: {exchange}")
        return None
    if "&" in br_symbol:
        br_symbol = br_symbol.replace("&", "%26")

    prctyp, prc = _apply_mpp(position, auth_token)

    return {
        "exch": exchange,
        "tsym": br_symbol,
        "qty": str(int(position["quantity"])),
        "prc": prc,
        "trgprc": str(position.get("trigger_price", 0) or 0),
        "prd": map_product_type(position.get("product", "NRML")),
        "trantype": "B" if position["action"].upper() == "BUY" else "S",
        "prctyp": prctyp,
    }


def transform_margin_positions(positions, userid, auth_token=None):
    orders = []
    for position in positions:
        try:
            order = _build_order(position, auth_token)
            if order:
                orders.append(order)
        except Exception as e:
            logger.error(f"Error transforming position: {position}, Error: {e}")
            continue
    if not orders:
        return {"uid": userid, "actid": userid, "basketlists": []}

    first = orders[0]
    rest = orders[1:]
    return {
        "uid": userid,
        "actid": userid,
        "exch": first["exch"],
        "tsym": first["tsym"],
        "qty": first["qty"],
        "prc": first["prc"],
        "trgprc": first["trgprc"],
        "prd": first["prd"],
        "trantype": first["trantype"],
        "prctyp": first["prctyp"],
        "basketlists": rest,
    }


def parse_margin_response(response_data):
    try:
        if not response_data or not isinstance(response_data, dict):
            return {"status": "error", "message": "Invalid response from broker"}
        if response_data.get("stat") != "Ok":
            error_message = (
                response_data.get("emsg")
                or response_data.get("remarks")
                or "Failed to calculate margin"
            )
            return {"status": "error", "message": error_message}
        # Flattrade doc semantics:
        #   marginused      -> "Total margin"        (pre-hedge basket total)
        #   marginusedtrade -> "Margin after trade"  (post-hedge account total)
        # Parallels Zerodha's initial.total vs final.total. Map total to
        # marginused (matches Zerodha impl using initial.total) and set
        # span/exposure to 0 since Flattrade gives no breakdown.
        margin_used = float(response_data.get("marginused", 0) or 0)
        return {
            "status": "success",
            "data": {
                "total_margin_required": margin_used,
                "span_margin": 0,
                "exposure_margin": 0,
            },
        }
    except Exception as e:
        logger.error(f"Error parsing margin response: {e}")
        return {"status": "error", "message": f"Failed to parse margin response: {str(e)}"}
