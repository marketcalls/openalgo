"""
Option Symbol Service

This service helps fetch option symbols based on underlying, expiry, strike offset, and option type.
It calculates ATM based on current LTP and returns the appropriate option symbol.

Two methods are supported:
1. NEW (RECOMMENDED): Uses actual strikes from database - more accurate, handles unequal strike intervals
2. OLD (LEGACY): Uses strike_int parameter - may construct non-existent symbols if strikes are unequal

Example Usage (NEW METHOD - Recommended):
    Input:
        underlying: "NIFTY"
        exchange: "NSE_INDEX"
        expiry_date: "28OCT25"
        strike_int: None  (or omit this parameter)
        offset: "ITM2"
        option_type: "CE"

    Output:
        symbol: "NIFTY28OCT2523500CE"  (based on actual 2nd ITM strike from database)

Example Usage (OLD METHOD - Legacy):
    Input:
        underlying: "NIFTY"
        exchange: "NSE_INDEX"
        expiry_date: "28OCT25"
        strike_int: 50
        offset: "ITM2"
        option_type: "CE"

    Output:
        symbol: "NIFTY28OCT2523500CE"  (if ATM is 23600, ITM2 = 23600 - 2*50 = 23500)
"""

import importlib
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from database.auth_db import get_auth_token_broker
from database.symbol import SymToken, db_session
from services.quotes_service import get_quotes
from utils.logging import get_logger

logger = get_logger(__name__)

# ============================================================================
# STRIKES CACHE - In-Memory Cache for Ultra-Fast Lookups
# ============================================================================
# Cache structure: {(base_symbol, expiry, option_type, exchange): [sorted_strikes]}
_STRIKES_CACHE: dict[tuple[str, str, str, str], list[float]] = {}
_CACHE_STATS = {"hits": 0, "misses": 0, "total_queries": 0}


def get_strikes_cache_stats() -> dict:
    """Get cache statistics for monitoring"""
    total = _CACHE_STATS["total_queries"]
    hit_rate = (_CACHE_STATS["hits"] / total * 100) if total > 0 else 0.0
    return {
        "hits": _CACHE_STATS["hits"],
        "misses": _CACHE_STATS["misses"],
        "total_queries": _CACHE_STATS["total_queries"],
        "hit_rate": f"{hit_rate:.2f}%",
        "cached_entries": len(_STRIKES_CACHE),
    }


def clear_strikes_cache():
    """Clear the strikes cache (call when master contracts are updated)"""
    global _STRIKES_CACHE, _CACHE_STATS
    _STRIKES_CACHE.clear()
    _CACHE_STATS = {"hits": 0, "misses": 0, "total_queries": 0}
    logger.info("Strikes cache cleared")


def parse_underlying_symbol(underlying: str) -> tuple[str, str | None]:
    """
    Parse underlying symbol to extract base symbol and expiry date if present.

    Args:
        underlying: Symbol like "NIFTY" or "NIFTY28OCT25FUT" or "RELIANCE31JAN25FUT"

    Returns:
        Tuple of (base_symbol, expiry_date)
        e.g., ("NIFTY", "28OCT25") or ("NIFTY", None)
    """
    # Pattern to match: SYMBOL + DDMMMYY + optional FUT
    # Examples: NIFTY28OCT25FUT, BANKNIFTY31JAN25FUT, RELIANCE28MAR24FUT
    pattern = r"^([A-Z]+)(\d{2}[A-Z]{3}\d{2})(?:FUT)?$"

    match = re.match(pattern, underlying.upper())
    if match:
        base_symbol = match.group(1)
        expiry_date = match.group(2)
        logger.info(
            f"Parsed underlying '{underlying}' -> base: '{base_symbol}', expiry: '{expiry_date}'"
        )
        return base_symbol, expiry_date

    # If no pattern match, treat the entire string as base symbol
    logger.info(f"Underlying '{underlying}' has no embedded expiry, using as-is")
    return underlying.upper(), None


