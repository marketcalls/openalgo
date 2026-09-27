# Mapping OpenAlgo API Request https://openalgo.in/docs
# Mapping Angel Broking Parameters https://smartapi.angelbroking.com/docs/Orders

import math
from decimal import Decimal

from database.token_db import get_br_symbol, get_symbol_info
from utils.logging import get_logger
from utils.mpp_slab import (
    calculate_protected_price,
    get_instrument_type_from_symbol,
    get_mpp_percentage,
)

logger = get_logger(__name__)


def _tick_decimals(tick: float) -> int:
    """Number of decimal places implied by a tick size (0.05 -> 2, 0.0025 -> 4)."""
    return max(0, -Decimal(str(tick)).as_tuple().exponent)


def _snap_to_tick(value: float, tick: float, direction: str) -> float:
    """Snap ``value`` to a multiple of ``tick``.

    ``"floor"`` rounds down and ``"ceil"`` rounds up, so the protective limit
    stays strictly on the required side of the trigger after snapping —
    nearest-tick rounding could land it back on the trigger.
    """
    ratio = round(value / tick, 6)  # tame float noise before the floor/ceil
    k = math.floor(ratio) if direction == "floor" else math.ceil(ratio)
    return round(k * tick, _tick_decimals(tick))


def _slm_protected_price(symbol, exchange, action, trigger_price):
    """
    Derive a protective stop-limit price for an SL-M order from its trigger.

    5Paisa rejects every order it sees as "at market" when it comes from an API
    key, with RMS reason "Market order with Algo Id not allowed" (verified live
    2026-08-07 on NSE cash; the same string Kotak returns). 5Paisa has no
    order-type field — `Price = 0` IS the market flag, and the order book echoes
    it back as `AtMarket = "Y"` — so an SL-M sent as Price 0 + StopLossPrice is
    rejected outright.

    Plain MARKET orders already dodge this: transform_data() converts them to an
    MPP-protected LIMIT off the LTP. SL-M skipped that path entirely. Give it the
    same treatment, but anchored on the TRIGGER rather than the LTP (the LTP is
    irrelevant to an order that rests until the trigger fires): offset MPP%
    beyond the trigger in the fill direction — SELL below it, BUY above it — so
    the stop still fills once triggered. Same shape as the Dhan #1647 fix and the
    Kotak SL-M conversion.

    NSE also requires an SL SELL limit at or below its trigger (and BUY at or
    above), so the beyond-trigger direction is what the exchange wants anyway.

    The limit is snapped to the instrument tick away from the trigger (SELL
    floors, BUY ceils) and forced at least one tick past it, so rounding can
    never put it back onto the trigger or collapse it to zero on a low-priced
    scrip. Fails closed when the tick size cannot be resolved rather than
    guessing 2 decimals, which 5Paisa would reject on a tick-size check.
    """
    instrument_type = get_instrument_type_from_symbol(symbol)

    symbol_info = get_symbol_info(symbol, exchange)
    try:
        tick_size = float(getattr(symbol_info, "tick_size", None)) if symbol_info else 0.0
    except (TypeError, ValueError):
        tick_size = 0.0
    if not math.isfinite(tick_size) or tick_size <= 0:
        raise ValueError(
            f"Cannot resolve tick size from DB for {symbol}/{exchange}; required to "
            f"build a valid SL-M protective limit price"
        )

    pct = (get_mpp_percentage(trigger_price, instrument_type) or 0) / 100.0

    if action.upper() == "SELL":
        # Strictly BELOW the trigger, at least one tick away, tick-aligned.
        raw = min(trigger_price * (1 - pct), trigger_price - tick_size)
        limit = _snap_to_tick(raw, tick_size, "floor")
        if limit <= 0:
            raise ValueError(
                f"SL-M SELL trigger {trigger_price} for {symbol}/{exchange} is too low "
                f"to derive a positive protective limit at tick {tick_size}"
            )
    else:
        # Strictly ABOVE the trigger, at least one tick away, tick-aligned.
        raw = max(trigger_price * (1 + pct), trigger_price + tick_size)
        limit = _snap_to_tick(raw, tick_size, "ceil")

    return limit


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

    # SL-M carries no price of its own, so it would go out as Price=0 — which
    # 5Paisa reads as "at market" and rejects for API keys ("Market order with
    # Algo Id not allowed"). Convert it to a stop-LIMIT priced just beyond the
    # trigger. Unlike the MARKET branch above this needs no quote, so it works
    # even without an auth token.
    trigger_price = float(data.get("trigger_price", "0") or 0)
    if data.get("pricetype") == "SL-M" and trigger_price > 0:
        try:
            price = _slm_protected_price(
                data["symbol"], data["exchange"], action, trigger_price
            )
            logger.info(
                f"MPP Conversion Complete: Symbol={data['symbol']}, "
                f"OrderType=SL-M->SL, Trigger={trigger_price}, FinalPrice={price}"
            )
        except Exception as e:
            # Fail loudly rather than silently sending Price=0, which 5Paisa
            # would reject anyway — the caller sees the reason instead of a
            # bare RMS rejection.
            logger.error(
                f"MPP Error: Cannot build SL-M protective limit for "
                f"Symbol={data['symbol']}, Exchange={data['exchange']}, "
                f"Trigger={trigger_price}: {e}"
            )
            raise

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
