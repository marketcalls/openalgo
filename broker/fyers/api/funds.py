# api/funds.py for Fyers

import json
import os
import threading
import time
from typing import Any, Dict, Optional

import httpx

from broker.fyers.api.order_api import get_positions
from broker.fyers.mapping.order_data import map_position_data
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)

# Per-user cache and rate limit state, keyed by auth_token
_cache: dict[str, dict] = {}
_rate_limit: dict[str, dict] = {}
_lock = threading.Lock()

CACHE_TTL = 60  # seconds - serve cached data within this window
INITIAL_BACKOFF = 30  # seconds - first backoff after 429
MAX_BACKOFF = 120  # seconds - maximum backoff duration


def get_margin_data(auth_token: str) -> dict[str, str]:
    """
    Fetch and process margin/funds data from Fyers' API using shared HTTP client with connection pooling.
    Includes response caching and exponential backoff on rate limits (429).

    Args:
        auth_token: The authentication token for Fyers API (format: 'app_id:access_token')

    Returns:
        dict: Processed margin data with standardized keys:
            - availablecash: Total available balance
            - collateral: Collateral value
            - m2munrealized: Unrealized M2M
            - m2mrealized: Realized M2M
            - utiliseddebits: Utilized amount
    """
    # Initialize default response
    default_response = {
        "availablecash": "0.00",
        "collateral": "0.00",
        "m2munrealized": "0.00",
        "m2mrealized": "0.00",
        "utiliseddebits": "0.00",
    }

    now = time.time()

    with _lock:
        user_cache = _cache.get(auth_token, {"data": None, "timestamp": 0})
        user_rate_limit = _rate_limit.get(auth_token, {"backoff_until": 0, "backoff_seconds": 0})

    # If within cache TTL, return cached data
    if user_cache["data"] and (now - user_cache["timestamp"]) < CACHE_TTL:
        return user_cache["data"]

    # If rate-limited and in backoff period, return cached or default data
    if now < user_rate_limit["backoff_until"]:
        remaining = int(user_rate_limit["backoff_until"] - now)
        logger.debug(f"Rate limit backoff active, {remaining}s remaining. Serving cached data.")
        return user_cache["data"] if user_cache["data"] else default_response

    api_key = os.getenv("BROKER_API_KEY")
    if not api_key:
        logger.error("BROKER_API_KEY environment variable not set")
        return default_response

    # Get shared HTTP client with connection pooling
    client = get_httpx_client()

    headers = {"Authorization": f"{api_key}:{auth_token}", "Content-Type": "application/json"}

    try:
        # Get the funds data
        response = client.get("https://api-t1.fyers.in/api/v3/funds", headers=headers, timeout=30.0)
        response.raise_for_status()

        funds_data = response.json()
        logger.debug(f"Fyers funds API response: {json.dumps(funds_data, indent=2)}")

        if funds_data.get("code") != 200:
            error_msg = funds_data.get("message", "Unknown error")
            logger.error(f"Error in Fyers funds API: {error_msg}")
            return user_cache["data"] if user_cache["data"] else default_response

        # Process the funds data
        processed_funds = {}
        for fund in funds_data.get("fund_limit", []):
            try:
                key = fund["title"].lower().replace(" ", "_")
                processed_funds[key] = {
                    "equity_amount": float(fund.get("equityAmount", 0)),
                    "commodity_amount": float(fund.get("commodityAmount", 0)),
                }
            except (KeyError, ValueError) as e:
                logger.warning(f"Error processing fund entry: {e}")
                continue

        # Calculate totals with proper error handling
        try:
            # Get available balance
            balance = processed_funds.get("available_balance", {})
            balance_equity = float(balance.get("equity_amount", 0))
            balance_commodity = float(balance.get("commodity_amount", 0))
            total_balance = balance_equity + balance_commodity

            # Get collateral
            collateral = processed_funds.get("collaterals", {})
            collateral_equity = float(collateral.get("equity_amount", 0))
            collateral_commodity = float(collateral.get("commodity_amount", 0))
            total_collateral = collateral_equity + collateral_commodity

            # Get realized P&L
            pnl = processed_funds.get("realized_profit_and_loss", {})
            real_pnl_equity = float(pnl.get("equity_amount", 0))
            real_pnl_commodity = float(pnl.get("commodity_amount", 0))
            total_real_pnl = real_pnl_equity + real_pnl_commodity

            # Get utilized amount
            utilized = processed_funds.get("utilized_amount", {})
            utilized_equity = float(utilized.get("equity_amount", 0))
            utilized_commodity = float(utilized.get("commodity_amount", 0))
            total_utilized = utilized_equity + utilized_commodity

            # Get unrealized P&L from position book
            position_book_raw = get_positions(auth_token)
            logger.info(
                f"Fyers position book raw response: {json.dumps(position_book_raw, indent=2)}"
            )
            position_book = map_position_data(position_book_raw)
            logger.info(f"Fyers position book mapped: {position_book}")

            def sum_realised_unrealised(position_book):
                total_realised = sum(
                    float(position.get("realized_profit", 0)) for position in position_book
                )
                total_unrealised = sum(
                    float(position.get("unrealized_profit", 0)) for position in position_book
                )
                return total_realised, total_unrealised

            total_realised, total_unrealised = sum_realised_unrealised(position_book)

            # Format and return the response
            result = {
                "availablecash": f"{total_balance:.2f}",
                "collateral": f"{total_collateral:.2f}",
                "m2munrealized": f"{total_unrealised:.2f}",
                "m2mrealized": f"{total_realised:.2f}",
                "utiliseddebits": f"{total_utilized:.2f}",
            }

            # Cache successful response and reset backoff
            with _lock:
                _cache[auth_token] = {"data": result, "timestamp": now}
                _rate_limit[auth_token] = {"backoff_until": 0, "backoff_seconds": 0}

            return result

        except (ValueError, TypeError):
            logger.exception("Error calculating fund totals")
            return user_cache["data"] if user_cache["data"] else default_response

    except httpx.HTTPStatusError as e:
        if e.response.status_code == 429:
            # Exponential backoff: 30s → 60s → 120s (max)
            with _lock:
                backoff = user_rate_limit["backoff_seconds"]
                backoff = INITIAL_BACKOFF if backoff == 0 else min(backoff * 2, MAX_BACKOFF)
                _rate_limit[auth_token] = {
                    "backoff_until": time.time() + backoff,
                    "backoff_seconds": backoff,
                }
            logger.warning(
                f"Fyers API rate limited (429). Backing off for {backoff}s. "
                f"Serving cached data."
            )
            return user_cache["data"] if user_cache["data"] else default_response
        logger.error(f"HTTP error {e.response.status_code} fetching Fyers funds: {e.response.text}")
    except httpx.RequestError as e:
        logger.error(f"Request failed: {str(e)}")
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse Fyers API response: {str(e)}")
    except Exception:
        logger.exception("Unexpected error in get_margin_data")

    return user_cache["data"] if user_cache["data"] else default_response