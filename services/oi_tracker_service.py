"""
OI Tracker Service

Provides Open Interest data aggregation and Max Pain calculation
for option chains. Reuses the existing option chain service for OI data.

Functions:
    get_oi_data() - Get OI data for all strikes with PCR and futures price
    calculate_max_pain() - Calculate max pain strike and pain distribution
"""

from typing import Any

from database.token_db_enhanced import fno_search_symbols
from services.option_chain_service import get_option_chain
from services.quotes_service import get_quotes
from utils.logging import get_logger

logger = get_logger(__name__)


def _get_nearest_futures_price(
    underlying: str, exchange: str, expiry_date: str, api_key: str
) -> float | None:
    """
    Get the nearest month futures price for an underlying.

    Searches for futures contracts matching the underlying and expiry,
    then fetches the LTP.

    Args:
        underlying: Base symbol (e.g., NIFTY, BANKNIFTY)
        exchange: Options exchange (NFO, BFO, etc.)
        expiry_date: Expiry in DDMMMYY format (e.g., 30JAN26)
        api_key: OpenAlgo API key

    Returns:
        Futures LTP or None if not found
    """
    try:
        # Convert DDMMMYY to DD-MMM-YY for database lookup
        expiry_formatted = f"{expiry_date[:2]}-{expiry_date[2:5]}-{expiry_date[5:]}".upper()

        # Search for futures contract matching this expiry
        futures = fno_search_symbols(
            underlying=underlying,
            exchange=exchange,
            instrumenttype="FUT",
            expiry=expiry_formatted,
            limit=1,
        )

        if not futures:
            # Try without expiry filter to get nearest futures
            futures = fno_search_symbols(
                underlying=underlying,
                exchange=exchange,
                instrumenttype="FUT",
                limit=10,
            )
            if not futures:
                logger.warning(f"No futures contracts found for {underlying} on {exchange}")
                return None

            # Sort by expiry to get nearest
            from datetime import datetime

            def parse_expiry(exp_str: str) -> datetime:
                try:
                    return datetime.strptime(exp_str, "%d-%b-%y")
                except (ValueError, TypeError):
                    return datetime.max

            futures.sort(key=lambda f: parse_expiry(f.get("expiry", "")))

        fut_symbol = futures[0]["symbol"]
        fut_exchange = futures[0]["exchange"]

        logger.info(f"Fetching futures price for {fut_symbol} on {fut_exchange}")
        success, quote_response, _ = get_quotes(
            symbol=fut_symbol, exchange=fut_exchange, api_key=api_key
        )

        if success and "data" in quote_response:
            return quote_response["data"].get("ltp")

        return None
    except Exception as e:
        logger.warning(f"Error fetching futures price: {e}")
        return None


def get_oi_data(
    underlying: str, exchange: str, expiry_date: str, api_key: str
) -> tuple[bool, dict[str, Any], int]:
    """
    Get Open Interest data for all strikes of an underlying/expiry.

    Uses the option chain service to fetch OI data, then computes:
    - Total CE/PE OI and overall PCR
    - Per-strike PCR for PCR line
    - Futures price for the matching expiry

    Args:
        underlying: Underlying symbol (e.g., NIFTY, BANKNIFTY)
        exchange: Exchange (NSE_INDEX, BSE_INDEX, NFO, BFO)
        expiry_date: Expiry in DDMMMYY format
        api_key: OpenAlgo API key

    Returns:
        Tuple of (success, response_data, status_code)
    """
    try:
        # Fetch option chain (45 strikes around ATM)
        success, chain_response, status_code = get_option_chain(
            underlying=underlying,
            exchange=exchange,
            expiry_date=expiry_date,
            strike_count=45,
            api_key=api_key,
        )

        if not success:
            return False, chain_response, status_code

        full_chain = chain_response.get("chain", [])
        atm_strike = chain_response.get("atm_strike")
        spot_price = chain_response.get("underlying_ltp")

        # Compute PCR and totals from the full chain
        total_ce_oi = 0
        total_pe_oi = 0
        total_ce_volume = 0
        total_pe_volume = 0
        lot_size = None

        for item in full_chain:
            if item.get("ce"):
                total_ce_oi += item["ce"].get("oi", 0) or 0
                total_ce_volume += item["ce"].get("volume", 0) or 0
                if lot_size is None and item["ce"].get("lotsize"):
                    lot_size = item["ce"]["lotsize"]
            if item.get("pe"):
                total_pe_oi += item["pe"].get("oi", 0) or 0
                total_pe_volume += item["pe"].get("volume", 0) or 0
                if lot_size is None and item["pe"].get("lotsize"):
                    lot_size = item["pe"]["lotsize"]

        pcr_oi = round(total_pe_oi / total_ce_oi, 2) if total_ce_oi > 0 else 0
        pcr_volume = round(total_pe_volume / total_ce_volume, 2) if total_ce_volume > 0 else 0

        # Build OI chain for chart
        oi_chain = []
        for item in full_chain:
            ce_oi = 0
            pe_oi = 0
            if item.get("ce"):
                ce_oi = item["ce"].get("oi", 0) or 0
            if item.get("pe"):
                pe_oi = item["pe"].get("oi", 0) or 0
            oi_chain.append(
                {
                    "strike": item["strike"],
                    "ce_oi": ce_oi,
                    "pe_oi": pe_oi,
                }
            )

        # Get futures price (single get_quotes call)
        # exchange is already the options exchange (NFO/BFO) from the frontend
        futures_price = _get_nearest_futures_price(
            underlying=underlying,
            exchange=exchange,
            expiry_date=expiry_date,
            api_key=api_key,
        )

        return (
            True,
            {
                "status": "success",
                "underlying": chain_response.get("underlying", underlying),
                "spot_price": spot_price,
                "futures_price": futures_price,
                "lot_size": lot_size or 1,
                "pcr_oi": pcr_oi,
                "pcr_volume": pcr_volume,
                "total_ce_oi": total_ce_oi,
                "total_pe_oi": total_pe_oi,
                "atm_strike": atm_strike,
                "expiry_date": expiry_date,
                "chain": oi_chain,
            },
            200,
        )

    except Exception as e:
        logger.exception(f"Error in get_oi_data: {e}")
        return (
            False,
            {"status": "error", "message": "Error fetching OI data"},
            500,
        )


