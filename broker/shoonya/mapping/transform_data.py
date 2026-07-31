# Mapping OpenAlgo API Request https://openalgo.in/docs
# Mapping Shoonya Broking Parameters https://shoonya.com/api-documentation

from database.token_db import get_br_symbol, get_symbol_info
from utils.logging import get_logger
from utils.mpp_slab import calculate_protected_price, get_instrument_type_from_symbol

logger = get_logger(__name__)


def transform_data(data, token, auth_token=None):
    """
    Transforms the new API request structure to the current expected structure.
    For market orders, fetches quotes and adjusts price using MPP (Market Price Protection):
    - EQ/FUT: Price < 100: 2%, 100-500: 1%, > 500: 0.5%
    - OPT (CE/PE): Price < 10: 5%, 10-100: 3%, 100-500: 2%, > 500: 1%

    Args:
        data: Order data dictionary
        token: Instrument token
        auth_token: Authentication token for fetching quotes (passed from order_api)
    """
    userid = data["apikey"]
    symbol = get_br_symbol(data["symbol"], data["exchange"])
    # Handle special characters in symbol
    if symbol and "&" in symbol:
        symbol = symbol.replace("&", "%26")

    # Default values
    price = str(data.get("price", "0"))
    order_type = map_order_type(data["pricetype"])
    action = data["action"].upper()

    # Apply Market Price Protection for MARKET and SL-M orders
    # Shoonya blocks both MKT and SL-MKT order types for API orders
    if data["pricetype"] in ("MARKET", "SL-M"):
        original_type = data["pricetype"]
        logger.info(
            f"MPP: {original_type} order detected for Symbol={data['symbol']}, Exchange={data['exchange']}, Action={action}"
        )
        try:
            if auth_token:
                # Lazy import to avoid circular dependency
                from broker.shoonya.api.data import BrokerData

                # Create BrokerData instance to fetch quotes
                broker_data = BrokerData(auth_token)

                # Fetch quotes for the symbol
                quote_data = broker_data.get_quotes(data["symbol"], data["exchange"])
                logger.info(
                    f"MPP Quote Response: Symbol={data['symbol']}, Exchange={data['exchange']}, "
                    f"LTP={quote_data.get('ltp')}, Bid={quote_data.get('bid')}, Ask={quote_data.get('ask')}, "
                    f"TickSize={quote_data.get('tick_size')}"
                )

                # Get instrument type from symbol
                instrument_type = get_instrument_type_from_symbol(data["symbol"])

                # Get tick_size from quote response
                tick_size = quote_data.get("tick_size")
                logger.info(
                    f"MPP Symbol Info: InstrumentType={instrument_type}, TickSize={tick_size}"
                )

                # Get LTP for price calculation
                ltp = float(quote_data.get("ltp", 0))

                if ltp > 0:
                    # Calculate protected price using centralized MPP slab with tick size rounding
                    protected_price = calculate_protected_price(
                        price=ltp,
                        action=action,
                        symbol=data["symbol"],
                        instrument_type=instrument_type,
                        tick_size=tick_size,
                    )
                    price = str(protected_price)

                    if original_type == "MARKET":
                        # Convert MARKET to LIMIT
                        order_type = "LMT"
                    else:
                        # Convert SL-M to SL-LMT (keep trigger price)
                        order_type = "SL-LMT"

                    logger.info(
                        f"MPP Conversion Complete: Symbol={data['symbol']}, "
                        f"OrderType={original_type}->{order_type}, FinalPrice={protected_price}"
                    )
                else:
                    logger.warning(
                        f"MPP Warning: LTP is 0 or invalid for Symbol={data['symbol']}, "
                        f"Exchange={data['exchange']}. Proceeding with regular {original_type} order"
                    )
            else:
                logger.warning(
                    f"MPP Warning: No auth token available for Symbol={data['symbol']}. "
                    f"Cannot fetch quotes for MPP adjustment"
                )
        except Exception as e:
            logger.error(
                f"MPP Error: Failed to apply MPP for Symbol={data['symbol']}, "
                f"Exchange={data['exchange']}, Error={str(e)}. Proceeding with regular {original_type} order."
            )

        # A missing auth token, a zero LTP or a quote exception must NOT leave an
        # SL-M falling through as SL-MKT — that is the exact price type Shoonya
        # rejects for API orders, so the order would be dead on arrival. Unlike
        # MARKET (which has no reference price without a quote), an SL-M always
        # carries a trigger price, so derive the protective limit from the
        # trigger and still send SL-LMT. Same fallback as
        # broker/tradesmart/mapping/transform_data.py::_apply_mpp.
        if original_type == "SL-M" and order_type != "SL-LMT":
            order_type = "SL-LMT"
            trigger = float(data.get("trigger_price") or 0)
            if trigger > 0:
                # The caller's trigger price is already tick-valid, so it is the
                # safe limit. Add the MPP buffer on top only when the master
                # contract yields a tick size: with tick_size=None,
                # calculate_protected_price rounds to 2 decimals, which is
                # off-tick on a 0.05-tick instrument — that would trade a
                # rejection on price type for a rejection on price. No quote
                # means no tick size from the API, so read it from SymToken.
                price = str(trigger)
                try:
                    info = get_symbol_info(data["symbol"], data["exchange"])
                    tick_size = getattr(info, "tick_size", None)
                    if tick_size:
                        price = str(
                            calculate_protected_price(
                                price=trigger,
                                action=action,
                                symbol=data["symbol"],
                                instrument_type=get_instrument_type_from_symbol(data["symbol"]),
                                tick_size=tick_size,
                            )
                        )
                except Exception as e:
                    logger.error(
                        f"MPP Fallback Error: could not protect off the trigger for "
                        f"Symbol={data['symbol']}, Error={str(e)}. Using the trigger price as-is."
                    )
                    price = str(trigger)
            logger.warning(
                f"MPP Fallback: quote-based conversion did not run for Symbol={data['symbol']}; "
                f"sending SL-M->SL-LMT priced off the trigger ({trigger}) at {price}"
            )

    # Basic mapping
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
        "mkt_protection": "0",
        "ret": "DAY",
        "ordersource": "API",
    }

    # Log order data without sensitive fields
    safe_log = {k: v for k, v in transformed.items() if k not in ("uid", "actid")}
    logger.info(f"Transformed order data: {safe_log}")
    return transformed


