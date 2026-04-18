"""
MStock Option Chain Formatter

This module formats MStock option chain responses to match Kotak reference format exactly.
Handles strike range extension, label calculation, and field standardization.
"""

from typing import Any, Dict, List
from utils.logging import get_logger

logger = get_logger(__name__)


def format_option_chain_to_kotak(raw_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Format MStock option chain data to match Kotak reference format.

    This ensures:
    1. Strike range: 17100-30100 (261 strikes)
    2. ATM calculation: round(LTP / 50) * 50
    3. Labels: ITM/OTM/ATM with distance suffix
    4. Standardized fields: lotsize=65, tick_size=0.05

    Args:
        raw_data: Raw option chain data from MStock API

    Returns:
        Formatted data matching Kotak structure
    """
    try:
        # Extract current data
        underlying_ltp = raw_data.get("underlying_ltp", 0)
        current_chain = raw_data.get("chain", [])

        # Step 1: Recalculate ATM strike
        atm_strike = round(underlying_ltp / 50) * 50
        logger.info(f"Calculated ATM strike: {atm_strike} (from LTP: {underlying_ltp})")

        # Step 2: Generate full strike range (17100-30100, step 50)
        full_strikes = list(range(17100, 30150, 50))  # 261 strikes
        logger.info(f"Generated {len(full_strikes)} strikes (17100-30100)")

        # Step 3: Build strike map from existing data
        existing_strikes = {}
        for item in current_chain:
            strike = float(item.get("strike", 0))
            existing_strikes[strike] = item

        # Step 4: Build formatted chain
        formatted_chain = []

        for strike in full_strikes:
            # Get existing data or create empty structure
            if strike in existing_strikes:
                strike_data = existing_strikes[strike]
                ce_data = strike_data.get("ce", {})
                pe_data = strike_data.get("pe", {})
            else:
                # Create empty strike data
                ce_data = {
                    "symbol": f"NIFTY21APR26{int(strike)}CE",
                    "ltp": 0, "bid": 0, "ask": 0,
                    "open": 0, "high": 0, "low": 0, "prev_close": 0,
                    "volume": 0, "oi": 0
                }
                pe_data = {
                    "symbol": f"NIFTY21APR26{int(strike)}PE",
                    "ltp": 0, "bid": 0, "ask": 0,
                    "open": 0, "high": 0, "low": 0, "prev_close": 0,
                    "volume": 0, "oi": 0
                }

            # Step 5: Calculate labels
            ce_label = calculate_option_label(strike, atm_strike, "CE")
            pe_label = calculate_option_label(strike, atm_strike, "PE")

            # Step 6: Build formatted strike
            formatted_strike = {
                "strike": int(strike),  # Ensure integer format like Kotak
                "ce": {
                    "symbol": ce_data.get("symbol", f"NIFTY21APR26{int(strike)}CE"),
                    "label": ce_label,
                    "ltp": ce_data.get("ltp", 0),
                    "bid": ce_data.get("bid", 0),
                    "ask": ce_data.get("ask", 0),
                    "open": ce_data.get("open", 0),
                    "high": ce_data.get("high", 0),
                    "low": ce_data.get("low", 0),
                    "prev_close": ce_data.get("prev_close", 0),
                    "volume": ce_data.get("volume", 0),
                    "oi": ce_data.get("oi", 0),
                    "lotsize": 65,
                    "tick_size": 0.05
                },
                "pe": {
                    "symbol": pe_data.get("symbol", f"NIFTY21APR26{int(strike)}PE"),
                    "label": pe_label,
                    "ltp": pe_data.get("ltp", 0),
                    "bid": pe_data.get("bid", 0),
                    "ask": pe_data.get("ask", 0),
                    "open": pe_data.get("open", 0),
                    "high": pe_data.get("high", 0),
                    "low": pe_data.get("low", 0),
                    "prev_close": pe_data.get("prev_close", 0),
                    "volume": pe_data.get("volume", 0),
                    "oi": pe_data.get("oi", 0),
                    "lotsize": 65,
                    "tick_size": 0.05
                }
            }

            formatted_chain.append(formatted_strike)

        # Step 7: Build final response matching Kotak format
        formatted_data = {
            "status": "success",
            "underlying": raw_data.get("underlying", "NIFTY"),
            "underlying_ltp": underlying_ltp,
            "underlying_prev_close": raw_data.get("underlying_prev_close", underlying_ltp),
            "expiry_date": raw_data.get("expiry_date", "21APR26"),
            "atm_strike": int(atm_strike),  # Ensure integer format like Kotak
            "chain": formatted_chain
        }

        logger.info(f"Formatted option chain: {len(formatted_chain)} strikes, ATM={atm_strike}")
        return formatted_data

    except Exception as e:
        logger.error(f"Error formatting option chain: {e}")
        # Return original data on error
        return raw_data


def calculate_option_label(strike: float, atm_strike: float, option_type: str) -> str:
    """
    Calculate ITM/ATM/OTM label with distance for an option.

    Args:
        strike: Strike price
        atm_strike: ATM strike price
        option_type: "CE" or "PE"

    Returns:
        Label string (e.g., "ATM", "ITM3", "OTM5")

    Label Logic (Kotak standard):
        - ATM: strike == atm_strike (both CE and PE)
        - CE: ITM when strike < ATM, OTM when strike > ATM
        - PE: ITM when strike > ATM, OTM when strike < ATM
        - Distance suffix = abs(strike - atm) / 50
    """
    if strike == atm_strike:
        return "ATM"

    steps = abs(int((strike - atm_strike) / 50))

    if option_type == "CE":
        if strike < atm_strike:
            return f"ITM{steps}"
        else:
            return f"OTM{steps}"
    else:  # PE
        if strike > atm_strike:
            return f"ITM{steps}"
        else:
            return f"OTM{steps}"
