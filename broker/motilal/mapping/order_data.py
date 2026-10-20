import json

from broker.motilal.mapping.transform_data import (
    reverse_map_exchange,
    reverse_map_product_type,
)
from database.token_db import get_symbol
from utils.logging import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

#: Motilal REST books quote prices as integers scaled by 10**precision and ship
#: the scale in a ``precision`` field (doc 18-trade-book.md: precision 2,
#: tradeprice 278400, tradeqty 20, tradevalue 5568000 -> 2784.00 x 20).
#: Doc 32 does not declare a default, so fall back to 2 when the field is absent.
DEFAULT_PRECISION = 2

#: Motilal order statuses (doc 32-parameters-constants.md / FAQ Q25):
#: Unknown, Sent, Confirm, Cancel, Partial, Traded, Rejected, Error.
#: OpenAlgo's valid set is defined in services/flow_node_contracts.py:
#: {"any", "open", "trigger pending", "complete", "rejected", "cancelled"}.
#: Casing varies across MOFSL channels (doc 17 "Error" vs doc 34 uppercase), so
#: every lookup here is done on a lower-cased key.
ORDER_STATUS_MAP = {
    "traded": "complete",
    "complete": "complete",
    "sent": "open",
    "confirm": "open",
    "open": "open",
    "partial": "open",  # live, partially filled -> still an open order
    "unknown": "open",  # transient pre-confirmation state -> treat as open
    "rejected": "rejected",
    "error": "rejected",
    "cancel": "cancelled",
    "cancelled": "cancelled",
}


def _to_float(value, default=0.0):
    """Coerce a Motilal numeric field to float.

    Doc-typed Decimal(15,4) fields (price, LTP, marktomarket, ...) may arrive as
    JSON numbers or as strings depending on the endpoint. Coerce so downstream
    arithmetic cannot raise TypeError or silently concatenate strings.
    """
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_int(value, default=0):
    return int(_to_float(value, default))


def _get_precision(record, default=None):
    """Return the price scale exponent for one Motilal record, or ``default``.

    ``default`` is what to use when the record carries no ``precision`` field.
    ``None`` (the default) means "this endpoint does not publish a scale, so do
    not rescale". Endpoints that DO document the field pass
    ``DEFAULT_PRECISION``: a row that omits it is still scaled, because the
    scale is a property of the endpoint, not of the individual row (live trade
    book rows have been observed without it, which rendered prices in paisa).
    Only docs 18 (trade book), 20, 34 and 35 carry a ``precision`` field; docs 17
    (order book) and 19 (order detail) do not. Where it IS published the scale is
    provable -- doc 18 has ``tradeprice 278400 * tradeqty 20 == tradevalue
    5568000`` with ``precision 2``, i.e. a real price of 2784.00.

    Where it is NOT published we deliberately do not guess. Doc 17's sample
    (``averageprice 394305`` for BSE IDBI, a ~Rs39 scrip) implies a scale of 4,
    not the 2 used elsewhere, and that record is internally odd anyway
    (orderstatus "Error", price 0, yet a traded quantity). Assuming 2 there would
    render order-book prices 100x too high. Leaving them unscaled preserves the
    long-standing behaviour until a live order-book response settles it.
    """
    if record.get("precision") is None:
        return default
    precision = _to_int(record.get("precision"), DEFAULT_PRECISION)
    if precision < 0 or precision > 8:
        return DEFAULT_PRECISION
    return precision


def _scale_price(value, precision, default=0.0):
    """Convert a Motilal scaled integer price to rupees.

    ``precision is None`` -> the endpoint publishes no scale; pass the value
    through untouched rather than guessing (see :func:`_get_precision`).
    """
    value = _to_float(value, default)
    if precision is None:
        return value
    return value / (10**precision)


def _map_order_status(order_status):
    """Map a Motilal order status to the OpenAlgo status vocabulary."""
    key = str(order_status or "").strip().lower()
    mapped = ORDER_STATUS_MAP.get(key)
    if mapped is None:
        logger.warning(f"Unrecognised Motilal order status '{order_status}'; treating as open.")
        return "open"
    return mapped


