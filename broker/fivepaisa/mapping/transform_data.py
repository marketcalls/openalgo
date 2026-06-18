# Mapping OpenAlgo API Request https://openalgo.in/docs
# Mapping Angel Broking Parameters https://smartapi.angelbroking.com/docs/Orders

from database.token_db import get_br_symbol, get_symbol_info
from utils.logging import get_logger
from utils.mpp_slab import calculate_protected_price, get_instrument_type_from_symbol

logger = get_logger(__name__)


def transform_data(data, token, auth_token=None):
    """
    Transforms the new API request structure to the current expected structure.

    5Paisa does not accept plain market orders (Price=0 is rejected by RMS).
    For MARKET orders we apply Market Price Protection (MPP): fetch the LTP,
    add/subtract a slab-based buffer (rounded to tick size), and send a LIMIT
    order at that protected price. This mirrors the Flattrade implementation.
    """
    symbol = get_br_symbol(data["symbol"], data["exchange"])
    action = data["action"].upper()

    # Default price comes straight from the request (LIMIT / SL orders).
    price = float(data.get("price", "0"))

    # Apply Market Price Protection for MARKET orders
    if data.get("pricetype") == "MARKET":
        logger.info(
            f"MPP: MARKET order detected for Symbol={data['symbol']}, "
            f"Exchange={data['exchange']}, Action={action}"
        )
        try:
            if auth_token:
                # Lazy import to avoid a circular import at module load time
                from broker.fivepaisa.api.data import BrokerData

                broker_data = BrokerData(auth_token)
                quote_data = broker_data.get_quotes(data["symbol"], data["exchange"])
                ltp = float((quote_data or {}).get("ltp", 0))

                # 5Paisa quotes don't carry tick size; pull it from the symbol DB.
                tick_size = None
                sym_info = get_symbol_info(data["symbol"], data["exchange"])
                if sym_info is not None:
                    tick_size = getattr(sym_info, "tick_size", None)

                instrument_type = get_instrument_type_from_symbol(data["symbol"])
                logger.info(
                    f"MPP Quote: Symbol={data['symbol']}, LTP={ltp}, "
                    f"InstrumentType={instrument_type}, TickSize={tick_size}"
                )

                if ltp > 0:
                    protected_price = calculate_protected_price(
                        price=ltp,
                        action=action,
                        symbol=data["symbol"],
                        instrument_type=instrument_type,
                        tick_size=tick_size,
                    )
                    price = protected_price
                    logger.info(
                        f"MPP Conversion Complete: Symbol={data['symbol']}, "
                        f"OrderType=MARKET->LIMIT, FinalPrice={protected_price}"
                    )
                else:
                    logger.warning(
                        f"MPP Warning: LTP is 0 or invalid for Symbol={data['symbol']}, "
                        f"Exchange={data['exchange']}. Sending price={price} as-is."
                    )
            else:
                logger.warning(
                    f"MPP Warning: No auth token available for Symbol={data['symbol']}. "
                    f"Cannot fetch quote for MPP adjustment."
                )
        except Exception as e:
            logger.error(
                f"MPP Error: Failed to apply MPP for Symbol={data['symbol']}, "
                f"Exchange={data['exchange']}, Error={e}. Sending price={price} as-is."
            )

    # Basic mapping
    transformed = {
        "OrderType": map_action(action),
        "Exchange": map_exchange(data["exchange"]),
        "ExchangeType": map_exchange_type(data["exchange"]),
        "ScripCode": token,
        # "ScriData": symbol,
        # "iOrderValidity": "0",
        "Price": price,
        "Qty": int(data["quantity"]),
        "StopLossPrice": float(data.get("trigger_price", "0")),
        "DisQty": int(data.get("disclosed_quantity", "0")),
        "IsIntraday": True if data.get("product") == "MIS" else False,
        "AHPlaced": "N",  # AMO Order by default NO
        "RemoteOrderID": "OpenAlgo",
        # "AppSource": "7044"
    }

    return transformed