def get_atm_strike(ltp: float, strike_int: int) -> float:
    """
    Calculate ATM strike price based on LTP and strike interval.

    Args:
        ltp: Last Traded Price of the underlying
        strike_int: Strike interval/difference

    Returns:
        ATM strike price rounded to nearest strike interval

    Example:
        LTP = 23587.50, strike_int = 50
        ATM = round(23587.50 / 50) * 50 = 23600
    """
    atm_strike = round(ltp / strike_int) * strike_int
    logger.info(f"Calculated ATM: LTP={ltp}, strike_int={strike_int}, ATM={atm_strike}")
    return atm_strike


def calculate_offset_strike(
    atm_strike: float, offset: str, strike_int: int, option_type: str
) -> float:
    """
    Calculate the target strike based on ATM and offset.

    Args:
        atm_strike: ATM strike price
        offset: Offset like "ATM", "ITM1", "ITM2", "OTM1", "OTM2"
        strike_int: Strike interval
        option_type: "CE" or "PE"

    Returns:
        Target strike price

    Logic:
        For CE (Call):
            - ITM: ATM - (N * strike_int)  [Lower strike]
            - OTM: ATM + (N * strike_int)  [Higher strike]

        For PE (Put):
            - ITM: ATM + (N * strike_int)  [Higher strike]
            - OTM: ATM - (N * strike_int)  [Lower strike]

    Example:
        ATM = 23600, strike_int = 50, option_type = "CE", offset = "ITM2"
        Target = 23600 - (2 * 50) = 23500
    """
    offset = offset.upper()
    option_type = option_type.upper()

    if offset == "ATM":
        target_strike = atm_strike
    elif offset.startswith("ITM"):
        # Extract the number (ITM1 -> 1, ITM2 -> 2)
        num = int(offset[3:])
        if option_type == "CE":
            # For Call, ITM means lower strike
            target_strike = atm_strike - (num * strike_int)
        else:  # PE
            # For Put, ITM means higher strike
            target_strike = atm_strike + (num * strike_int)
    elif offset.startswith("OTM"):
        # Extract the number (OTM1 -> 1, OTM2 -> 2)
        num = int(offset[3:])
        if option_type == "CE":
            # For Call, OTM means higher strike
            target_strike = atm_strike + (num * strike_int)
        else:  # PE
            # For Put, OTM means lower strike
            target_strike = atm_strike - (num * strike_int)
    else:
        logger.error(f"Invalid offset: {offset}")
        raise ValueError(f"Invalid offset: {offset}")

    logger.info(
        f"Calculated target strike: ATM={atm_strike}, offset={offset}, type={option_type}, target={target_strike}"
    )
    return target_strike


def construct_option_symbol(
    base_symbol: str, expiry_date: str, strike: float, option_type: str
) -> str:
    """
    Construct option symbol in OpenAlgo format.

    Format: [Base Symbol][Expiry Date][Strike Price][Option Type]

    Args:
        base_symbol: Base symbol like "NIFTY", "BANKNIFTY", "RELIANCE"
        expiry_date: Expiry in DDMMMYY format like "28OCT25"
        strike: Strike price like 23500 or 292.5
        option_type: "CE" or "PE"

    Returns:
        Option symbol like "NIFTY28OCT2523500CE" or "VEDL25APR24292.5CE"

    Examples:
        construct_option_symbol("NIFTY", "28MAR24", 20800, "CE") -> "NIFTY28MAR2420800CE"
        construct_option_symbol("VEDL", "25APR24", 292.5, "CE") -> "VEDL25APR24292.5CE"
    """
    # Format strike: Remove .0 if it's a whole number, otherwise keep decimal
    if strike == int(strike):
        strike_str = str(int(strike))
    else:
        strike_str = str(strike)

    option_symbol = f"{base_symbol}{expiry_date}{strike_str}{option_type.upper()}"
    logger.info(f"Constructed option symbol: {option_symbol}")
    return option_symbol


