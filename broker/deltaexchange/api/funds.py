# api/funds.py
# Delta Exchange wallet balance → OpenAlgo margin format
# Endpoint: GET /v2/wallet/balances  (authenticated, HMAC-SHA256)

import os

from broker.deltaexchange.api.baseurl import BASE_URL, get_auth_headers
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)

DEFAULT_MARGIN_RESPONSE = {
    "availablecash": "0.00",
    "collateral": "0.00",
    "m2mrealized": "0.00",
    "m2munrealized": "0.00",
    "utiliseddebits": "0.00",
}


def _f(value):
    """Safe float conversion from string or number."""
    try:
        return float(value or 0)
    except (ValueError, TypeError):
        return 0.0


def get_margin_data(auth_token):
    """
    Fetch wallet balance from Delta Exchange and return it in OpenAlgo margin format.

    Endpoint: GET /v2/wallet/balances
    Authentication: HMAC-SHA256 signed headers (api-key + timestamp + signature)

    Delta Exchange wallet balance object fields used:
        available_balance  – free balance, immediately tradeable
        blocked_margin     – total margin locked by open positions + orders
        realized_pnl       – realised P&L since position was opened
        unrealized_pnl     – unrealised P&L at current mark price

    OpenAlgo field mapping:
        availablecash  ← available_balance
        collateral     ← 0.00  (no pledge/collateral model on crypto derivatives)
        m2mrealized    ← realized_pnl
        m2munrealized  ← unrealized_pnl
        utiliseddebits ← blocked_margin

    Args:
        auth_token (str): api_key stored in OpenAlgo auth DB after login.

    Returns:
        dict: OpenAlgo standard margin dict, or DEFAULT_MARGIN_RESPONSE on failure.
    """
    api_key = auth_token
    api_secret = os.getenv("BROKER_API_SECRET", "")

    if not api_key or not api_secret:
        logger.error("[DeltaExchange] BROKER_API_KEY / BROKER_API_SECRET not set")
        return DEFAULT_MARGIN_RESPONSE

    path = "/v2/wallet/balances"
    url = BASE_URL + path

    try:
        headers = get_auth_headers(
            method="GET",
            path=path,
            query_string="",
            payload="",
            api_key=api_key,
            api_secret=api_secret,
        )

        client = get_httpx_client()
        response = client.get(url, headers=headers, timeout=30.0)

        if response.status_code != 200:
            logger.error(
                f"[DeltaExchange] wallet/balances HTTP {response.status_code}: "
                f"{response.text[:200]}"
            )
            return DEFAULT_MARGIN_RESPONSE

        data = response.json()

        if not data.get("success", False):
            error = data.get("error", {})
            logger.error(f"[DeltaExchange] wallet/balances API error: {error}")
            return DEFAULT_MARGIN_RESPONSE

        balances = data.get("result", [])
        if not isinstance(balances, list):
            logger.error(
                f"[DeltaExchange] Unexpected wallet/balances result type: {type(balances)}"
            )
            return DEFAULT_MARGIN_RESPONSE

        # Aggregate across all assets (Delta India is primarily USD-settled)
        total_available = 0.0
        total_blocked = 0.0
        total_realized_pnl = 0.0
        total_unrealized_pnl = 0.0

        for asset in balances:
            if not isinstance(asset, dict):
                continue
            total_available += _f(asset.get("available_balance", 0))
            total_blocked += _f(asset.get("blocked_margin", 0))
            total_realized_pnl += _f(asset.get("realized_pnl", 0))
            total_unrealized_pnl += _f(asset.get("unrealized_pnl", 0))

        result = {
            "availablecash": f"{total_available:.2f}",
            "collateral": "0.00",
            "m2mrealized": f"{total_realized_pnl:.2f}",
            "m2munrealized": f"{total_unrealized_pnl:.2f}",
            "utiliseddebits": f"{total_blocked:.2f}",
        }

        logger.info(
            f"[DeltaExchange] Wallet balance: available={result['availablecash']} "
            f"blocked={result['utiliseddebits']}"
        )
        return result

    except Exception as e:
        logger.error(f"[DeltaExchange] Unexpected error in get_margin_data: {e}", exc_info=True)
        return DEFAULT_MARGIN_RESPONSE
