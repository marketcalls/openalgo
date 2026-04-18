"""
Option Chain Normalizer

This module provides normalization functions to ensure option chain data
matches the Kotak reference format with complete strike ranges and correct labels.
"""

from typing import Any, Dict, List
from utils.logging import get_logger

logger = get_logger(__name__)


def calculate_atm_strike(underlying_ltp: float, strike_interval: int = 50) -> float:
    """
    Calculate ATM strike by rounding LTP to nearest strike interval.

    Args:
        underlying_ltp: Current LTP of underlying
        strike_interval: Strike interval (default 50 for NIFTY)

    Returns:
        ATM strike price
    """
    return round(underlying_ltp / strike_interval) * strike_interval


def calculate_option_label(strike: float, atm_strike: float, option_type: str) -> str:
    """
    Calculate ITM/ATM/OTM label with distance for an option.

    Args:
        strike: Strike price
        atm_strike: ATM strike price
        option_type: "CE" or "PE"

    Returns:
        Label string (e.g., "ATM", "ITM3", "OTM5")

    Label Logic:
        - ATM: strike == atm_strike (both CE and PE)
        - CE: ITM when strike < ATM, OTM when strike > ATM
        - PE: ITM when strike > ATM, OTM when strike < ATM
    """
    if strike == atm_strike:
        return "ATM"

    steps = abs(int((strike - atm_strike) / 50))

    if option_type == "CE":
        return f"ITM{steps}" if strike < atm_strike else f"OTM{steps}"
    else:  # PE
        return f"ITM{steps}" if strike > atm_strike else f"OTM{steps}"


def generate_full_strike_range(
    start_strike: int = 17100,
    end_strike: int = 30100,
    strike_interval: int = 50
) -> List[float]:
    """
    Generate complete strike range for NIFTY options.

    Args:
        start_strike: Starting strike (default 17100)
        end_strike: Ending strike (default 30100)
        strike_interval: Strike interval (default 50)

    Returns:
        List of strike prices
    """
    return [float(strike) for strike in range(start_strike, end_strike + strike_interval, strike_interval)]


def normalize_option_chain_data(
    chain_data: Dict[str, Any],
    extend_strike_range: bool = True,
    recalculate_atm: bool = True,
    fix_labels: bool = True
) -> Dict[str, Any]:
    """
    Normalize option chain data to match Kotak reference format.

    This function:
    1. Recalculates ATM strike from underlying LTP
    2. Extends strike range to 17100-30100 (261 strikes)
    3. Fixes CE/PE labels according to ITM/OTM rules
    4. Standardizes lotsize and tick_size

    Args:
        chain_data: Raw option chain data
        extend_strike_range: Whether to extend to full strike range
        recalculate_atm: Whether to recalculate ATM strike
        fix_labels: Whether to fix CE/PE labels

    Returns:
        Normalized option chain data
    """
    try:
        # Extract current data
        underlying_ltp = chain_data.get("underlying_ltp", 0)
        current_chain = chain_data.get("chain", [])

        # Step 1: Recalculate ATM strike
        if recalculate_atm:
            atm_strike = calculate_atm_strike(underlying_ltp)
            logger.info(f"Recalculated ATM: {atm_strike} (from LTP: {underlying_ltp})")
        else:
            atm_strike = chain_data.get("atm_strike", calculate_atm_strike(underlying_ltp))

        # Step 2: Build strike map from existing data
        existing_strikes = {}
        for item in current_chain:
            strike = float(item.get("strike", 0))
            existing_strikes[strike] = item

        # Step 3: Generate full strike range or use existing
        if extend_strike_range:
            full_strikes = generate_full_strike_range()
            logger.info(f"Extended strike range: 17100-30100 ({len(full_strikes)} strikes)")
        else:
            full_strikes = sorted(existing_strikes.keys())

        # Step 4: Build normalized chain
        normalized_chain = []

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

            # Step 5: Fix labels
            if fix_labels:
                ce_label = calculate_option_label(strike, atm_strike, "CE")
                pe_label = calculate_option_label(strike, atm_strike, "PE")
            else:
                ce_label = ce_data.get("label", "")
                pe_label = pe_data.get("label", "")

            # Step 6: Standardize fields
            normalized_strike = {
                "strike": strike,
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

            normalized_chain.append(normalized_strike)

        # Step 7: Build final response
        normalized_data = {
            "status": "success",
            "underlying": chain_data.get("underlying", "NIFTY"),
            "underlying_ltp": underlying_ltp,
            "underlying_prev_close": chain_data.get("underlying_prev_close", underlying_ltp),
            "expiry_date": chain_data.get("expiry_date", "21APR26"),
            "atm_strike": atm_strike,
            "chain": normalized_chain
        }

        logger.info(f"Normalization complete: {len(normalized_chain)} strikes, ATM={atm_strike}")
        return normalized_data

    except Exception as e:
        logger.error(f"Error normalizing option chain: {e}")
        raise
