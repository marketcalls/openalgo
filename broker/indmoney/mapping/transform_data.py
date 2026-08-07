# Mapping OpenAlgo API Request https://openalgo.in/docs
# Mapping Indmoney API Parameters https://api.indstocks.com/

from flask import session

from broker.indmoney.api.data import BrokerData
from database.auth_db import get_auth_token
from database.token_db import get_symbol_info
from utils.logging import get_logger
from utils.mpp_slab import calculate_protected_price, get_instrument_type_from_symbol

logger = get_logger(__name__)


def _protective_limit(trigger, action, symbol, exchange):
    """
    Derive a protective limit price from a stop trigger.

    INDstocks has no market-on-trigger order, so an SL-M has to go out as a
    trigger-limit. Pricing that limit at the trigger itself risks not filling on
    a gap, so add the MPP buffer in the direction of the fill - below the trigger
    for a SELL stop, above it for a BUY stop. Same approach as
    broker/flattrade and broker/shoonya, which face the same restriction.

    Falls back to the trigger price itself, which is already tick-valid.
    """
    try:
        info = get_symbol_info(symbol, exchange)
        tick_size = getattr(info, "tick_size", None)
        if tick_size:
            return float(
                calculate_protected_price(
                    price=trigger,
                    action=action,
                    symbol=symbol,
                    instrument_type=get_instrument_type_from_symbol(symbol),
                    tick_size=tick_size,
                )
            )
        logger.warning(
            f"No tick size for {symbol}/{exchange}; using the trigger price "
            f"({trigger}) as the protective limit rather than risking an off-tick price."
        )
    except Exception as e:
        logger.error(
            f"Could not derive a protective limit for {symbol}/{exchange}: {e}. "
            f"Using the trigger price ({trigger}) as-is."
        )
    return float(trigger)