def _raise_on_failure(response, book_name):
    """Surface a Motilal FAILURE response instead of rendering an empty book.

    Doc 04-response-format.md: status is SUCCESS or FAILURE, message carries the
    description and errorcode the code from doc 31-error-codes.md. Returning []
    for a FAILURE would make an expired token look like "no orders".
    """
    if not isinstance(response, dict):
        return
    status = str(response.get("status", "")).strip().upper()
    if status == "FAILURE":
        message = response.get("message") or f"{book_name} request failed"
        errorcode = response.get("errorcode") or ""
        detail = f"{message} (errorcode: {errorcode})" if errorcode else str(message)
        logger.error(f"Motilal {book_name} returned FAILURE: {detail}")
        raise ValueError(f"Motilal {book_name} failed: {detail}")


# ---------------------------------------------------------------------------
# Order book
# ---------------------------------------------------------------------------


def map_order_data(order_data):
    """
    Processes and modifies a list of order dictionaries based on specific conditions.

    Parameters:
    - order_data: A list of dictionaries, where each dictionary represents an order.

    Returns:
    - The modified order_data with updated 'symbol', 'exchange' and 'producttype' fields.
    """
    _raise_on_failure(order_data, "order book")

    # Check if order_data is empty or doesn't have 'data' key
    if not order_data or "data" not in order_data or order_data["data"] is None:
        logger.info("No data available.")
        return []  # Return empty list as the functions expect a list

    order_data = order_data["data"]
    logger.info(f"{order_data}")

    if order_data:
        for order in order_data:
            # Extract the instrument_token and exchange for the current order
            # Doc 17 types symboltoken as Number, but SymToken.token is a String
            # column, so coerce before every DB lookup.
            symboltoken = str(order.get("symboltoken", ""))
            motilal_exchange = order.get("exchange", "")
            # Convert Motilal exchange (NSEFO) to OpenAlgo exchange (NFO) for database lookup
            openalgo_exchange = reverse_map_exchange(motilal_exchange)

            # Use the get_symbol function to fetch the symbol from the database
            # Use OpenAlgo exchange format for lookup
            symbol_from_db = get_symbol(symboltoken, openalgo_exchange)

            if symbol_from_db:
                order["symbol"] = symbol_from_db  # Motilal uses 'symbol' field
            else:
                logger.info(
                    f"Symbol not found for token {symboltoken} and exchange {openalgo_exchange}. "
                    "Keeping original trading symbol."
                )

            # Exchange and product are normalised regardless of whether the
            # symbol lookup succeeded, so the book never mixes Motilal
            # vocabulary (DELIVERY/NORMAL/VALUEPLUS) with OpenAlgo vocabulary.
            order["exchange"] = openalgo_exchange
            order["producttype"] = reverse_map_product_type(
                order.get("producttype", ""), openalgo_exchange
            )

    return order_data


def calculate_order_statistics(order_data):
    """
    Calculates statistics from order data, including totals for buy orders, sell orders,
    completed orders, open orders, and rejected orders.

    Parameters:
    - order_data: A list of dictionaries, where each dictionary represents an order.

    Returns:
    - A dictionary containing counts of different types of orders.
    """
    # Initialize counters
    total_buy_orders = total_sell_orders = 0
    total_completed_orders = total_open_orders = total_rejected_orders = 0

    if order_data:
        for order in order_data:
            # Count buy and sell orders - Motilal uses 'buyorsell' field
            buyorsell = str(order.get("buyorsell", "") or "").strip().upper()
            if buyorsell == "BUY":
                total_buy_orders += 1
            elif buyorsell == "SELL":
                total_sell_orders += 1

            # Count orders based on their status - Motilal uses 'orderstatus' field.
            # Shares the single status table, so Partial/Unknown count as open.
            order_status = _map_order_status(order.get("orderstatus", ""))
            if order_status == "complete":
                total_completed_orders += 1
            elif order_status == "open":
                total_open_orders += 1
            elif order_status == "rejected":
                total_rejected_orders += 1
            # Note: 'cancelled' orders are not counted in statistics (following Angel One implementation)

    # Compile and return the statistics
    return {
        "total_buy_orders": total_buy_orders,
        "total_sell_orders": total_sell_orders,
        "total_completed_orders": total_completed_orders,
        "total_open_orders": total_open_orders,
        "total_rejected_orders": total_rejected_orders,
    }


