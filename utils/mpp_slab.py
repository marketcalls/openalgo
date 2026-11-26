# Market Price Protection (MPP) Slab Configuration
# Reference: https://support.zerodha.com/category/trading-and-markets/charts-and-orders/order/articles/market-price-protection-on-the-order-window
#
# This module provides centralized Market Price Protection functionality for OpenAlgo.
# When brokers stop supporting market orders, this converts MARKET orders to LIMIT orders
# with a price buffer based on configurable protection percentages.

import math
import re

from utils.logging import get_logger

logger = get_logger(__name__)

# MPP Slabs for Equity and Futures (EQ and FUT)
# Based on Indian exchange regulations
# Format: (max_price, protection_percentage)
EQ_FUT_MPP_SLABS = [
    (100, 2.0),  # Price < 100: 2% protection
    (500, 1.0),  # Price 100-500: 1% protection
    (float("inf"), 0.5),  # Price > 500: 0.5% protection
]

# MPP Slabs for Options (CE and PE)
# Options have different slabs due to higher volatility
OPT_MPP_SLABS = [
    (10, 5.0),  # Price < 10: 5% protection
    (100, 3.0),  # Price 10-100: 3% protection
    (500, 2.0),  # Price 100-500: 2% protection
    (float("inf"), 1.0),  # Price > 500: 1% protection
]

# Instrument types that use Options slabs
OPTIONS_INSTRUMENT_TYPES = ["CE", "PE"]

# Cash-market exchanges: everything traded there is equity, whatever the
# symbol ends with.
CASH_EXCHANGES = {"NSE", "BSE"}

# OpenAlgo derivative symbols always carry the expiry (DDMMMYY) before the
# suffix: options are [Base][Expiry][Strike][CE/PE] (NIFTY28MAR2420800CE,
# VEDL25APR24292.5CE) and futures [Base][Expiry]FUT (BANKNIFTY24APR24FUT).
# Equity symbols never do, so a cash symbol that merely ends in CE or PE
# (RELIANCE, BAJFINANCE, PRINCEPIPE, REDTAPE) is not mistaken for an option.
_OPTION_SYMBOL_RE = re.compile(r"^.+\d{2}[A-Z]{3}\d{2}\d+(?:\.\d+)?(CE|PE)$")
_FUTURE_SYMBOL_RE = re.compile(r"^.+\d{2}[A-Z]{3}\d{2}FUT$")


def is_option_instrument_type(instrument_type: str | None) -> bool:
    """
    Whether an instrument type uses the options slabs.

    Accepts OpenAlgo's 'CE'/'PE' as well as the master contract types some
    brokers store in SymToken.instrumenttype ('OPTIDX', 'OPTSTK', 'OPTFUT',
    'OPTCUR', ...).
    """
    if not instrument_type:
        return False
    instrument_type = str(instrument_type).upper()
    return instrument_type in OPTIONS_INSTRUMENT_TYPES or instrument_type.startswith("OPT")


def get_instrument_type_from_symbol(symbol: str, exchange: str | None = None) -> str:
    """
    Determine instrument type from an OpenAlgo symbol.

    An option needs the full option shape (expiry, strike, CE/PE) and a future
    the expiry before FUT; anything else is equity. The suffix alone is not
    enough: RELIANCE ends in CE and is a stock.

    Args:
        symbol: OpenAlgo trading symbol (e.g., 'RELIANCE', 'NIFTY24DEC2425000CE',
            'NIFTY24DEC24FUT')
        exchange: Optional OpenAlgo exchange. NSE and BSE are always 'EQ'.

    Returns:
        str: 'CE', 'PE', 'FUT', or 'EQ'
    """
    if exchange and str(exchange).upper() in CASH_EXCHANGES:
        return "EQ"
    symbol_upper = (symbol or "").strip().upper()
    option_match = _OPTION_SYMBOL_RE.match(symbol_upper)
    if option_match:
        return option_match.group(1)
    if _FUTURE_SYMBOL_RE.match(symbol_upper):
        return "FUT"
    return "EQ"


