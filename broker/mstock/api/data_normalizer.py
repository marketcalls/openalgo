"""
Data Normalizer for MStock Broker
Cleans up MStock API data to match standard OpenAlgo format.
"""

from typing import Any, Dict

from utils.logging import get_logger

logger = get_logger(__name__)


def normalize_quote_data(quote_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize MStock quote data to standard format.

    Fixes:
    1. Convert ltp=0.05 to ltp=0 when volume=0 and oi=0 (inactive strikes)
    2. Convert open/high/low=0.05 to 0 for same condition
    3. Ensure consistent zero values for inactive strikes

    Args:
        quote_data: Raw quote data from MStock API

    Returns:
        Normalized quote data
    """
    # Check if strike is inactive (no trading activity)
    volume = quote_data.get("volume", 0)
    oi = quote_data.get("oi", 0)
    is_inactive = (volume == 0 and oi == 0)

    # If inactive and values are at tick size (0.05), convert to 0
    if is_inactive:
        # LTP: Convert 0.05 to 0 for inactive strikes
        if quote_data.get("ltp") == 0.05:
            quote_data["ltp"] = 0
            logger.debug("Normalized inactive strike: ltp 0.05 -> 0")

        # Open: Convert 0.05 to 0 for inactive strikes
        if quote_data.get("open") == 0.05:
            quote_data["open"] = 0

        # High: Convert 0.05 to 0 for inactive strikes
        if quote_data.get("high") == 0.05:
            quote_data["high"] = 0

        # Low: Convert 0.05 to 0 for inactive strikes
        if quote_data.get("low") == 0.05:
            quote_data["low"] = 0

        # Prev close: Convert 0.05 to 0 for inactive strikes
        if quote_data.get("prev_close") == 0.05:
            quote_data["prev_close"] = 0

    return quote_data


def add_oi_disclaimer(response: Dict[str, Any]) -> Dict[str, Any]:
    """
    Add metadata disclaimer about OI data limitation.

    Args:
        response: Option chain response

    Returns:
        Response with metadata added
    """
    if "metadata" not in response:
        response["metadata"] = {}

    response["metadata"]["oi_note"] = (
        "OI data not available in MStock OHLC mode. "
        "Use WebSocket mode for real-time OI updates."
    )

    return response