def find_option_in_database(option_symbol: str, exchange: str) -> dict[str, Any] | None:
    """
    Find the option symbol in the database and return its details.

    Args:
        option_symbol: Constructed option symbol like "NIFTY28OCT2523500CE"
        exchange: Exchange like "NFO", "BFO", "MCX", "CDS"

    Returns:
        Dictionary with symbol details or None if not found
    """
    try:
        # Query the database
        result = (
            db_session.query(SymToken)
            .filter(SymToken.symbol == option_symbol, SymToken.exchange == exchange)
            .first()
        )

        if result:
            logger.info(f"Found option in database: {option_symbol} on {exchange}")
            return {
                "symbol": result.symbol,
                "brsymbol": result.brsymbol,
                "name": result.name,
                "exchange": result.exchange,
                "brexchange": result.brexchange,
                "token": result.token,
                "expiry": result.expiry,
                "strike": result.strike,
                "lotsize": result.lotsize,
                "instrumenttype": result.instrumenttype,
                "tick_size": result.tick_size,
            }
        else:
            logger.warning(f"Option symbol not found in database: {option_symbol} on {exchange}")
            return None

    except Exception as e:
        logger.exception(f"Error querying database for option symbol: {e}")
        return None


def get_available_strikes(
    base_symbol: str, expiry_date: str, option_type: str, exchange: str
) -> list:
    """
    Fetch all available strikes from cache or database for a given underlying, expiry, and option type.
    Uses in-memory cache for ultra-fast lookups (O(1) instead of database query).

    Args:
        base_symbol: Base symbol like "NIFTY", "BANKNIFTY", "RELIANCE"
        expiry_date: Expiry in DDMMMYY format like "28OCT25"
        option_type: "CE" or "PE"
        exchange: Options exchange like "NFO", "BFO", "MCX", "CDS"

    Returns:
        Sorted list of available strike prices (ascending order)

    Example:
        get_available_strikes("NIFTY", "28OCT25", "CE", "NFO")
        -> [23000, 23050, 23100, 23150, 23200, ...]
    """
    global _STRIKES_CACHE, _CACHE_STATS

    try:
        # Normalize inputs for cache key
        cache_key = (
            base_symbol.upper(),
            expiry_date.upper(),
            option_type.upper(),
            exchange.upper(),
        )

        # Update query stats
        _CACHE_STATS["total_queries"] += 1

        # Check cache first (O(1) lookup)
        if cache_key in _STRIKES_CACHE:
            _CACHE_STATS["hits"] += 1
            strikes = _STRIKES_CACHE[cache_key]
            logger.debug(
                f"Cache HIT: {len(strikes)} strikes for {base_symbol} {expiry_date} {option_type}"
            )
            return strikes

        # Cache miss - query database
        _CACHE_STATS["misses"] += 1
        logger.debug(f"Cache MISS: Querying database for {base_symbol} {expiry_date} {option_type}")

        # Convert expiry from DDMMMYY to DD-MMM-YY format used in database
        # e.g., "28OCT25" -> "28-OCT-25"
        expiry_formatted = f"{expiry_date[:2]}-{expiry_date[2:5]}-{expiry_date[5:]}"

        # Construct symbol pattern: BASE + EXPIRY (without hyphens) + % wildcard
        # e.g., "NIFTY" + "18NOV25" + "%" = "NIFTY18NOV25%"
        expiry_no_hyphen = expiry_date.upper()  # Already in DDMMMYY format
        symbol_pattern = f"{base_symbol}{expiry_no_hyphen}%{option_type.upper()}"

        # Query database for all strikes matching the criteria
        # Using LIKE to match symbol pattern and filter by exchange and instrumenttype
        results = (
            db_session.query(SymToken.strike)
            .filter(
                SymToken.symbol.like(symbol_pattern),
                SymToken.expiry == expiry_formatted.upper(),
                SymToken.instrumenttype == option_type.upper(),
                SymToken.exchange == exchange.upper(),
            )
            .distinct()
            .order_by(SymToken.strike)
            .all()
        )

        # Extract strike values and filter out None
        strikes = [result.strike for result in results if result.strike is not None]

        # Store in cache for future requests
        _STRIKES_CACHE[cache_key] = strikes

        logger.info(
            f"Cached {len(strikes)} strikes for {base_symbol} {expiry_date} {option_type} on {exchange}"
        )
        if strikes:
            logger.info(f"Strike range: {strikes[0]} to {strikes[-1]}")

        return strikes

    except Exception as e:
        logger.exception(f"Error fetching available strikes: {e}")
        return []


