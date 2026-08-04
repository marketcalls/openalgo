# api/funds.py

import json

from broker.nubra.api.baseurl import (
    SESSION_EXPIRED_STATUS,
    NubraSessionExpired,
    get_nubra_headers,
    get_url,
)
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)


def get_margin_data(auth_token):
    """
    Fetch funds and margin from Nubra.

    Nubra API: GET /sentinel/portfolio/user_funds_and_margin
    V3 returns the snapshot under the camelCase key ``portFundsAndMargin``
    (V2 used ``port_funds_and_margin``). All cash/margin/MTM values are in
    paise.
    """

    # Get the shared httpx client with connection pooling
    client = get_httpx_client()

    endpoint = get_url("/sentinel/portfolio/user_funds_and_margin")
    logger.debug(f"Nubra funds request to: {endpoint}")

    response = client.get(endpoint, headers=get_nubra_headers(auth_token, with_json=False))

    # Add status attribute for compatibility with the existing codebase
    response.status = response.status_code

    if response.status_code == SESSION_EXPIRED_STATUS:
        # Raise rather than return {}. funds_service reports success
        # unconditionally when this function returns, so an empty dict would
        # answer HTTP 200 with no margin data instead of telling the user to
        # log in again; its except branch turns this into a 500 carrying the
        # message.
        logger.error("Nubra session expired (HTTP 440) fetching funds")
        raise NubraSessionExpired()

    try:
        margin_data = json.loads(response.text)
    except (json.JSONDecodeError, ValueError):
        logger.error(f"Failed to parse Nubra funds response: {response.text}")
        return {}

    logger.info(f"Nubra Margin Data: {margin_data}")

    data = margin_data.get("portFundsAndMargin")
    if not data:
        logger.warning(f"No portFundsAndMargin in Nubra response: {margin_data}")
        return {}

    # Map Nubra fields to OpenAlgo standard format
    try:
        # Nubra API returns values in paise, convert to rupees by dividing by 100

        # Available cash - netMarginAvailable is the spendable balance
        availablecash = float(data.get("netMarginAvailable", 0) or 0) / 100

        # Collateral - total pledged collateral value
        collateral = float(data.get("totalCollateral", 0) or 0) / 100

        # M2M Realized - net derivative premium (realized P&L from derivatives)
        m2mrealized = float(data.get("netDerivativePrem", 0) or 0) / 100

        # M2M Unrealized - equity intraday/CNC, equity delivery and derivative MTM
        mtm_eq_iday = float(data.get("mtmEqIdayCnc", 0) or 0) / 100
        mtm_eq_delivery = float(data.get("mtmEqDelivery", 0) or 0) / 100
        mtm_deriv = float(data.get("mtmDeriv", 0) or 0) / 100
        m2munrealized = mtm_eq_iday + mtm_eq_delivery + mtm_deriv

        # Utilised debits - total margin blocked/used
        utiliseddebits = float(data.get("totalMarginBlocked", 0) or 0) / 100

    except (ValueError, TypeError) as e:
        logger.error(f"Error parsing Nubra margin data: {e}")
        availablecash = 0.0
        collateral = 0.0
        m2mrealized = 0.0
        m2munrealized = 0.0
        utiliseddebits = 0.0

    filtered_data = {
        "availablecash": f"{availablecash:.2f}",
        "collateral": f"{collateral:.2f}",
        "m2mrealized": f"{m2mrealized:.2f}",
        "m2munrealized": f"{m2munrealized:.2f}",
        "utiliseddebits": f"{utiliseddebits:.2f}",
    }

    logger.info(f"Nubra Filtered Margin Data: {filtered_data}")
    return filtered_data
