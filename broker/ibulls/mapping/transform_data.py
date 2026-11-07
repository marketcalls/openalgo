# Mapping OpenAlgo API Request https://openalgo.in/docs
# Mapping ibullssecurities Broking Parameters https://symphonyfintech.com/xts-trading-front-end-api/

from flask import has_request_context, session

from broker.ibulls.api.data import BrokerData
from database.auth_db import Auth, get_auth_token, get_feed_token
from database.token_db import get_br_symbol, get_symbol_info, get_token
from utils.logging import get_logger
from utils.mpp_slab import calculate_protected_price

logger = get_logger(__name__)


def _feed_token_username():
    """The OpenAlgo user whose Ibulls feed token prices a MARKET order.

    A browser order has it in the session (``session["user"]``, set at login).
    An API, strategy or webhook order has no browser session, so it is the user
    of the stored Ibulls broker session (one user per deployment).
    """
    if has_request_context() and session.get("user"):
        return session["user"]
    row = Auth.query.filter_by(broker="ibulls", is_revoked=False).first()
    return row.name if row else None


def transform_data(data, token):
    """
    Transforms the new API request structure to the current expected structure.
    A MARKET order is sent as LIMIT at the LTP plus the Market Price Protection
    slab (utils/mpp_slab.py), rounded to the instrument's tick size.
    """
    symbol = get_br_symbol(data["symbol"], data["exchange"])

    # Check if market order and convert to limit order with adjusted price
    order_type = map_order_type(data["pricetype"])
    price = data.get("price", "0")
    action = data["action"].upper()

    if data["pricetype"] == "MARKET":
        try:
            username = _feed_token_username()
            feed_token = get_feed_token(username)

            if feed_token:
                # Create BrokerData instance to use get_quotes - only need feed_token for market data
                broker_data = BrokerData(feed_token, feed_token)

                # Fetch quotes for the symbol
                quote_data = broker_data.get_quotes(data["symbol"], data["exchange"])
                logger.info(f"Quote data for market order adjustment: {quote_data}")

                ltp = float(quote_data.get("ltp") or 0)
                if ltp > 0:
                    info = get_symbol_info(data["symbol"], data["exchange"])
                    price = str(
                        calculate_protected_price(
                            price=ltp,
                            action=action,
                            symbol=data["symbol"],
                            tick_size=getattr(info, "tick_size", None) if info else None,
                            exchange=data["exchange"],
                        )
                    )
                    order_type = "LIMIT"
                    logger.info(f"MPP: MARKET {action} sent as LIMIT at {price} (LTP {ltp})")
                else:
                    logger.warning(
                        f"MPP: no LTP for {data['symbol']}, sending the MARKET order as it is"
                    )
            else:
                logger.warning(
                    "No feed token available, cannot fetch quotes for market order price adjustment"
                )
        except Exception as e:
            logger.error(
                f"Error adjusting market order price: {str(e)}. Proceeding with regular market order."
            )

    # Basic mapping
    transformed = {
        "exchangeSegment": map_exchange(data["exchange"]),
        "exchangeInstrumentID": token,
        "productType": map_product_type(data["product"]),
        "orderType": order_type,
        "orderSide": action,
        "timeInForce": "DAY",
        "disclosedQuantity": data.get("disclosed_quantity", "0"),
        "orderQuantity": data["quantity"],
        "limitPrice": price,
        "stopPrice": data.get("trigger_price", "0"),
        "orderUniqueIdentifier": "openalgo",
    }
    logger.info(f"transformed data: {transformed}")
    return transformed


def transform_modify_order_data(data, token):
    return {
        "appOrderID": data["orderid"],
        "modifiedProductType": map_product_type(data["product"]),
        "modifiedOrderType": map_order_type(data["pricetype"]),
        "modifiedOrderQuantity": data["quantity"],
        "modifiedDisclosedQuantity": data.get("disclosed_quantity", "0"),
        "modifiedLimitPrice": data["price"],
        "modifiedStopPrice": data.get("trigger_price", "0"),
        "modifiedTimeInForce": "DAY",
        "orderUniqueIdentifier": "openalgo",
    }


def map_exchange(exchange):
    """
    Maps the new exchange to the existing exchange.
    """
    exchange_mapping = {
        "NSE": "NSECM",
        "BSE": "BSECM",
        "MCX": "MCXFO",
        "NFO": "NSEFO",
        "BFO": "BSEFO",
        "CDS": "NSECD",
        "EXCHANGE": "EXCHANGE",
    }
    return exchange_mapping.get(exchange, "EXCHANGE")


def map_order_type(pricetype):
    """
    Maps the new pricetype to the existing order type.
    """
    order_type_mapping = {
        "MARKET": "MARKET",
        "LIMIT": "LIMIT",
        "SL": "STOPLIMIT",
        "SL-M": "STOPMARKET",
    }
    return order_type_mapping.get(pricetype, "MARKET")  # Default to MARKET if not found


def map_product_type(product):
    """
    Maps the new product type to the existing product type.
    """
    product_type_mapping = {
        "CNC": "CNC",
        "NRML": "NRML",
        "MIS": "MIS",
    }
    return product_type_mapping.get(product, "MIS")  # Default to INTRADAY if not found


def reverse_map_product_type(exchange, product):
    """
    Reverse maps the broker product type to the OpenAlgo product type, considering the exchange.
    """
    # Exchange to OpenAlgo product type mapping for 'D'
    exchange_mapping = {
        "CNC": "CNC",
        "NRML": "NRML",
        "MIS": "MIS",
    }

    return exchange_mapping.get(product)
