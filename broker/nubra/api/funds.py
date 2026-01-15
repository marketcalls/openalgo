# api/funds.py

import os
import httpx
import json
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)

# Nubra API Base URLs
UAT_BASE_URL = "https://uatapi.nubra.io"
PROD_BASE_URL = "https://api.nubra.io"

def get_base_url():
    """Get the base URL based on environment setting."""
    use_uat = os.getenv('NUBRA_USE_UAT', 'false').lower() == 'true'
    return UAT_BASE_URL if use_uat else PROD_BASE_URL


def get_margin_data(auth_token):
    """Fetch margin data from Nubra's API using the provided auth token."""

    # Get the shared httpx client with connection pooling
    client = get_httpx_client()
    base_url = get_base_url()

    headers = {
        'Authorization': f'Bearer {auth_token}',
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'x-device-id': 'OPENALGO'
    }

    logger.debug(f"Nubra funds request to: {base_url}/portfolio/user_funds_and_margin")

    response = client.get(
        f"{base_url}/portfolio/user_funds_and_margin",
        headers=headers
    )

    # Add status attribute for compatibility with the existing codebase
    response.status = response.status_code

    margin_data = json.loads(response.text)

    logger.info(f"Nubra Margin Data: {margin_data}")

    if margin_data.get('port_funds_and_margin'):
        data = margin_data['port_funds_and_margin']

        # Map Nubra fields to OpenAlgo standard format
        try:
            # Available cash - using net_margin_available as available funds
            availablecash = float(data.get('net_margin_available', 0) or 0)

            # Collateral - total pledged collateral value
            collateral = float(data.get('total_collateral', 0) or 0)

            # M2M Realized - using derivative premium (realized P&L from derivatives)
            m2mrealized = float(data.get('net_derivative_prem', 0) or 0)

            # M2M Unrealized - combining equity intraday and delivery MTM
            mtm_eq_iday = float(data.get('mtm_eq_iday_cnc', 0) or 0)
            mtm_eq_delivery = float(data.get('mtm_eq_delivery', 0) or 0)
            mtm_deriv = float(data.get('mtm_deriv', 0) or 0)
            m2munrealized = mtm_eq_iday + mtm_eq_delivery + mtm_deriv

            # Utilised debits - total margin blocked/used
            utiliseddebits = float(data.get('total_margin_blocked', 0) or 0)

        except (ValueError, TypeError) as e:
            logger.error(f"Error parsing Nubra margin data: {e}")
            availablecash = 0.0
            collateral = 0.0
            m2mrealized = 0.0
            m2munrealized = 0.0
            utiliseddebits = 0.0

        filtered_data = {
            "availablecash": "{:.2f}".format(availablecash),
            "collateral": "{:.2f}".format(collateral),
            "m2mrealized": "{:.2f}".format(m2mrealized),
            "m2munrealized": "{:.2f}".format(m2munrealized),
            "utiliseddebits": "{:.2f}".format(utiliseddebits)
        }

        logger.info(f"Nubra Filtered Margin Data: {filtered_data}")
        return filtered_data
    else:
        logger.warning(f"No port_funds_and_margin in Nubra response: {margin_data}")
        return {}