def calculate_max_pain(
    underlying: str, exchange: str, expiry_date: str, api_key: str
) -> tuple[bool, dict[str, Any], int]:
    """
    Calculate Max Pain for an underlying/expiry.

    Max Pain is the strike price at which option writers (sellers) would
    experience the least financial loss. For each candidate strike:
    - CE writer loss = sum of (candidate - strike) * ce_oi for all strikes below candidate
    - PE writer loss = sum of (strike - candidate) * pe_oi for all strikes above candidate
    - Total pain = CE loss + PE loss
    - Max pain = strike with minimum total pain

    Args:
        underlying: Underlying symbol
        exchange: Exchange
        expiry_date: Expiry in DDMMMYY format
        api_key: OpenAlgo API key

    Returns:
        Tuple of (success, response_data, status_code)
    """
    try:
        # First get OI data
        success, oi_response, status_code = get_oi_data(
            underlying=underlying,
            exchange=exchange,
            expiry_date=expiry_date,
            api_key=api_key,
        )

        if not success:
            return False, oi_response, status_code

        chain = oi_response.get("chain", [])
        lot_size = oi_response.get("lot_size", 1)

        if not chain:
            return False, {"status": "error", "message": "No OI data available"}, 404

        # Filter out invalid entries
        chain = [item for item in chain if isinstance(item.get("strike"), (int, float)) and item["strike"] > 0]
        if not chain:
            return False, {"status": "error", "message": "No valid strike data available"}, 404

        # Calculate pain at each strike
        pain_data = []
        for candidate in chain:
            candidate_strike = candidate["strike"]
            ce_pain = 0
            pe_pain = 0

            for item in chain:
                strike = item["strike"]
                ce_oi = item["ce_oi"]
                pe_oi = item["pe_oi"]

                # CE writers lose when underlying > strike (CE is ITM)
                if candidate_strike > strike and ce_oi > 0:
                    ce_pain += (candidate_strike - strike) * ce_oi

                # PE writers lose when underlying < strike (PE is ITM)
                if candidate_strike < strike and pe_oi > 0:
                    pe_pain += (strike - candidate_strike) * pe_oi

            total_pain = ce_pain + pe_pain

            pain_data.append(
                {
                    "strike": candidate_strike,
                    "ce_pain": round(ce_pain, 2),
                    "pe_pain": round(pe_pain, 2),
                    "total_pain": round(total_pain, 2),
                    # Convert to Crores for display
                    "total_pain_cr": round(total_pain / 10000000, 2),
                }
            )

        # Find max pain strike (minimum total pain)
        max_pain_entry = min(pain_data, key=lambda x: x["total_pain"])
        max_pain_strike = max_pain_entry["strike"]

        return (
            True,
            {
                "status": "success",
                "underlying": oi_response.get("underlying", underlying),
                "spot_price": oi_response.get("spot_price"),
                "futures_price": oi_response.get("futures_price"),
                "atm_strike": oi_response.get("atm_strike"),
                "max_pain_strike": max_pain_strike,
                "lot_size": lot_size,
                "pcr_oi": oi_response.get("pcr_oi"),
                "pcr_volume": oi_response.get("pcr_volume"),
                "expiry_date": expiry_date,
                "pain_data": pain_data,
            },
            200,
        )

    except Exception as e:
        logger.exception(f"Error calculating max pain: {e}")
        return (
            False,
            {"status": "error", "message": "Error calculating max pain"},
            500,
        )