def get_mpp_slabs(instrument_type: str) -> list:
    """
    Get the appropriate MPP slabs based on instrument type.

    Args:
        instrument_type: 'EQ', 'FUT', 'CE', 'PE', or a master contract type
            such as 'OPTIDX' / 'OPTSTK' / 'FUTSTK'

    Returns:
        list: The MPP slabs to use
    """
    if is_option_instrument_type(instrument_type):
        return OPT_MPP_SLABS
    else:
        return EQ_FUT_MPP_SLABS


def get_mpp_percentage(price: float, instrument_type: str = "EQ") -> float:
    """
    Get the Market Price Protection percentage for a given price and instrument type.

    Args:
        price: The current market price (LTP)
        instrument_type: 'EQ', 'FUT', 'CE', or 'PE'

    Returns:
        float: The protection percentage to apply

    Raises:
        TypeError: If price is not a number (e.g. None, a string, or a bool).
        ValueError: If price is NaN or infinite (no slab can match it).

    Example:
        >>> get_mpp_percentage(50, 'EQ')   # Returns 2.0 (for EQ/FUT price < 100)
        >>> get_mpp_percentage(50, 'CE')   # Returns 3.0 (for OPT price 10-100)
        >>> get_mpp_percentage(5, 'PE')    # Returns 5.0 (for OPT price < 10)
    """
    if isinstance(price, bool) or not isinstance(price, (int, float)):
        raise TypeError(f"MPP price must be a number, got {type(price).__name__}")
    if not math.isfinite(price):
        raise ValueError(f"MPP price must be finite, got {price!r}")
    slabs = get_mpp_slabs(instrument_type)
    slab_type = "OPT" if is_option_instrument_type(instrument_type) else "EQ/FUT"

    # Find the appropriate slab for the price
    for max_price, percentage in slabs:
        if price < max_price:
            slab_desc = f"< {max_price}" if max_price != float("inf") else "> 500"
            logger.info(
                f"MPP Slab Lookup: InstrumentType={instrument_type}, Price={price}, "
                f"Slab={slab_desc}, Protection={percentage}%, SlabType={slab_type}"
            )
            return percentage


def round_to_tick_size(price: float, tick_size: float = None) -> float:
    """
    Round price to the nearest valid tick size.

    Args:
        price: The calculated price
        tick_size: The tick size for the instrument (from database)

    Returns:
        float: Price rounded to nearest tick size, or 2 decimal places if no tick size

    Example:
        >>> round_to_tick_size(102.0111, 0.05)  # Returns 102.0
        >>> round_to_tick_size(102.0111, 0.01)  # Returns 102.01
        >>> round_to_tick_size(102.0111, None)  # Returns 102.01 (2 decimal places)
    """
    if tick_size is None or tick_size <= 0:
        # No tick size available, just round to 2 decimal places
        return round(price, 2)

    # Round to nearest tick size
    rounded = round(price / tick_size) * tick_size

    # Ensure 2 decimal places for display
    return round(rounded, 2)