def _order_timestamp(order):
    """Pick the best available timestamp for an order.

    Doc 17 returns lastmodifiedtime as "0" for orders that were never modified,
    so fall back to entrydatetime and then recordinserttime.
    """
    for field in ("lastmodifiedtime", "entrydatetime", "recordinserttime"):
        value = order.get(field)
        if value is None:
            continue
        value = str(value).strip()
        if value and value != "0":
            return value
    return ""


def transform_order_data(orders):
    # Directly handling a dictionary assuming it's the structure we expect
    if isinstance(orders, dict):
        # Convert the single dictionary into a list of one dictionary
        orders = [orders]

    transformed_orders = []

    for order in orders:
        # Make sure each item is indeed a dictionary
        if not isinstance(order, dict):
            logger.warning(
                f"Warning: Expected a dict, but found a {type(order)}. Skipping this item."
            )
            continue

        precision = _get_precision(order)

        # Prices come back scaled by 10**precision (see DEFAULT_PRECISION note).
        trigger_price = _scale_price(order.get("triggerprice", 0.0), precision)
        avg_price = _scale_price(order.get("averageprice", 0.0), precision)
        order_price = _scale_price(order.get("price", 0.0), precision)

        # Map Motilal order types to OpenAlgo standard format
        # Motilal returns: Market, Limit, Stoploss (casing varies by channel)
        # OpenAlgo standard: MARKET, LIMIT, SL, SL-M (uppercase)
        ordertype = str(order.get("ordertype", "") or "").strip().upper()
        if ordertype == "STOPLOSS":
            # Determine if it's SL or SL-M based on trigger price
            ordertype = "SL" if trigger_price > 0 else "SL-M"

        # Map Motilal order status to OpenAlgo standard format
        order_status = _map_order_status(order.get("orderstatus", ""))

        # Log for debugging price issues
        if order_price == 0 and ordertype == "LIMIT" and order_status == "open":
            logger.warning("LIMIT order with open status has price=0.")
            logger.warning(f"Order ID: {order.get('uniqueorderid')}")
            logger.warning(f"Symbol: {order.get('symbol')}")
            logger.warning(f"Order Type: {order.get('ordertype')}")
            logger.warning(f"Order Status: {order.get('orderstatus')}")
            logger.warning(
                f"Raw price field value: '{order.get('price')}' (type: {type(order.get('price'))})"
            )
            logger.warning(
                f"Raw averageprice field value: '{order.get('averageprice')}' "
                f"(type: {type(order.get('averageprice'))})"
            )
            try:
                logger.warning(f"Full raw order data: {json.dumps(order, indent=2, default=str)}")
            except (TypeError, ValueError):
                logger.warning(f"Full raw order data: {order}")

        # Determine which price to use:
        # - For executed orders: use averageprice (execution price)
        # - For pending/open orders: use price (order price)
        display_price = avg_price if avg_price > 0 else order_price

        transformed_order = {
            "symbol": order.get("symbol", ""),  # Motilal uses 'symbol'
            "exchange": order.get("exchange", ""),
            "action": str(order.get("buyorsell", "") or "").upper(),  # Ensure uppercase BUY/SELL
            "quantity": _to_int(order.get("orderqty", 0)),  # Motilal uses 'orderqty'
            "price": round(display_price, 2),  # Format to 2 decimal places
            "trigger_price": round(trigger_price, 2),  # Format to 2 decimal places
            "pricetype": ordertype,
            "product": order.get("producttype", ""),
            "orderid": order.get("uniqueorderid", ""),  # Motilal uses 'uniqueorderid'
            "order_status": order_status,  # Standardized lowercase status
            "timestamp": _order_timestamp(order),
        }

        transformed_orders.append(transformed_order)

    return transformed_orders