def transform_data(data, token):
    """
    Transforms the OpenAlgo API request structure to Indmoney API structure.
    For market orders, fetches quotes and adjusts price accordingly:
    - BUY: Uses bid price + 0.1%
    - SELL: Uses ask price - 0.1%

    Parameters required by Indmoney API:
    - txn_type (required): BUY/SELL
    - exchange (required): NSE/BSE
    - segment (required): DERIVATIVE/EQUITY
    - product (required): MARGIN/INTRADAY/CNC
    - order_type (required): LIMIT/MARKET
    - validity (required): DAY/IOC
    - security_id (required): string
    - qty (required): integer
    - is_amo: boolean (for after market orders)
    - limit_price: float (required for LIMIT orders)
    """
    # Check if market order and convert to limit order with adjusted price
    order_type = map_order_type(data["pricetype"])
    price = data.get("price", "0")
    action = data["action"].upper()

    if data["pricetype"] == "MARKET":
        # Get username from Flask session (never fall back to a hard-coded user
        # — that would borrow another account's token). Without a session user
        # we cannot fetch a quote, so send a native MARKET order instead.
        username = None
        if session and hasattr(session, "get"):
            username = session.get("username")

        auth_token = get_auth_token(username) if username else None

        if not auth_token:
            logger.warning(
                "No session user/auth token available for market-order price "
                "adjustment; sending a native MARKET order."
            )
        else:
            logger.info(f"Using auth token for user: {username}")

            # Create BrokerData instance to use get_quotes - only need auth_token
            broker_data = BrokerData(auth_token)

            # Fetch quotes for the symbol
            quote_data = broker_data.get_quotes(data["symbol"], data["exchange"])
            logger.info(f"Quote data for market order adjustment: {quote_data}")

            # Adjust price based on action (BUY or SELL) using LTP
            ltp = float(quote_data.get("ltp", 0))
            if ltp <= 0:
                logger.warning(
                    "LTP unavailable for market-order adjustment; sending a native MARKET order."
                )
            elif action == "BUY":
                # Add 0.1% to LTP for BUY orders
                adjusted_price = ltp * 1.001
                price = str(round(adjusted_price, 2))
                logger.info(f"Adjusted BUY price: LTP {ltp} + 0.1% = {price}")
                # Change order type to LIMIT (uppercase required by API)
                order_type = "LIMIT"
            elif action == "SELL":
                # Subtract 0.1% from LTP for SELL orders
                adjusted_price = ltp * 0.999
                price = str(round(adjusted_price, 2))
                logger.info(f"Adjusted SELL price: LTP {ltp} - 0.1% = {price}")
                # Change order type to LIMIT (uppercase required by API)
                order_type = "LIMIT"

    # Basic mapping from OpenAlgo to Indmoney
    segment = map_segment(data["exchange"])
    # Indmoney order API only accepts NSE/BSE for the exchange field; F&O
    # exchanges (NFO/BFO/CDS/BCD) map to their NSE/BSE parent + DERIVATIVE segment.
    raw_exchange = data["exchange"].upper()
    api_exchange = map_exchange_type(raw_exchange)
    # Fail fast on exchanges the order API can't place, instead of letting the
    # default NSE mapping silently misroute the order. Only NSE/BSE and the F&O
    # exchanges that map onto them are placeable; MCX (maps to MCX) and any
    # unrecognised code are rejected.
    if raw_exchange not in {"NSE", "BSE", "NFO", "BFO", "CDS", "BCD"} or api_exchange not in {
        "NSE",
        "BSE",
    }:
        raise ValueError(
            f"Unsupported exchange for IndMoney order placement: {data['exchange']}"
        )
    # algo_id is exchange-specific: 99999 for NSE, 9999999999999999 for BSE.
    algo_id = "9999999999999999" if api_exchange == "BSE" else "99999"

    # --- Stop orders -------------------------------------------------------
    # /order supports only LIMIT and MARKET - it has no stop type and no
    # trigger_price field, so an SL/SL-M sent there loses its trigger entirely
    # and fires immediately. The trigger facility lives on /smart/order as
    # order_type "TRIGGER". Build that payload instead; place_order_api() routes
    # any TRIGGER order to the smart-order endpoint.
    if data["pricetype"] in ("SL", "SL-M"):
        trigger = float(data.get("trigger_price") or 0)
        if trigger <= 0:
            raise ValueError(
                f"A trigger_price is required for an {data['pricetype']} order "
                f"({data['symbol']})."
            )

        # Smart orders are documented for NSE only.
        if api_exchange != "NSE":
            raise ValueError(
                f"IndMoney supports stop orders (SL/SL-M) on NSE only; "
                f"{data['exchange']} was requested for {data['symbol']}."
            )

        if data["pricetype"] == "SL":
            # Trigger-limit: honour the caller's limit price, falling back to a
            # protective limit when none was supplied.
            limit_price = float(data.get("price") or 0)
            if limit_price <= 0:
                limit_price = _protective_limit(
                    trigger, action, data["symbol"], data["exchange"]
                )
        else:
            # SL-M: no market-on-trigger exists, so protect off the trigger.
            limit_price = _protective_limit(trigger, action, data["symbol"], data["exchange"])

        transformed = {
            "txn_type": action,
            "exchange": api_exchange,
            "segment": segment,
            "product": map_product_type(data["product"]),
            "order_type": "TRIGGER",
            "validity": "DAY",  # smart orders accept DAY only
            "security_id": token,
            "qty": int(data["quantity"]),
            "algo_id": algo_id,
            "trigger_price": trigger,
            "trigger_limit_price": limit_price,
        }
        logger.info(
            f"{data['pricetype']} -> smart TRIGGER order for {data['symbol']}: "
            f"trigger={trigger}, limit={limit_price}"
        )
        return transformed

    transformed = {
        "txn_type": action,  # BUY/SELL
        "exchange": api_exchange,  # NSE/BSE
        "segment": segment,  # DERIVATIVE/EQUITY
        "product": map_product_type(data["product"]),  # MARGIN/INTRADAY/CNC
        "order_type": order_type,  # LIMIT/MARKET
        "validity": "DAY",  # Default to DAY
        "security_id": token,  # Security ID from token
        "qty": int(data["quantity"]),  # Order quantity
        "is_amo": data.get("is_amo", False),  # After market order flag
        "algo_id": algo_id,  # Required by API - NSE: 99999, BSE: 9999999999999999
    }

    # Log the segment mapping for debugging
    logger.info(f"Exchange: {data['exchange']}, Mapped Segment: {segment}")
    logger.info(f"Order Type: {data.get('pricetype')} -> {transformed['order_type']}")

    # Add limit_price for LIMIT orders
    if data.get("pricetype") == "LIMIT" and data.get("price"):
        transformed["limit_price"] = float(data["price"])
    elif transformed["order_type"] == "LIMIT":
        # For LIMIT orders, price is required
        transformed["limit_price"] = float(price if price != "0" else data.get("price", 0))

    # Handle validity if specified
    if data.get("validity") == "IOC":
        transformed["validity"] = "IOC"

    # For equity orders, ensure we have all required fields
    if transformed["segment"] == "EQUITY":
        # Ensure limit_price is set for LIMIT orders
        if transformed["order_type"] == "LIMIT" and "limit_price" not in transformed:
            transformed["limit_price"] = float(price if price != "0" else data.get("price", 0))

    logger.info(f"transformed data: {transformed}")
    return transformed


