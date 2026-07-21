# Mapping OpenAlgo API Request https://openalgo.in/docs
# Mapping Upstox Broking Parameters https://dhanhq.co/docs/v2/orders/

from database.token_db import get_symbol_info
from utils.logging import get_logger
from utils.mpp_slab import calculate_protected_price, get_instrument_type_from_symbol

logger = get_logger(__name__)


def _slm_protected_price(symbol, exchange, action, trigger_price):
    """
    Derive a protective stop-limit price for an SL-M order from its trigger price.

    Dhan's live API does not honor a bare STOP_LOSS_MARKET as a resting market stop
    under the SEBI MPP regime: it either drops the trigger and fills immediately as a
    LIMIT, or rejects the order with DH-906 "Trigger Price should be greater than
    Price" (the limit price it substitutes via MPP lands on the wrong side of the
    trigger). See GitHub issue #1647.

    To place a stop that actually rests, SL-M is mapped to Dhan's STOP_LOSS
    (stop-limit) with a limit price offset MPP% beyond the trigger in the fill
    direction (SELL below the trigger, BUY above it) so it stays marketable once
    triggered. This mirrors the shared MPP handling used by the other Noren/MPP
    brokers (e.g. samco).
    """
    instrument_type = get_instrument_type_from_symbol(symbol)
    tick_size = None
    try:
        symbol_info = get_symbol_info(symbol, exchange)
        if symbol_info and getattr(symbol_info, "tick_size", None):
            tick_size = float(symbol_info.tick_size)
    except Exception as e:
        logger.warning(f"Dhan SL-M: tick size lookup failed for {symbol}/{exchange}: {e}")

    return calculate_protected_price(
        price=trigger_price,
        action=action,
        symbol=symbol,
        instrument_type=instrument_type,
        tick_size=tick_size,
    )


def transform_data(data, token):
    """
    Transforms the OpenAlgo API request structure to Dhan v2 API structure.
    Based on the exact structure from Dhan documentation.
    """
    # Build payload exactly as shown in Dhan documentation
    transformed = {
        "dhanClientId": data.get("dhan_client_id", data["apikey"]),
        "transactionType": data["action"].upper(),
        "exchangeSegment": map_exchange_type(data["exchange"]),
        "productType": map_product_type(data["product"]),
        "orderType": map_order_type(data["pricetype"]),
        "validity": "DAY",
        "securityId": token,
        "quantity": int(data["quantity"]),
    }

    # Add optional fields only if needed
    correlation_id = data.get("correlation_id", "")
    if correlation_id:
        transformed["correlationId"] = correlation_id

    # Set price for limit-priced orders (LIMIT and SL). MARKET carries no price —
    # Dhan applies its own MPP (market->limit) conversion server-side. SL-M is
    # handled below (converted to a protective STOP_LOSS with a derived limit).
    if data["pricetype"] in ["LIMIT", "SL"]:
        price = float(data.get("price", 0))
        transformed["price"] = float(price)

    # Set disclosed quantity if provided
    disclosed_qty = int(data.get("disclosed_quantity", 0))
    if disclosed_qty > 0:
        transformed["disclosedQuantity"] = disclosed_qty

    # Set trigger price for SL orders
    if data["pricetype"] in ["SL", "SL-M"]:
        trigger_price = float(data.get("trigger_price", 0))
        if trigger_price <= 0:
            raise ValueError("Trigger price is required for Stop Loss orders")
        transformed["triggerPrice"] = float(trigger_price)

        # Map SL-M -> STOP_LOSS with an MPP-protected limit price so the stop rests
        # instead of being mangled/rejected by Dhan's live MPP. See _slm_protected_price.
        if data["pricetype"] == "SL-M":
            protected_price = _slm_protected_price(
                data["symbol"], data["exchange"], data["action"], trigger_price
            )
            transformed["orderType"] = "STOP_LOSS"
            transformed["price"] = float(protected_price)
            logger.info(
                f"Dhan SL-M -> STOP_LOSS: Symbol={data['symbol']}, Action={data['action']}, "
                f"Trigger={trigger_price}, ProtectedLimit={protected_price}"
            )

    # Handle after market orders
    after_market = data.get("after_market_order", False)
    if after_market:
        transformed["afterMarketOrder"] = True
        amo_time = data.get("amo_time", "")
        if amo_time in ["PRE_OPEN", "OPEN", "OPEN_30", "OPEN_60"]:
            transformed["amoTime"] = amo_time

    # Handle bracket order values
    if data.get("product") == "BO":
        bo_profit = data.get("bo_profit_value")
        bo_stop_loss = data.get("bo_stop_loss_value")
        if bo_profit:
            transformed["boProfitValue"] = float(bo_profit)
        if bo_stop_loss:
            transformed["boStopLossValue"] = float(bo_stop_loss)

    # Handle IOC validity
    if data.get("validity") == "IOC":
        transformed["validity"] = "IOC"

    return transformed