# ---------------------------------------------------------------------------
# Trade book
# ---------------------------------------------------------------------------


def map_trade_data(trade_data):
    """
    Processes and modifies a list of trade dictionaries based on specific conditions.

    Parameters:
    - trade_data: The Motilal trade book response.

    Returns:
    - The modified trade list with updated 'symbol', 'exchange' and 'producttype' fields.
    """
    _raise_on_failure(trade_data, "trade book")

    # get_api_response() returns {} for an empty body, so never subscript blindly.
    if not trade_data or "data" not in trade_data or trade_data["data"] is None:
        logger.info("No data available.")
        return []

    trade_data = trade_data["data"]

    if trade_data:
        for order in trade_data:
            # Doc 18 returns symbol as the bare name ("COCUDAKL") which does not
            # match the derivative brsymbol, so resolve by symboltoken like the
            # order book does. Doc 18 quotes the token; coerce to str anyway.
            symboltoken = str(order.get("symboltoken", ""))
            motilal_exchange = order.get("exchange", "")
            # Convert Motilal exchange to OpenAlgo exchange for database lookup
            openalgo_exchange = reverse_map_exchange(motilal_exchange)

            # Use the get_symbol function to fetch the symbol from the database
            symbol_from_db = get_symbol(symboltoken, openalgo_exchange)

            if symbol_from_db:
                order["symbol"] = symbol_from_db
            else:
                logger.info(
                    f"Unable to find the symbol for token {symboltoken} and exchange "
                    f"{openalgo_exchange}. Keeping original trading symbol."
                )

            # Normalise exchange and product regardless of the lookup result.
            order["exchange"] = openalgo_exchange
            order["producttype"] = reverse_map_product_type(
                order.get("producttype", ""), openalgo_exchange
            )

    return trade_data


def transform_tradebook_data(tradebook_data):
    """
    Transforms Motilal Oswal tradebook data to OpenAlgo format.
    Motilal field names: symbol, buyorsell, tradeqty, tradeprice, tradetime, etc.
    Prices/values are scaled by 10**precision (doc 18) and are divided back here.
    """
    transformed_data = []
    reported_scale_fallback = False
    for trade in tradebook_data:
        # doc 18 documents `precision` for this endpoint, and its sample proves
        # the scale: tradeprice 278400 x tradeqty 20 == tradevalue 5568000, i.e.
        # 2784.00 x 20. Live rows have been seen with the field ABSENT or set to
        # 0 - both of which mean "no usable scale for this row" and used to let
        # the raw paisa integers through - so fall back to the documented
        # default rather than rendering paisa in the UI.
        raw_precision = trade.get("precision")
        precision = _get_precision(trade, DEFAULT_PRECISION)
        if not precision or precision <= 0:
            precision = DEFAULT_PRECISION
            if not reported_scale_fallback:
                reported_scale_fallback = True
                logger.info(
                    "Motilal trade book reports precision=%r; assuming %s (doc 18) so "
                    "prices render in rupees. Raw tradeprice for %s was %r.",
                    raw_precision,
                    DEFAULT_PRECISION,
                    trade.get("symbol", "?"),
                    trade.get("tradeprice"),
                )
        transformed_trade = {
            "symbol": trade.get("symbol", ""),  # Motilal uses 'symbol'
            "exchange": trade.get("exchange", ""),
            "product": trade.get("producttype", ""),
            "action": str(trade.get("buyorsell", "") or "").upper(),  # doc 32: BUY/SELL
            "quantity": _to_int(trade.get("tradeqty", 0)),  # Motilal uses 'tradeqty'
            "average_price": round(
                _scale_price(trade.get("tradeprice", 0.0), precision), 2
            ),  # Motilal uses 'tradeprice'
            "trade_value": round(_scale_price(trade.get("tradevalue", 0.0), precision), 2),
            "orderid": trade.get("uniqueorderid", ""),  # Motilal uses 'uniqueorderid'
            "timestamp": trade.get("tradetime", ""),  # Motilal uses 'tradetime'
        }
        if not transformed_data:
            # First row of each call: shows the scale actually applied, and
            # proves this build of the mapping is the one running.
            logger.info(
                "Motilal trade book mapping: raw tradeprice=%r precision=%r -> "
                "scale 10^%s -> average_price=%s",
                trade.get("tradeprice"),
                raw_precision,
                precision,
                transformed_trade["average_price"],
            )
        transformed_data.append(transformed_trade)
    return transformed_data