def calculate_protected_price(
    price: float,
    action: str,
    symbol: str = None,
    instrument_type: str = None,
    tick_size: float = None,
    custom_percentage: float = None,
    exchange: str = None,
) -> float:
    """
    Calculate the protected limit price for a market order with tick size rounding.

    Args:
        price: The current market price (LTP)
        action: Order action - 'BUY' or 'SELL'
        symbol: Trading symbol (used to determine instrument type if not provided)
        instrument_type: 'EQ', 'FUT', 'CE', or 'PE' (if None, derived from symbol)
        tick_size: Tick size for price rounding (from database)
        custom_percentage: Optional custom percentage to override slab-based calculation
        exchange: Optional OpenAlgo exchange, used with symbol to derive the type

    Returns:
        float: The adjusted limit price with protection, rounded to tick size

    Example:
        >>> calculate_protected_price(100, 'BUY', instrument_type='EQ')  # ~102.0 (100 + 2%)
        >>> calculate_protected_price(5, 'BUY', instrument_type='CE')    # ~5.25 (5 + 5%)
    """
    # Determine instrument type from symbol if not provided
    if instrument_type is None and symbol:
        instrument_type = get_instrument_type_from_symbol(symbol, exchange)
    elif instrument_type is None:
        instrument_type = "EQ"  # Default to EQ

    # Get protection percentage
    if custom_percentage is not None:
        percentage = custom_percentage
        logger.info(f"MPP: Using custom percentage: {percentage}%")
    else:
        percentage = get_mpp_percentage(price, instrument_type)

    multiplier = percentage / 100
    price_adjustment = round(price * multiplier, 2)

    if action.upper() == "BUY":
        # For BUY orders, add protection percentage to ensure execution
        protected_price = price * (1 + multiplier)
        adjustment_type = "+"
    else:
        # For SELL orders, subtract protection percentage to ensure execution
        protected_price = price * (1 - multiplier)
        adjustment_type = "-"

    # Round to tick size
    protected_price = round_to_tick_size(protected_price, tick_size)

    logger.info(
        f"MPP Calculation: Symbol={symbol or 'N/A'}, InstrumentType={instrument_type}, "
        f"Action={action.upper()}, BasePrice={price}, Protection={percentage}%, "
        f"Adjustment={adjustment_type}{price_adjustment}, TickSize={tick_size}, "
        f"ProtectedPrice={protected_price}"
    )

    return protected_price


def get_mpp_info(
    price: float,
    symbol: str = None,
    instrument_type: str = None,
    tick_size: float = None,
    exchange: str = None,
) -> dict:
    """
    Get detailed MPP information for a given price.

    Args:
        price: The current market price
        symbol: Trading symbol
        instrument_type: 'EQ', 'FUT', 'CE', or 'PE'
        tick_size: Tick size for rounding (from database)
        exchange: Optional OpenAlgo exchange, used with symbol to derive the type

    Returns:
        dict: Dictionary with MPP details
    """
    if instrument_type is None and symbol:
        instrument_type = get_instrument_type_from_symbol(symbol, exchange)
    elif instrument_type is None:
        instrument_type = "EQ"

    percentage = get_mpp_percentage(price, instrument_type)
    slab_type = "OPT" if is_option_instrument_type(instrument_type) else "EQ/FUT"

    return {
        "base_price": price,
        "symbol": symbol,
        "instrument_type": instrument_type,
        "slab_type": slab_type,
        "percentage": percentage,
        "tick_size": tick_size,
        "buy_price": calculate_protected_price(price, "BUY", symbol, instrument_type, tick_size),
        "sell_price": calculate_protected_price(price, "SELL", symbol, instrument_type, tick_size),
    }


def log_mpp_slabs():
    """Log all MPP slabs for reference."""
    logger.info("=" * 50)
    logger.info("MPP Slabs for EQ and FUT (Equity & Futures):")
    logger.info("-" * 50)
    prev_max = 0
    for max_price, percentage in EQ_FUT_MPP_SLABS:
        if max_price == float("inf"):
            logger.info(f"  Price >= {prev_max}: {percentage}%")
        else:
            logger.info(f"  Price < {max_price}: {percentage}%")
        prev_max = max_price

    logger.info("=" * 50)
    logger.info("MPP Slabs for OPT (Options - CE/PE):")
    logger.info("-" * 50)
    prev_max = 0
    for max_price, percentage in OPT_MPP_SLABS:
        if max_price == float("inf"):
            logger.info(f"  Price >= {prev_max}: {percentage}%")
        else:
            logger.info(f"  Price < {max_price}: {percentage}%")
        prev_max = max_price
    logger.info("=" * 50)