def transform_modify_order_data(data, token):
    # Handle special characters in symbol
    symbol = data["symbol"]
    if symbol and "&" in symbol:
        symbol = symbol.replace("&", "%26")

    result = {
        "uid": data["apikey"],
        "exch": data["exchange"],
        "norenordno": data["orderid"],
        "prctyp": map_order_type(data["pricetype"]),
        "prc": str(data["price"]),
        "qty": str(data["quantity"]),
        "tsym": symbol,
        "ret": "DAY",
        "dscqty": str(data.get("disclosed_quantity") or 0),
    }

    # Only include trigger price for SL/SL-M orders
    # Sending trgprc=0 for LIMIT orders causes "Trigger price invalid - 0.00" error
    if data["pricetype"] in ["SL", "SL-M"]:
        result["trgprc"] = str(data.get("trigger_price") or 0)

    return result


def map_order_type(pricetype):
    """
    Maps the new pricetype to the existing order type.
    """
    order_type_mapping = {"MARKET": "MKT", "LIMIT": "LMT", "SL": "SL-LMT", "SL-M": "SL-MKT"}
    return order_type_mapping.get(pricetype, "MARKET")  # Default to MARKET if not found


def map_product_type(product):
    """
    Maps the new product type to the existing product type.
    """
    product_type_mapping = {
        "CNC": "C",
        "NRML": "M",
        "MIS": "I",
    }
    return product_type_mapping.get(product, "I")  # Default to DELIVERY if not found


def reverse_map_product_type(product):
    """
    Maps the new product type to the existing product type.
    """
    reverse_product_type_mapping = {
        "C": "CNC",
        "M": "NRML",
        "I": "MIS",
    }
    return reverse_product_type_mapping.get(product)
