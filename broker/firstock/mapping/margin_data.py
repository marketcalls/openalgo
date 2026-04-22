# Mapping OpenAlgo API Request https://openalgo.in/docs
# Mapping Firstock basketMargin API

from broker.firstock.mapping.transform_data import map_order_type, map_product_type
from database.token_db import get_br_symbol, get_symbol_info
from utils.logging import get_logger
from utils.mpp_slab import calculate_protected_price, get_instrument_type_from_symbol

logger = get_logger(__name__)


def _apply_mpp(position, auth_token):
    """
    Convert MARKET/SL-M to LMT/SL-LMT with a protected price for basket margin.

    Matches the place-order MPP behavior: for MARKET/SL-M inputs we always
    return a converted order type (LMT or SL-LMT) even when MPP can't fetch
    an LTP. Fallback price when MPP fails:
      - MARKET -> position.price (user-supplied limit, may be 0)
      - SL-M   -> position.trigger_price (at trigger, SL-LMT becomes a LIMIT
                  at this level)
    Ensures the basketMargin payload never carries a bare MKT/SL-MKT with
    price=0 that would either be rejected or produce meaningless margin.
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

        from broker.firstock.api.data import BrokerData

        broker_data = BrokerData(auth_token)
        quote = broker_data.get_quotes(position["symbol"], position["exchange"])
        ltp = float(quote.get("ltp", 0))

        # Firstock's /getQuote response omits tick_size — fall back to the
        # master contract DB (same pattern as kotak / place-order MPP).
        tick_size = quote.get("tick_size")
        if not tick_size:
            symbol_info = get_symbol_info(position["symbol"], position["exchange"])
            if symbol_info and symbol_info.tick_size:
                tick_size = symbol_info.tick_size

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
    """Build a single Firstock basketMargin leg from an OpenAlgo position."""
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
        "exchange": exchange,
        "tradingSymbol": br_symbol,
        "quantity": str(int(position["quantity"])),
        "price": prc,
        "triggerPrice": str(position.get("trigger_price", 0) or 0),
        "product": map_product_type(position.get("product", "NRML")),
        "transactionType": "B" if position["action"].upper() == "BUY" else "S",
        "priceType": prctyp,
    }


def transform_margin_positions(positions, userid, auth_token=None):
    """
    Transform a list of OpenAlgo positions into a Firstock basketMargin payload.

    Firstock layout (per /V1/basketMargin docs):
      - First leg is flat at the top level of the request body
      - Additional legs are nested inside BasketList_Params[]
      - userId and jKey must be at top level (jKey is added by the caller)
    """
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
        return {"userId": userid, "BasketList_Params": []}

    first = orders[0]
    rest = orders[1:]
    return {
        "userId": userid,
        "exchange": first["exchange"],
        "tradingSymbol": first["tradingSymbol"],
        "quantity": first["quantity"],
        "price": first["price"],
        "triggerPrice": first["triggerPrice"],
        "product": first["product"],
        "transactionType": first["transactionType"],
        "priceType": first["priceType"],
        "BasketList_Params": rest,
    }


def parse_margin_response(response_data):
    """
    Parse Firstock /V1/basketMargin response into OpenAlgo's standard shape.

    Firstock success shape:
      {
        "status": "success",
        "data": {
          "BasketMargin": [...],
          "MarginOnNewOrder": 126783,
          "PreviousMargin": 0,
          "TradedMargin": 126783
        }
      }

    Firstock failure shape:
      {"status": "failed", "error": {"message": "..."}}
      or {"status": "failed"}

    TradedMargin is the post-hedge total margin (analogous to Zerodha's
    initial.total). Map to total_margin_required. span/exposure set to 0
    since Firstock doesn't break them down in this response.
    """
    try:
        if not response_data or not isinstance(response_data, dict):
            return {"status": "error", "message": "Invalid response from broker"}

        if response_data.get("status") != "success":
            error_obj = response_data.get("error") or {}
            error_message = (
                (error_obj.get("message") if isinstance(error_obj, dict) else None)
                or response_data.get("message")
                or response_data.get("emsg")
                or "Failed to calculate margin"
            )
            return {"status": "error", "message": error_message}

        data = response_data.get("data") or {}
        margin_used = float(data.get("TradedMargin", 0) or 0)

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
