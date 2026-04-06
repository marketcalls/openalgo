"""
Mudrex wallet balance → OpenAlgo margin format.

Endpoints:
    POST /wallet/funds    — spot wallet (total, withdrawable)
    GET  /futures/funds    — futures wallet (balance, locked_amount)
    GET  /futures/positions — open positions (for P&L aggregation)
"""

import os

from broker.mudrex.api.mudrex_http import mudrex_request
from utils.logging import get_logger

logger = get_logger(__name__)

DEFAULT_MARGIN_RESPONSE = {
    "availablecash": "0.00",
    "collateral": "0.00",
    "m2mrealized": "0.00",
    "m2munrealized": "0.00",
    "utiliseddebits": "0.00",
}


def _f(value, default: float = 0.0) -> float:
    try:
        return float(value) if value is not None else default
    except (ValueError, TypeError):
        return default


def get_margin_data(auth_token: str) -> dict:
    """Fetch wallet balances from Mudrex and return OpenAlgo margin dict.

    Combines spot wallet (POST /wallet/funds) and futures wallet
    (GET /futures/funds) into a single response matching the interface
    used by ``services/funds_service.py``.
    """
    secret = auth_token or os.getenv("BROKER_API_SECRET", "")
    if not secret:
        logger.error("[Mudrex] BROKER_API_SECRET not set")
        return DEFAULT_MARGIN_RESPONSE

    total_available = 0.0
    total_locked = 0.0

    # Spot wallet
    try:
        spot = mudrex_request("/wallet/funds", method="POST", auth=secret)
        if spot.get("success"):
            d = spot.get("data", {})
            total_available += _f(d.get("withdrawable"))
        else:
            logger.warning(f"[Mudrex] spot wallet error: {spot}")
    except Exception as exc:
        logger.warning(f"[Mudrex] Exception fetching spot wallet: {exc}")

    # Futures wallet
    try:
        fut = mudrex_request("/futures/funds", method="GET", auth=secret)
        if fut.get("success"):
            d = fut.get("data", {})
            total_available += _f(d.get("balance"))
            total_locked += _f(d.get("locked_amount"))
        else:
            logger.warning(f"[Mudrex] futures wallet error: {fut}")
    except Exception as exc:
        logger.warning(f"[Mudrex] Exception fetching futures wallet: {exc}")

    result = {
        "availablecash": f"{total_available:.2f}",
        "collateral": "0.00",
        "m2mrealized": "0.00",
        "m2munrealized": "0.00",
        "utiliseddebits": f"{total_locked:.2f}",
    }

    logger.debug(
        f"[Mudrex] Wallet: available={result['availablecash']} "
        f"locked={result['utiliseddebits']}"
    )
    return result
