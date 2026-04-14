# Mapping OpenAlgo API Request https://openalgo.in/docs
# Mapping Kotak Neo API Parameters

from broker.kotak.api.data import BrokerData
from database.token_db import get_br_symbol, get_symbol_info
from utils.logging import get_logger
from utils.mpp_slab import calculate_protected_price, get_instrument_type_from_symbol

logger = get_logger(__name__)


def transform_data(data, token, auth_token=None):
    """
    Transforms the new API request structure to the current expected structure.
    ALL values must be strings for Kotak API.

    For market orders, fetches quotes and adjusts price using MPP (Market Price Protection):
    - EQ/FUT: Price < 100: 2%, 100-500: 1%, > 500: 0.5%
    - OPT (CE/PE): Price < 10: 5%, 10-100: 3%, 100-500: 2%, > 500: 1%

    Args:
        data: Order data dictionary
        token: Instrument token
        auth_token: Authentication token for fetching quotes (passed from order_api)
    """
    symbol = get_br_symbol(data["symbol"], data["exchange"])

    # Default values
    price = str(data.get("price", "0"))
    order_type = map_order_type(data["pricetype"])
    action = data["action"].upper()

    # Apply Market Price Protection for MARKET orders
    if data["pricetype"] == "MARKET":
        logger.info(
            f"MPP: MARKET order detected for Symbol={data['symbol']}, Exchange={data['exchange']}, Action={action}"
        )
        try:
            if auth_token:
                # Create BrokerData instance to fetch quotes
                broker_data = BrokerData(auth_token)

                # Fetch quotes for the symbol
                quote_data = broker_data.get_quotes(data["symbol"], data["exchange"])
                logger.info(
                    f"MPP Quote Response: Symbol={data['symbol']}, Exchange={data['exchange']}, "
                    f"LTP={quote_data.get('ltp') if quote_data else None}"
                )

                if quote_data:
                    # Get instrument type from symbol
                    instrument_type = get_instrument_type_from_symbol(data["symbol"])

                    # Get tick_size from master contract database
                    tick_size = None
                    symbol_info = get_symbol_info(data["symbol"], data["exchange"])
                    if symbol_info and symbol_info.tick_size:
                        tick_size = symbol_info.tick_size
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

                        # Convert order type from MARKET to LIMIT
                        order_type = "L"
                        logger.info(
                            f"MPP Conversion Complete: Symbol={data['symbol']}, OrderType=MKT->L, "
                            f"FinalPrice={protected_price}"
                        )
                    else:
                        logger.warning(
                            f"MPP Warning: LTP is 0 or invalid for Symbol={data['symbol']}, "
                            f"Exchange={data['exchange']}. Proceeding with regular market order"
                        )
                else:
                    logger.warning(
                        f"MPP Warning: No quote data for Symbol={data['symbol']}. "
                        f"Proceeding with regular market order"
                    )
            else:
                logger.warning(
                    f"MPP Warning: No auth token available for Symbol={data['symbol']}. "
                    f"Cannot fetch quotes for MPP adjustment"
                )
        except Exception as e:
            logger.error(
                f"MPP Error: Failed to apply MPP for Symbol={data['symbol']}, "
                f"Exchange={data['exchange']}, Error={str(e)}. Proceeding with regular market order."
            )

    # Apply Market Price Protection for SL-M orders (convert SL-M to SL with protected price)
    elif data["pricetype"] == "SL-M":
        try:
            trigger_price = float(data.get("trigger_price", 0))
        except (TypeError, ValueError):
            trigger_price = 0.0
            logger.warning(
                f"MPP Warning: Invalid trigger_price for SL-M Symbol={data['symbol']}. "
                f"Proceeding with SL-M order."
            )
        logger.info(
            f"MPP: SL-M order detected for Symbol={data['symbol']}, Exchange={data['exchange']}, "
            f"Action={action}, TriggerPrice={trigger_price}"
        )
        if trigger_price > 0:
            try:
                # Get instrument type and tick_size from master contract
                instrument_type = get_instrument_type_from_symbol(data["symbol"])
                tick_size = None
                symbol_info = get_symbol_info(data["symbol"], data["exchange"])
                if symbol_info and symbol_info.tick_size:
                    tick_size = symbol_info.tick_size
                logger.info(
                    f"MPP Symbol Info: InstrumentType={instrument_type}, TickSize={tick_size}"
                )

                # Calculate protected price based on trigger price
                protected_price = calculate_protected_price(
                    price=trigger_price,
                    action=action,
                    symbol=data["symbol"],
                    instrument_type=instrument_type,
                    tick_size=tick_size,
                )
                price = str(protected_price)

                # Convert SL-M to SL (stop loss limit)
                order_type = "SL"
                logger.info(
                    f"MPP Conversion Complete: Symbol={data['symbol']}, OrderType=SL-M->SL, "
                    f"TriggerPrice={trigger_price}, LimitPrice={protected_price}"
                )
            except Exception as e:
                logger.error(
                    f"MPP Error: Failed to apply MPP for SL-M Symbol={data['symbol']}, "
                    f"Exchange={data['exchange']}, Error={str(e)}. Proceeding with SL-M order."
                )
        else:
            logger.warning(
                f"MPP Warning: Trigger price is 0 for SL-M Symbol={data['symbol']}. "
                f"Proceeding with SL-M order."
            )

    # Basic mapping - ALL values must be strings for Kotak API
    transformed = {
        "am": "NO",
        "dq": str(data.get("disclosed_quantity", "0")),
        "bc": "1",
        "es": reverse_map_exchange(data["exchange"]),
        "mp": "0",
        "pc": data.get("product", "MIS"),
        "pf": "N",
        "pr": price,
        "pt": order_type,
        "qt": str(data["quantity"]),
        "rt": "DAY",
        "tp": str(data.get("trigger_price", "0")),
        "ts": symbol,
        "tt": "B" if action == "BUY" else ("S" if action == "SELL" else "None"),
    }

    # Log order data
    logger.info(f"Transformed order data: {transformed}")
    return transformed


