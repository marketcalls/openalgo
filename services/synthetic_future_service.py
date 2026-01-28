"""
Synthetic Future Service

This service calculates synthetic futures price using ATM options.

A synthetic future is created by combining:
- Long Call + Short Put at the same strike (synthetic long future)

Formula:
Synthetic Future Price = Strike Price + Call Premium - Put Premium

The basis (difference from spot) indicates the cost of carry.
"""

from typing import Any, Dict, Tuple

from services.option_symbol_service import get_option_symbol
from services.quotes_service import get_quotes
from utils.logging import get_logger

logger = get_logger(__name__)


def calculate_synthetic_future(
    underlying: str, exchange: str, expiry_date: str, api_key: str
) -> tuple[bool, dict[str, Any], int]:
    """
    Calculate synthetic future price using ATM Call and Put options.

    Args:
        underlying: Underlying symbol (e.g., "NIFTY", "BANKNIFTY")
        exchange: Exchange (e.g., "NSE_INDEX", "NSE")
        expiry_date: Expiry date in DDMMMYY format (e.g., "28OCT25")
        api_key: OpenAlgo API key

    Returns:
        Tuple of (success, response_data, status_code)

    Response includes:
        - underlying: Underlying symbol
        - underlying_ltp: Current LTP of underlying
        - expiry: Expiry date
        - atm_strike: ATM strike price
        - synthetic_future_price: Calculated synthetic future price
    """
    try:
        logger.info(f"Calculating synthetic future for {underlying} expiring {expiry_date}")

        # Step 1: Get ATM Call option symbol
        success_call, call_response, status_code = get_option_symbol(
            underlying=underlying,
            exchange=exchange,
            expiry_date=expiry_date,
            strike_int=None,  # Use actual strikes from database
            offset="ATM",
            option_type="CE",
            api_key=api_key,
        )

        if not success_call:
            logger.error(f"Failed to get ATM Call symbol: {call_response.get('message')}")
            return False, call_response, status_code

        call_symbol = call_response.get("symbol")
        call_exchange = call_response.get("exchange")
        underlying_ltp = call_response.get("underlying_ltp")
        atm_strike = None

        # Extract ATM strike from the call symbol
        # For NIFTY28OCT2526000CE, we need to extract 26000
        # Format: [BASE][DDMMMYY][STRIKE][CE/PE]
        try:
            # Remove base symbol and date from the beginning
            base_symbol = underlying.upper()
            expiry_str = expiry_date.upper()
            temp = call_symbol.replace(base_symbol, "", 1).replace(expiry_str, "", 1)
            # Remove CE from the end
            strike_str = temp.replace("CE", "").replace("PE", "")
            atm_strike = float(strike_str)
            logger.info(f"Extracted ATM strike: {atm_strike}")
        except Exception as e:
            logger.exception(f"Failed to extract strike from {call_symbol}: {e}")
            return (
                False,
                {
                    "status": "error",
                    "message": f"Failed to parse strike from option symbol: {call_symbol}",
                },
                500,
            )

        # Step 2: Get ATM Put option symbol
        success_put, put_response, status_code = get_option_symbol(
            underlying=underlying,
            exchange=exchange,
            expiry_date=expiry_date,
            strike_int=None,  # Use actual strikes from database
            offset="ATM",
            option_type="PE",
            api_key=api_key,
        )

        if not success_put:
            logger.error(f"Failed to get ATM Put symbol: {put_response.get('message')}")
            return False, put_response, status_code

        put_symbol = put_response.get("symbol")
        put_exchange = put_response.get("exchange")

        # Step 3: Get Call option LTP
        success_call_quote, call_quote_response, status_code = get_quotes(
            symbol=call_symbol, exchange=call_exchange, api_key=api_key
        )

        if not success_call_quote:
            logger.error(f"Failed to get Call quote: {call_quote_response.get('message')}")
            return False, call_quote_response, status_code

        call_ltp = call_quote_response.get("data", {}).get("ltp")
        if call_ltp is None:
            return (
                False,
                {
                    "status": "error",
                    "message": f"Could not fetch LTP for Call option: {call_symbol}",
                },
                500,
            )

        # Step 4: Get Put option LTP
        success_put_quote, put_quote_response, status_code = get_quotes(
            symbol=put_symbol, exchange=put_exchange, api_key=api_key
        )

        if not success_put_quote:
            logger.error(f"Failed to get Put quote: {put_quote_response.get('message')}")
            return False, put_quote_response, status_code

        put_ltp = put_quote_response.get("data", {}).get("ltp")
        if put_ltp is None:
            return (
                False,
                {"status": "error", "message": f"Could not fetch LTP for Put option: {put_symbol}"},
                500,
            )

        # Step 5: Calculate Synthetic Future Price
        # Formula: Strike + Call Premium - Put Premium
        synthetic_future_price = atm_strike + call_ltp - put_ltp

        # Step 6: Calculate Basis (Cost of Carry)
        # Basis = Synthetic Future Price - Spot Price
        basis = synthetic_future_price - underlying_ltp

        logger.info(
            f"Synthetic Future calculated: Strike={atm_strike}, "
            f"Call={call_ltp}, Put={put_ltp}, "
            f"Synthetic={synthetic_future_price:.2f}, Basis={basis:.2f}"
        )

        # Step 7: Return response
        return (
            True,
            {
                "status": "success",
                "underlying": underlying,
                "underlying_ltp": underlying_ltp,
                "expiry": expiry_date,
                "atm_strike": atm_strike,
                "synthetic_future_price": round(synthetic_future_price, 2),
            },
            200,
        )

    except Exception as e:
        logger.exception(f"Error calculating synthetic future: {e}")
        return (
            False,
            {
                "status": "error",
                "message": f"An error occurred while calculating synthetic future: {str(e)}",
            },
            500,
        )