# ---------------------------------------------------------------------------
# Positions
# ---------------------------------------------------------------------------


def map_position_data(position_data):
    """
    Processes and modifies position data based on specific conditions.
    Motilal uses 'productname' field instead of 'producttype' for positions.

    Parameters:
    - position_data: Response from Motilal positions API

    Returns:
    - Modified position_data with updated symbols and product types
    """
    _raise_on_failure(position_data, "position book")

    # Check if position_data is empty or doesn't have 'data' key
    if not position_data or "data" not in position_data or position_data["data"] is None:
        logger.info("No position data available.")
        return []

    position_data_list = position_data["data"]
    logger.info(f"Processing {len(position_data_list)} positions")

    if position_data_list:
        for position in position_data_list:
            # Doc 22 types symboltoken as Number; SymToken.token is a String column.
            symboltoken = str(position.get("symboltoken", ""))
            motilal_exchange = position.get("exchange", "")
            # Convert Motilal exchange to OpenAlgo exchange for database lookup
            openalgo_exchange = reverse_map_exchange(motilal_exchange)

            # Use the get_symbol function to fetch the symbol from the database
            symbol_from_db = get_symbol(symboltoken, openalgo_exchange)

            if symbol_from_db:
                position["symbol"] = symbol_from_db
            else:
                logger.info(
                    f"Symbol not found for token {symboltoken} and exchange {openalgo_exchange}. "
                    "Keeping original symbol."
                )

            # Normalise exchange and product regardless of the lookup result.
            # Motilal uses 'productname' for positions instead of 'producttype'.
            position["exchange"] = openalgo_exchange
            position["productname"] = reverse_map_product_type(
                position.get("productname", ""), openalgo_exchange
            )

    return position_data_list


def transform_positions_data(positions_data):
    """
    Transforms Motilal Oswal positions data to OpenAlgo format.
    Motilal doesn't have netqty - calculate from buyquantity and sellquantity.

    Note: doc 22-position.md carries no `precision` field and no paisa note, so
    position amounts/LTP are used as-is (no 10**precision scaling).
    """
    transformed_data = []
    for position in positions_data:
        # Calculate net quantity from buy and sell quantities
        buyqty = _to_int(position.get("buyquantity", 0))
        sellqty = _to_int(position.get("sellquantity", 0))
        net_qty = buyqty - sellqty

        # Calculate average price (weighted average if needed)
        buyamt = _to_float(position.get("buyamount", 0.0))
        sellamt = _to_float(position.get("sellamount", 0.0))
        avg_price = 0.0
        if net_qty != 0:
            if net_qty > 0:  # Long position
                avg_price = buyamt / buyqty if buyqty > 0 else 0.0
            else:  # Short position
                avg_price = sellamt / sellqty if sellqty > 0 else 0.0

        transformed_position = {
            "symbol": position.get("symbol", ""),  # Motilal uses 'symbol'
            "exchange": position.get("exchange", ""),
            "product": position.get("productname", ""),  # Motilal uses 'productname'
            "quantity": net_qty,
            "average_price": avg_price,
            "ltp": _to_float(position.get("LTP", 0.0)),  # Motilal uses 'LTP' (uppercase)
            "pnl": _to_float(position.get("marktomarket", 0.0))
            + _to_float(position.get("bookedprofitloss", 0.0)),  # Total P&L
        }
        transformed_data.append(transformed_position)
    return transformed_data