def find_atm_strike_from_actual(ltp: float, available_strikes: list) -> float | None:
    """
    Find the ATM strike from actual available strikes based on LTP.
    ATM is the strike closest to the current LTP.

    Args:
        ltp: Last Traded Price of the underlying
        available_strikes: List of available strike prices (sorted)

    Returns:
        ATM strike price (closest to LTP) or None if no strikes available

    Example:
        LTP = 23587.50
        Available strikes = [23000, 23100, 23200, ..., 23500, 23600, 23700, ...]
        ATM = 23600 (closest to 23587.50)
    """
    if not available_strikes:
        logger.warning("No available strikes to find ATM")
        return None

    # Find the strike closest to LTP
    atm_strike = min(available_strikes, key=lambda x: abs(x - ltp))

    logger.info(f"Found ATM strike: {atm_strike} (LTP: {ltp})")
    return atm_strike


def calculate_offset_strike_from_actual(
    atm_strike: float, offset: str, option_type: str, available_strikes: list
) -> float | None:
    """
    Calculate the target strike based on ATM and offset using actual available strikes.

    Args:
        atm_strike: ATM strike price
        offset: Offset like "ATM", "ITM1", "ITM2", "OTM1", "OTM2"
        option_type: "CE" or "PE"
        available_strikes: List of available strike prices (sorted ascending)

    Returns:
        Target strike price or None if offset is out of range

    Logic:
        For CE (Call):
            - ITM: Lower strikes (traverse down the list from ATM)
            - OTM: Higher strikes (traverse up the list from ATM)

        For PE (Put):
            - ITM: Higher strikes (traverse up the list from ATM)
            - OTM: Lower strikes (traverse down the list from ATM)

    Example:
        ATM = 23600, available_strikes = [23000, 23100, ..., 23500, 23600, 23700, ...],
        option_type = "CE", offset = "ITM2"

        ATM index = position of 23600 in list
        For CE ITM2: Move 2 positions DOWN from ATM
        Result: 23400 (actual strike from database)
    """
    if not available_strikes or atm_strike not in available_strikes:
        logger.error(f"ATM strike {atm_strike} not found in available strikes")
        return None

    offset = offset.upper()
    option_type = option_type.upper()

    # Find the index of ATM in the sorted strikes list
    atm_index = available_strikes.index(atm_strike)

    if offset == "ATM":
        target_strike = atm_strike
        logger.info(f"Target strike (ATM): {target_strike}")
        return target_strike

    # Extract the offset number (ITM1 -> 1, OTM2 -> 2)
    if offset.startswith("ITM"):
        num = int(offset[3:])
        if option_type == "CE":
            # For Call, ITM means lower strikes (move backwards in list)
            target_index = atm_index - num
        else:  # PE
            # For Put, ITM means higher strikes (move forward in list)
            target_index = atm_index + num

    elif offset.startswith("OTM"):
        num = int(offset[3:])
        if option_type == "CE":
            # For Call, OTM means higher strikes (move forward in list)
            target_index = atm_index + num
        else:  # PE
            # For Put, OTM means lower strikes (move backwards in list)
            target_index = atm_index - num
    else:
        logger.error(f"Invalid offset: {offset}")
        return None

    # Check if target index is within bounds
    if target_index < 0 or target_index >= len(available_strikes):
        logger.error(
            f"Offset {offset} out of range. ATM index: {atm_index}, Target index: {target_index}, Available strikes: {len(available_strikes)}"
        )
        return None

    target_strike = available_strikes[target_index]
    logger.info(
        f"Target strike: {target_strike} (ATM: {atm_strike}, offset: {offset}, type: {option_type})"
    )
    return target_strike