def transform_modify_order_data(data, token):
    symbol = get_br_symbol(data["symbol"], data["exchange"])
    # Basic mapping - ALL values must be strings for Kotak API
    transformed = {
        "tk": str(token),
        "dq": str(data.get("disclosed_quantity", "0")),
        "es": reverse_map_exchange(data["exchange"]),
        "mp": "0",
        "dd": "NA",
        "vd": "DAY",
        "pc": data.get("product", "MIS"),
        "pr": str(data.get("price", "0")),
        "pt": map_order_type(data["pricetype"]),
        "qt": str(data["quantity"]),
        "tp": str(data.get("trigger_price", "0")),
        "ts": symbol,
        "no": str(data["orderid"]),
        "tt": "B" if data["action"] == "BUY" else ("S" if data["action"] == "SELL" else "None"),
    }
    return transformed


def map_order_type(pricetype):
    """
    Maps the new pricetype to the existing order type.
    """
    order_type_mapping = {"MARKET": "MKT", "LIMIT": "L", "SL": "SL", "SL-M": "SL-M"}
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
    return product_type_mapping.get(product)  # Default to DELIVERY if not found


def map_variety(pricetype):
    """
    Maps the pricetype to the existing order variety.
    """
    variety_mapping = {"MARKET": "NORMAL", "LIMIT": "NORMAL", "SL": "STOPLOSS", "SL-M": "STOPLOSS"}
    return variety_mapping.get(pricetype, "NORMAL")  # Default to DELIVERY if not found


def map_exchange(brexchange):
    """
    Maps the Broker Exchange to the OpenAlgo Exchange.
    """

    exchange_mapping = {
        "nse_cm": "NSE",
        "bse_cm": "BSE",
        "cde_fo": "CDS",
        "nse_fo": "NFO",
        "bse_fo": "BFO",
        "bcs_fo": "BCD",
        "mcx_fo": "MCX",
    }
    return exchange_mapping.get(brexchange)


def reverse_map_exchange(exchange):
    """
    Maps the Broker Exchange to the OpenAlgo Exchange.
    """

    exchange_mapping = {
        "NSE": "nse_cm",
        "BSE": "bse_cm",
        "CDS": "cde_fo",
        "NFO": "nse_fo",
        "BFO": "bse_fo",
        "BCD": "bcs_fo",
        "MCX": "mcx_fo",
    }
    return exchange_mapping.get(exchange)


def reverse_map_product_type(product):
    """
    Maps the new product type to the existing product type.
    """
    reverse_product_type_mapping = {
        "CNC": "CNC",
        "NRML": "NRML",
        "MIS": "MIS",
    }
    return reverse_product_type_mapping.get(product)