# ---------------------------------------------------------------------------
# Holdings
# ---------------------------------------------------------------------------


def transform_holdings_data(holdings_data):
    """
    Transforms Motilal Oswal holdings data to OpenAlgo format.
    Motilal holdings response has: scripname, dpquantity, buyavgprice, nsesymboltoken,
    bsescripcode (doc 21-holding.md). There is no LTP in the response, so P&L is only
    computed when a holding happens to carry one.

    Note: doc 21 carries no `precision` field and no paisa note, so buyavgprice is
    used as-is (no 10**precision scaling).
    """
    transformed_data = []
    # Motilal returns holdings directly in the data array
    holdings_list = (
        holdings_data if isinstance(holdings_data, list) else holdings_data.get("holdings", [])
    )

    for holdings in holdings_list:
        # Get the mapped OpenAlgo symbol and exchange from map_portfolio_data
        symbol = holdings.get("symbol", "")  # Already mapped by map_portfolio_data
        exchange = holdings.get("exchange", "NSE")  # Already determined by map_portfolio_data

        # dpquantity is the TOTAL quantity (doc 21) - it includes blocked, POA and
        # collateral quantities, so it is not the freely sellable quantity.
        dp_qty = _to_int(holdings.get("dpquantity", 0))
        avg_price = _to_float(holdings.get("buyavgprice", 0.0))

        # LTP is not part of the holdings response; only compute P&L if a build
        # of the API happens to supply one.
        ltp = _to_float(holdings.get("LTP", 0.0))
        if ltp > 0 and avg_price > 0 and dp_qty:
            pnl = (ltp - avg_price) * dp_qty
            pnlpercent = (ltp - avg_price) / avg_price * 100
        else:
            pnl = 0.0
            pnlpercent = 0.0

        transformed_position = {
            "symbol": symbol,
            "exchange": exchange,
            "quantity": dp_qty,
            "product": "CNC",  # Holdings are always CNC/DELIVERY
            "average_price": round(avg_price, 2),
            "pnl": round(pnl, 2),
            "pnlpercent": round(pnlpercent, 2),
        }
        transformed_data.append(transformed_position)
    return transformed_data