def transform_modify_order_data(data):
    modified = {
        "dhanClientId": data.get("dhan_client_id", data["apikey"]),
        "orderId": data["orderid"],
        "orderType": map_order_type(data["pricetype"]),
        "legName": "ENTRY_LEG",
        "quantity": int(data["quantity"]),
        "validity": "DAY",
    }

    # Set price for limit-priced orders (LIMIT and SL). SL-M is handled below.
    if data.get("pricetype") in ["LIMIT", "SL"]:
        modified["price"] = float(data["price"])

    # Set disclosed quantity if provided
    disclosed_qty = int(data.get("disclosed_quantity", 0))
    if disclosed_qty > 0:
        modified["disclosedQuantity"] = disclosed_qty

    # Handle trigger price for SL orders
    if data["pricetype"] in ["SL", "SL-M"]:
        trigger_price = float(data.get("trigger_price", 0))
        if trigger_price > 0:
            modified["triggerPrice"] = float(trigger_price)

            # Same SL-M -> protective STOP_LOSS conversion as placement (see
            # _slm_protected_price / issue #1647), so a modified SL-M also rests.
            if data["pricetype"] == "SL-M":
                protected_price = _slm_protected_price(
                    data["symbol"], data["exchange"], data["action"], trigger_price
                )
                modified["orderType"] = "STOP_LOSS"
                modified["price"] = float(protected_price)
                logger.info(
                    f"Dhan SL-M modify -> STOP_LOSS: Symbol={data['symbol']}, "
                    f"Action={data['action']}, Trigger={trigger_price}, ProtectedLimit={protected_price}"
                )

    return modified


def map_order_type(pricetype):
    """
    Maps the new pricetype to the existing order type.
    """
    order_type_mapping = {
        "MARKET": "MARKET",
        "LIMIT": "LIMIT",
        "SL": "STOP_LOSS",
        "SL-M": "STOP_LOSS_MARKET",
    }
    return order_type_mapping.get(pricetype, "MARKET")  # Default to MARKET if not found


def map_exchange_type(exchange):
    """
    Maps the Broker Exchange to the OpenAlgo Exchange.
    """
    exchange_mapping = {
        "NSE": "NSE_EQ",
        "BSE": "BSE_EQ",
        "CDS": "NSE_CURRENCY",
        "NFO": "NSE_FNO",
        "BFO": "BSE_FNO",
        "BCD": "BSE_CURRENCY",
        "MCX": "MCX_COMM",
    }
    return exchange_mapping.get(exchange)  # Default to MARKET if not found


def map_exchange(brexchange):
    """
    Maps the Broker Exchange to the OpenAlgo Exchange.
    """
    exchange_mapping = {
        "NSE_EQ": "NSE",
        "BSE_EQ": "BSE",
        "NSE_CURRENCY": "CDS",
        "NSE_FNO": "NFO",
        "BSE_FNO": "BFO",
        "BSE_CURRENCY": "BCD",
        "MCX_COMM": "MCX",
    }
    # Fall back to the raw broker segment instead of None so an unmapped
    # segment degrades to a visible label rather than propagating null
    # downstream (which crashes the positions UI). See issue #1463.
    return exchange_mapping.get(brexchange, brexchange)


def map_product_type(product):
    """
    Maps the new product type to the existing product type.
    """
    product_type_mapping = {
        "CNC": "CNC",
        "NRML": "MARGIN",
        "MIS": "INTRADAY",
    }
    return product_type_mapping.get(product, "INTRADAY")  # Default to INTRADAY if not found


def reverse_map_product_type(product):
    """
    Reverse maps the broker product type to the OpenAlgo product type, considering the exchange.
    """
    # Exchange to OpenAlgo product type mapping for 'D'
    product_mapping = {"CNC": "CNC", "MARGIN": "NRML", "MIS": "INTRADAY"}

    return product_mapping.get(product)  # Removed default; will return None if not found
