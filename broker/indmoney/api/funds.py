# api/funds.py

import json

from broker.indmoney.api.baseurl import get_url
from broker.indmoney.api.rate_limiter import rate_limited_request
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)



# Default response format for margin data (OpenAlgo standard format)
DEFAULT_MARGIN_RESPONSE = {
    "availablecash": "0.00",
    "collateral": "0.00",
    "m2mrealized": "0.00",
    "m2munrealized": "0.00",
    "utiliseddebits": "0.00",
}

# Cash-segment keys within `detailed_avl_balance`. The equity delivery limit is
# the closest analogue to plain "available cash": option_buy can exceed it
# because of premium-specific limits, and reporting that as cash would overstate
# what is spendable on stock.
_CASH_BALANCE_KEYS = ("eq_cnc", "eq_mis", "eq_mtf")


def _as_float(value, default=0.0):
    """Coerce a broker numeric to float, tolerating strings, None, and blanks."""
    if value is None:
        return default
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return default


def _available_cash(data, fallback):
    """
    Pick the balance available to trade from `detailed_avl_balance`.

    Prefers the equity delivery limit, then any other cash-segment key, and
    finally falls back to `withdrawal_balance` when the breakdown is absent.
    """
    detailed = data.get("detailed_avl_balance")
    if isinstance(detailed, dict):
        for key in _CASH_BALANCE_KEYS:
            if detailed.get(key) is not None:
                return _as_float(detailed[key])
        # Unexpected shape: fall through to withdrawal_balance rather than
        # guessing. Taking the largest value in the breakdown would happily
        # return option_buy - which exceeds the cash limit (4449.65 vs 2980.40
        # in the docs' own sample) - and reporting premium buying power as
        # stock cash overstates available funds and therefore order size.
        logger.warning(
            "IndMoney detailed_avl_balance has no recognised cash key "
            f"({sorted(detailed)}); using withdrawal_balance for available cash."
        )
    return fallback


def get_margin_data(auth_token):
    """
    Fetch margin data from Indmoney API using the provided auth token.

    Args:
        auth_token (str): The authorization token for Indmoney API

    Returns:
        dict: Formatted margin data or default values if request fails
    """
    logger.info("Getting margin data from Indmoney API")

    try:
        # Get the shared httpx client with connection pooling
        client = get_httpx_client()
        # Never log the access token itself, at any level.
        headers = {"Authorization": auth_token}

        # Get the API URL from baseurl
        url = get_url("/funds")

        logger.info(f"Making request to: {url}")

        # Make the API request with standard timeout (429-aware)
        response = rate_limited_request(client, "GET", url, headers=headers, timeout=30.0)

        # Check if the request was successful
        if response.status_code != 200:
            logger.error(
                f"Error fetching margin data: HTTP {response.status_code} - {response.text[:200]}..."
            )

            # Check if it's a Cloudflare challenge
            if response.status_code == 403 and (
                "cloudflare" in response.text.lower() or "just a moment" in response.text.lower()
            ):
                logger.warning("Cloudflare protection detected - API requires browser-based access")
                logger.warning(
                    "Consider using a headless browser solution or contacting Indmoney for API whitelisting"
                )

            return DEFAULT_MARGIN_RESPONSE

        try:
            # Try to parse the JSON response
            response_data = response.json()
            logger.debug(f"Raw response from Indmoney API: {response_data}")

            # Check if the response indicates success
            if response_data.get("status") != "success":
                error_msg = response_data.get("message", "Unknown error")
                logger.error(f"API returned error: {error_msg}")
                return DEFAULT_MARGIN_RESPONSE

            # Extract the margin data
            data = response_data.get("data", {})
            if not data:
                logger.error("No data in API response")
                return DEFAULT_MARGIN_RESPONSE

            # Extract values from the response and convert to float
            sod_balance = _as_float(data.get("sod_balance"))
            withdrawal_balance = _as_float(data.get("withdrawal_balance"))
            pledge_received = _as_float(data.get("pledge_received"))
            realized_pnl = _as_float(data.get("realized_pnl"))
            unrealized_pnl = _as_float(data.get("unrealized_pnl"))

            # Available cash is the balance available to TRADE, which is what
            # `detailed_avl_balance` reports per product/segment. It is not
            # `withdrawal_balance` - that is only what may be withdrawn, and is
            # typically lower (in the docs' own sample, option_buy is 4449.65
            # against a withdrawal_balance of 2983.47). Using the withdrawal
            # figure under-reports buying power and makes sizing over-cautious.
            available_cash = _available_cash(data, withdrawal_balance)

            # Utilised margin: what the day's activity has consumed out of the
            # start-of-day balance.
            utilised_debits = max(0.0, sod_balance - available_cash)

            # OpenAlgo standard required keys (matching Angel broker format)
            required_keys = [
                "availablecash",
                "collateral",
                "m2mrealized",
                "m2munrealized",
                "utiliseddebits",
            ]

            # Prepare the response in OpenAlgo standard format
            processed_data = {}

            # Map INDmoney fields to OpenAlgo standard fields
            field_mapping = {
                "availablecash": available_cash,  # Balance available to trade
                "collateral": pledge_received,  # Collateral is the pledge received
                "m2mrealized": realized_pnl,  # Realized P&L
                "m2munrealized": unrealized_pnl,  # Unrealized P&L
                "utiliseddebits": utilised_debits,  # SOD balance consumed so far
            }

            # Format each value to 2 decimal places
            for key in required_keys:
                value = field_mapping.get(key, 0)
                try:
                    formatted_value = f"{float(value):.2f}"
                except (ValueError, TypeError):
                    formatted_value = "0.00"
                processed_data[key] = formatted_value

            # Day charges are newly documented but have no slot in OpenAlgo's
            # 5-field funds contract, which is shared by every broker. Log them
            # rather than widening a response shape other brokers also return.
            logger.debug(
                "IndMoney day charges: brokerage=%s eq_charges=%s fno_charges=%s",
                _as_float(data.get("brokerage")),
                _as_float(data.get("eq_charges")),
                _as_float(data.get("fno_charges")),
            )

            logger.info("Successfully processed margin data from Indmoney API")
            return processed_data

        except (json.JSONDecodeError, ValueError, TypeError) as parse_err:
            logger.error(f"Failed to parse API response: {str(parse_err)}")
            if "response" in locals():
                logger.debug(f"Response content: {response.text[:500]}...")
            return DEFAULT_MARGIN_RESPONSE

    except Exception as e:
        logger.error(f"Unexpected error in get_margin_data: {str(e)}", exc_info=True)
        return DEFAULT_MARGIN_RESPONSE