def transform_modify_order_data(data):
    # Handle empty trigger_price by providing a default of "0" and checking if it's empty
    trigger_price = data.get("trigger_price", "0")
    trigger_price = "0" if trigger_price == "" else trigger_price

    # Handle empty price
    price = data.get("price", "0")
    price = "0" if price == "" else price

    # FivePaisa requires a minimal set of fields for order modification per their documentation
    # Only include fields that are explicitly needed
    transformed = {
        "ExchOrderID": data.get("exchange_order_id", ""),  # The actual exchange order ID
        "Price": price,
        "Qty": data.get("quantity", "0"),
        "StopLossPrice": trigger_price,
        "DisQty": data.get("disclosed_quantity", "0"),
    }

    # Remove empty fields to keep the payload clean
    return {k: v for k, v in transformed.items() if v is not None and v != ""}


def map_action(action):
    """
    Maps the new action to the existing order type.
    """
    action_mapping = {"BUY": "B", "SELL": "S"}
    return action_mapping.get(action)


def map_exchange(exchange):
    """
    Maps the new exchange to the existing exchange
    """
    exchange_mapping = {
        "NSE": "N",
        "BSE": "B",
        "NFO": "N",
        "BFO": "B",
        "CDS": "N",
        "BCD": "B",
        "MCX": "M",
        "NSE_INDEX": "N",  # NSE indices use same exchange code as NSE
        "BSE_INDEX": "B",  # BSE indices use same exchange code as BSE
    }
    return exchange_mapping.get(exchange)


def map_exchange_type(exchange):
    """
    Maps the new exchange to the existing exchange type
    """
    exchange_mapping_type = {
        "NSE": "C",
        "BSE": "C",
        "NFO": "D",
        "BFO": "D",
        "CDS": "U",
        "BCD": "U",
        "MCX": "D",
        "NSE_INDEX": "C",  # Indices use Cash type in Fivepaisa scrip master
        "BSE_INDEX": "C",  # Indices use Cash type in Fivepaisa scrip master
    }
    return exchange_mapping_type.get(exchange)


def map_order_type(pricetype):
    """
    Maps the new pricetype to the existing order type.
    """
    order_type_mapping = {
        "MARKET": "MARKET",
        "LIMIT": "LIMIT",
        "SL": "STOPLOSS_LIMIT",
        "SL-M": "STOPLOSS_MARKET",
    }
    return order_type_mapping.get(pricetype, "MARKET")  # Default to MARKET if not found


def map_product_type(product):
    """
    Maps the new product type to the existing product type.
    """
    product_type_mapping = {
        "CNC": "D",
        "NRML": "D",
        "MIS": "I",
    }
    return product_type_mapping.get(product, "I")  # Default to DELIVERY if not found


def map_variety(pricetype):
    """
    Maps the pricetype to the existing order variety.
    """
    variety_mapping = {"MARKET": "NORMAL", "LIMIT": "NORMAL", "SL": "STOPLOSS", "SL-M": "STOPLOSS"}
    return variety_mapping.get(pricetype, "NORMAL")  # Default to DELIVERY if not found


# Function to map Exch and ExchType to exchange names with additional conditions
def reverse_map_exchange(Exch, ExchType):
    exchange_mapping = {
        ("N", "C"): "NSE",
        ("B", "C"): "BSE",
        ("N", "D"): "NFO",
        ("B", "D"): "BFO",
        ("N", "U"): "CDS",
        ("B", "U"): "BCD",
        ("M", "D"): "MCX",
        # Add other mappings as needed
    }

    return exchange_mapping.get((Exch, ExchType))


def reverse_map_product_type(product, exchange):
    """
    Maps the new product type to the existing product type based on the exchange.
    """
    if exchange in ["NSE", "BSE"]:
        reverse_product_type_mapping = {
            "D": "CNC",
            "I": "MIS",
        }
    else:
        reverse_product_type_mapping = {
            "D": "NRML",
            "I": "MIS",
        }

    return reverse_product_type_mapping.get(product)