def map_portfolio_data(portfolio_data):
    """
    Processes Motilal Oswal portfolio/holdings data.
    Motilal returns holdings with nsesymboltoken and bsescripcode fields.

    Holdings structure:
    - scripname: Broker symbol (e.g., "RELAXO EQ")
    - dpquantity: Total quantity
    - buyavgprice: Average buy price
    - nsesymboltoken: NSE token
    - bsescripcode: BSE scrip code

    Parameters:
    - portfolio_data: A dictionary containing holdings data

    Returns:
    - The modified portfolio_data with mapped fields (OpenAlgo symbols and exchange).
    """
    # Log the raw response for debugging
    logger.info(
        f"Motilal Holdings API Response: status={portfolio_data.get('status')}, "
        f"data_type={type(portfolio_data.get('data'))}"
    )

    # Doc 04: a FAILURE must surface, not render as "no holdings".
    _raise_on_failure(portfolio_data, "holdings")

    # Motilal returns status as "SUCCESS" string
    if str(portfolio_data.get("status", "")).strip().upper() != "SUCCESS":
        logger.warning(f"Holdings API returned non-SUCCESS status: {portfolio_data.get('status')}")
        return {"holdings": [], "totalholding": None}

    if portfolio_data.get("data") is None:
        logger.info("No holdings data available (data is None).")
        return {"holdings": [], "totalholding": None}

    # Directly work with 'data' for clarity and simplicity
    data = portfolio_data["data"]

    # Check if data is empty list
    if isinstance(data, list) and len(data) == 0:
        logger.info("Holdings data is empty list - no holdings found in API response.")
        return {"holdings": [], "totalholding": None}

    logger.info(
        f"Processing {len(data) if isinstance(data, list) else 'unknown'} holdings from Motilal API"
    )

    # Motilal returns holdings as a list directly
    if isinstance(data, list):
        for idx, holding in enumerate(data):
            logger.info(
                f"Processing holding {idx + 1}: scripname={holding.get('scripname')}, "
                f"dpquantity={holding.get('dpquantity')}"
            )

            # Determine exchange based on which token is available
            # Priority: NSE token first, then BSE scripcode
            nsesymboltoken = holding.get("nsesymboltoken")
            bsescripcode = holding.get("bsescripcode")

            logger.debug(
                f"Tokens for {holding.get('scripname')}: nsesymboltoken={nsesymboltoken}, "
                f"bsescripcode={bsescripcode}"
            )

            exchange = None
            token = None

            # Check which token is available (non-zero, non-null)
            if _to_int(nsesymboltoken) > 0:
                exchange = "NSE"
                token = str(nsesymboltoken)
            elif _to_int(bsescripcode) > 0:
                exchange = "BSE"
                token = str(bsescripcode)
            else:
                # If no valid token, log and skip symbol lookup
                logger.warning(
                    f"No valid token found for holding: {holding.get('scripname', 'Unknown')}"
                )
                holding["symbol"] = holding.get("scripname", "")  # Keep broker symbol as fallback
                holding["exchange"] = "NSE"  # Default to NSE
                holding["product"] = "CNC"
                continue

            # Use get_symbol to fetch the OpenAlgo symbol from database.
            # Doc 21 types these tokens as Number; SymToken.token is a String column.
            symbol_from_db = get_symbol(token, exchange)

            if symbol_from_db:
                holding["symbol"] = symbol_from_db
                logger.info(
                    f"Mapped holding: {holding.get('scripname')} (token {token} on {exchange}) "
                    f"-> {symbol_from_db}"
                )
            else:
                # If symbol not found in database, keep the scripname as fallback
                logger.warning(
                    f"Symbol not found in DB for token {token} on {exchange}. "
                    f"Using scripname: {holding.get('scripname', '')}"
                )
                holding["symbol"] = holding.get("scripname", "")

            holding["exchange"] = exchange

            # All holdings are CNC/DELIVERY product
            holding["product"] = "CNC"

        logger.info(f"Completed processing holdings. Total processed: {len(data)}")

    return {"holdings": data, "totalholding": None}  # Match expected structure


def calculate_portfolio_statistics(holdings_data):
    """
    Calculates portfolio statistics from holdings data.

    Motilal does not return a totalholding summary, but doc 21-holding.md supplies
    dpquantity and buyavgprice, so the invested value IS computable. Only the LTP
    is genuinely missing from the holdings response, so unless a holding carries an
    LTP the current holding value is reported as the invested value and P&L as 0.
    """
    holdings = []
    if isinstance(holdings_data, dict):
        holdings = holdings_data.get("holdings") or []
    elif isinstance(holdings_data, list):
        holdings = holdings_data

    totalinvvalue = 0.0
    totalholdingvalue = 0.0

    for holding in holdings:
        if not isinstance(holding, dict):
            continue
        quantity = _to_int(holding.get("dpquantity", 0))
        avg_price = _to_float(holding.get("buyavgprice", 0.0))
        invested = quantity * avg_price
        totalinvvalue += invested

        # LTP is absent from doc 21; fall back to cost so holding value and P&L
        # stay consistent (P&L 0) instead of reporting a bogus zero market value.
        ltp = _to_float(holding.get("LTP", 0.0))
        totalholdingvalue += quantity * ltp if ltp > 0 else invested

    totalprofitandloss = totalholdingvalue - totalinvvalue
    totalpnlpercentage = (totalprofitandloss / totalinvvalue * 100) if totalinvvalue else 0.0

    return {
        "totalholdingvalue": round(totalholdingvalue, 2),
        "totalinvvalue": round(totalinvvalue, 2),
        "totalprofitandloss": round(totalprofitandloss, 2),
        "totalpnlpercentage": round(totalpnlpercentage, 2),
    }
