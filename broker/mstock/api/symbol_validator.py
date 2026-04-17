"""
Symbol Validator for MStock Broker
Validates symbols and provides suggestions for common typos.
"""

from difflib import get_close_matches
from typing import Optional

from database.token_db import get_token
from utils.logging import get_logger

logger = get_logger(__name__)

# Common index symbols by exchange
KNOWN_INDICES = {
    "NSE_INDEX": [
        "NIFTY",
        "BANKNIFTY",
        "FINNIFTY",
        "MIDCPNIFTY",
        "NIFTYNXT50",
        "INDIAVIX",
    ],
    "BSE_INDEX": [
        "SENSEX",
        "BANKEX",
        "SENSEX50",
    ],
}


def validate_symbol(symbol: str, exchange: str) -> tuple[bool, Optional[str], Optional[str]]:
    """
    Validate if a symbol exists and suggest alternatives if not found.

    Args:
        symbol: Trading symbol to validate
        exchange: Exchange code (NSE_INDEX, BSE_INDEX, NSE, BSE, NFO, BFO, etc.)

    Returns:
        Tuple of (is_valid, error_message, suggestion)
        - is_valid: True if symbol exists
        - error_message: Error message if symbol not found
        - suggestion: Suggested symbol if close match found
    """
    # Check if token exists
    token = get_token(symbol, exchange)

    if token:
        return True, None, None

    # Symbol not found - try to suggest alternatives
    suggestion = None
    error_msg = f"Symbol '{symbol}' not found for exchange '{exchange}'"

    # For index exchanges, check against known indices
    if exchange in KNOWN_INDICES:
        known_symbols = KNOWN_INDICES[exchange]
        close_matches = get_close_matches(symbol.upper(), known_symbols, n=1, cutoff=0.6)

        if close_matches:
            suggestion = close_matches[0]
            error_msg = (
                f"Symbol '{symbol}' not found for exchange '{exchange}'. "
                f"Did you mean '{suggestion}'?"
            )
        else:
            valid_symbols = ", ".join(known_symbols)
            error_msg = (
                f"Symbol '{symbol}' not found for exchange '{exchange}'. "
                f"Valid {exchange} symbols: {valid_symbols}"
            )
    else:
        error_msg = (
            f"Symbol '{symbol}' not found for exchange '{exchange}'. "
            f"Please verify the symbol name and ensure master contracts are downloaded."
        )

    logger.warning(error_msg)
    return False, error_msg, suggestion