def get_option_exchange(underlying_exchange: str) -> str:
    """
    Map underlying exchange to options exchange.

    Args:
        underlying_exchange: Exchange like "NSE_INDEX", "NSE", "BSE_INDEX", "BSE"

    Returns:
        Options exchange like "NFO", "BFO", "MCX", "CDS"

    Logic:
        NSE / NSE_INDEX -> NFO
        BSE / BSE_INDEX -> BFO
        MCX -> MCX (commodities have options on same exchange)
        CDS -> CDS (currency options on same exchange)
    """
    underlying_exchange = underlying_exchange.upper()

    if underlying_exchange in ["NSE", "NSE_INDEX"]:
        return "NFO"
    elif underlying_exchange in ["BSE", "BSE_INDEX"]:
        return "BFO"
    elif underlying_exchange == "MCX":
        return "MCX"
    elif underlying_exchange == "CDS":
        return "CDS"
    else:
        logger.warning(f"Unknown exchange mapping for: {underlying_exchange}, defaulting to NFO")
        return "NFO"


def get_option_symbol(
    underlying: str,
    exchange: str,
    expiry_date: str | None,
    strike_int: int | None,
    offset: str,
    option_type: str,
    api_key: str,
    underlying_ltp: float | None = None,
) -> tuple[bool, dict[str, Any], int]:
    """
    Main function to get option symbol based on underlying and parameters.

    Args:
        underlying: Underlying symbol (e.g., "NIFTY", "NIFTY28OCT25FUT", "RELIANCE")
        exchange: Exchange (e.g., "NSE_INDEX", "NSE", "NFO")
        expiry_date: Expiry date in DDMMMYY format (optional if embedded in underlying)
        strike_int: Strike interval (e.g., 50 for NIFTY). Optional - if not provided, will use actual strikes from database
        offset: Offset from ATM (e.g., "ATM", "ITM1", "OTM2")
        option_type: Option type ("CE" or "PE")
        api_key: OpenAlgo API key
        underlying_ltp: Optional pre-fetched LTP to avoid redundant quote requests

    Returns:
        Tuple of (success, response_data, status_code)
    """
    try:
        # Step 1: Parse underlying to extract base symbol and expiry
        base_symbol, embedded_expiry = parse_underlying_symbol(underlying)

        # Determine final expiry date
        final_expiry = embedded_expiry or expiry_date
        if not final_expiry:
            logger.error("No expiry date provided or found in underlying symbol")
            return (
                False,
                {
                    "status": "error",
                    "message": "Expiry date required. Provide via expiry_date parameter or embed in underlying (e.g., NIFTY28OCT25FUT).",
                },
                400,
            )

        # Step 2: Determine the quote exchange (where to fetch LTP from)
        # If exchange is already NFO/BFO, we need to get LTP from index/equity exchange
        quote_exchange = exchange
        if exchange.upper() in ["NFO", "BFO"]:
            # User passed options exchange, need to map back to index/equity
            if base_symbol in [
                "NIFTY",
                "BANKNIFTY",
                "FINNIFTY",
                "MIDCPNIFTY",
                "NIFTYNXT50",
                "INDIAVIX",
            ]:
                quote_exchange = "NSE_INDEX"
            elif base_symbol in ["SENSEX", "BANKEX", "SENSEX50"]:
                quote_exchange = "BSE_INDEX"
            else:
                # Assume it's an equity symbol
                quote_exchange = "NSE" if exchange.upper() == "NFO" else "BSE"

        # Construct the symbol to fetch quotes for
        # If underlying already has expiry embedded, use base symbol only
        # Otherwise, use underlying as-is
        if embedded_expiry:
            quote_symbol = base_symbol
        else:
            quote_symbol = underlying

        # Step 3: Get LTP of underlying (use provided LTP if available to avoid rate limits)
        if underlying_ltp is not None:
            ltp = underlying_ltp
            logger.info(f"Using provided LTP: {ltp} for {quote_symbol}")
        else:
            logger.info(f"Fetching LTP for: {quote_symbol} on {quote_exchange}")

            success, quote_response, status_code = get_quotes(
                symbol=quote_symbol, exchange=quote_exchange, api_key=api_key
            )

            if not success:
                logger.error(
                    f"Failed to fetch quotes: {quote_response.get('message', 'Unknown error')}"
                )
                return (
                    False,
                    {
                        "status": "error",
                        "message": f"Failed to fetch LTP for {quote_symbol}. {quote_response.get('message', 'Unknown error')}",
                    },
                    status_code,
                )

            # Extract LTP from quote response
            ltp = quote_response.get("data", {}).get("ltp")
            if ltp is None:
                logger.error(f"LTP not found in quote response for {quote_symbol}")
                return (
                    False,
                    {"status": "error", "message": f"Could not determine LTP for {quote_symbol}."},
                    500,
                )

            logger.info(f"Got LTP: {ltp} for {quote_symbol}")

        # Step 4: Map to options exchange
        options_exchange = get_option_exchange(quote_exchange)

        # Step 5: Determine calculation method based on strike_int parameter
        if strike_int is None:
            # NEW METHOD: Use actual strikes from database
            logger.info("Using actual strikes method (strike_int not provided)")

            # Fetch all available strikes for this underlying and expiry
            available_strikes = get_available_strikes(
                base_symbol, final_expiry, option_type, options_exchange
            )

            if not available_strikes:
                logger.error(
                    f"No strikes found in database for {base_symbol} {final_expiry} {option_type} on {options_exchange}"
                )
                return (
                    False,
                    {
                        "status": "error",
                        "message": f"No strikes found for {base_symbol} expiring {final_expiry}. Please check expiry date or update master contract.",
                    },
                    404,
                )

            # Find ATM from actual strikes
            atm_strike = find_atm_strike_from_actual(ltp, available_strikes)
            if atm_strike is None:
                logger.error("Failed to determine ATM strike from available strikes")
                return (
                    False,
                    {
                        "status": "error",
                        "message": "Failed to determine ATM strike from available strikes.",
                    },
                    500,
                )

            # Calculate target strike using actual strikes
            target_strike = calculate_offset_strike_from_actual(
                atm_strike, offset, option_type, available_strikes
            )
            if target_strike is None:
                logger.error(
                    f"Failed to calculate offset strike. Offset {offset} may be out of range."
                )
                return (
                    False,
                    {
                        "status": "error",
                        "message": f"Offset {offset} is out of range for available strikes. Please use a smaller offset.",
                    },
                    400,
                )

        else:
            # OLD METHOD: Use strike_int for backward compatibility
            logger.info(f"Using strike_int method (strike_int={strike_int})")

            # Calculate ATM strike using interval
            atm_strike = get_atm_strike(ltp, strike_int)

            # Calculate target strike based on offset
            target_strike = calculate_offset_strike(atm_strike, offset, strike_int, option_type)

        # Step 6: Construct option symbol
        option_symbol = construct_option_symbol(
            base_symbol, final_expiry, target_strike, option_type
        )

        # Step 7: Find option in database
        option_details = find_option_in_database(option_symbol, options_exchange)

        if not option_details:
            logger.warning(
                f"Option symbol {option_symbol} not found in database for {options_exchange}"
            )
            return (
                False,
                {
                    "status": "error",
                    "message": f"Option symbol {option_symbol} not found in {options_exchange}. Symbol may not exist or master contract needs update.",
                },
                404,
            )

        # Step 8: Get freeze quantity
        from database.qty_freeze_db import get_freeze_qty_for_option

        freeze_qty = get_freeze_qty_for_option(option_details["symbol"], option_details["exchange"])

        # Step 9: Return success response with simplified format
        return (
            True,
            {
                "status": "success",
                "symbol": option_details["symbol"],
                "exchange": option_details["exchange"],
                "lotsize": option_details["lotsize"],
                "tick_size": option_details["tick_size"],
                "freeze_qty": freeze_qty,
                "underlying_ltp": ltp,
            },
            200,
        )

    except ValueError as e:
        logger.error(f"Validation error in get_option_symbol: {e}")
        return False, {"status": "error", "message": str(e)}, 400
    except Exception as e:
        logger.exception(f"Error in get_option_symbol: {e}")
        return (
            False,
            {
                "status": "error",
                "message": f"An error occurred while processing option symbol request: {str(e)}",
            },
            500,
        )