def transform_modify_order_data(data):
    """
    Transforms OpenAlgo modify order data to Indmoney format.
    """
    transformed = {
        "segment": map_segment_from_orderid(data.get("orderid", "")),  # Derive from order ID
        "order_id": data["orderid"],
        "qty": int(data["quantity"]),
        "limit_price": float(data.get("price", 0)),
    }

    return transformed


def map_order_type(pricetype):
    """
    Maps OpenAlgo pricetype to Indmoney order_type.

    SL and SL-M map to TRIGGER, which is only valid on /smart/order - see the
    stop-order branch in transform_data(). They must NOT be flattened to
    LIMIT/MARKET on /order: that silently discards the trigger price and turns a
    stop into an order that fires immediately.
    """
    order_type_mapping = {
        "MARKET": "MARKET",
        "LIMIT": "LIMIT",  # Must be uppercase as per API requirement
        "SL": "TRIGGER",
        "SL-M": "TRIGGER",
    }
    return order_type_mapping.get(pricetype, "MARKET")


def map_segment(exchange):
    """
    Maps OpenAlgo exchange to Indmoney segment.
    """
    segment_mapping = {
        "NSE": "EQUITY",
        "BSE": "EQUITY",
        "NFO": "DERIVATIVE",
        "BFO": "DERIVATIVE",
        "CDS": "DERIVATIVE",
        "BCD": "DERIVATIVE",
        "MCX": "DERIVATIVE",
    }
    result = segment_mapping.get(exchange, "EQUITY")
    logger.debug(f"map_segment: {exchange} -> {result}")
    return result


def map_segment_from_orderid(orderid):
    """
    Maps order ID prefix to segment for modify/cancel operations.
    """
    if orderid.startswith("DRV-"):
        return "DERIVATIVE"
    else:
        return "EQUITY"


def map_exchange_type(exchange):
    """
    Maps OpenAlgo exchange to Indmoney exchange format.
    """
    exchange_mapping = {
        "NSE": "NSE",
        "BSE": "BSE",
        "NFO": "NSE",
        "BFO": "BSE",
        "CDS": "NSE",
        "BCD": "BSE",
        "MCX": "MCX",
    }
    return exchange_mapping.get(exchange, "NSE")


def map_exchange(br_exchange):
    """
    Maps Indmoney exchange back to OpenAlgo exchange.
    """
    exchange_mapping = {"NSE": "NSE", "BSE": "BSE", "MCX": "MCX"}
    return exchange_mapping.get(br_exchange, "NSE")


def map_product_type(product):
    """
    Maps OpenAlgo product type to Indmoney product type.
    """
    product_type_mapping = {
        "CNC": "CNC",
        "NRML": "MARGIN",
        "MIS": "INTRADAY",
    }
    return product_type_mapping.get(product, "INTRADAY")


def reverse_map_product_type(product):
    """
    Maps Indmoney product type back to OpenAlgo product type.
    """
    product_mapping = {"CNC": "CNC", "MARGIN": "NRML", "INTRADAY": "MIS"}
    return product_mapping.get(product, "MIS")
