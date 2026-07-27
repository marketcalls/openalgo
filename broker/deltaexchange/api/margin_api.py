# api/margin_api.py
# Delta Exchange margin calculation
# Endpoint: GET /v2/products/{product_id}/margin_required  (authenticated)

import os

from broker.deltaexchange.api.baseurl import BASE_URL, get_auth_headers
from broker.deltaexchange.mapping.margin_data import parse_margin_response, transform_margin_positions
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)


def get_margin_mode(auth: str) -> str:
    """
    Detect the account's current margin mode from Delta Exchange.

    Calls: GET /v2/users/trading_preferences

    Returns one of:
        "isolated"  – each position holds margin independently (default)
        "cross"     – all positions share a single margin pool
        "unknown"   – the API call failed or the field is absent

    The margin mode affects the interpretation of available_margin:
    in cross-margin mode the full wallet balance is available to all
    positions combined, whereas in isolated mode each position has a
    separate margin allocation.
    """
    api_key    = auth
    api_secret = os.getenv("BROKER_API_SECRET", "")
    if not api_key or not api_secret:
        return "unknown"

    path = "/v2/users/trading_preferences"
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
        resp = client.get(BASE_URL + path, headers=headers, timeout=15.0)
        data = resp.json()
        if data.get("success"):
            prefs = data.get("result", {})
            # Delta Exchange field can be 'margin_type', 'portfolio_margin_enabled', etc.
            # Try several known field names for resilience.
            if prefs.get("portfolio_margin_enabled") or prefs.get("margin_type") == "cross":
                return "cross"
            return "isolated"
    except Exception as exc:
        logger.warning(f"[DeltaExchange] Could not fetch trading_preferences: {exc}")
    return "unknown"


def calculate_margin_api(positions, auth):
    """
    Calculate margin requirement for a basket of positions using Delta Exchange API.

    For each position, calls:
        GET /v2/products/{product_id}/margin_required
            ?size=<n>&side=<buy|sell>&order_type=<limit_order|market_order>
            [&limit_price=<price>]

    Results are aggregated across all positions.

    Args:
        positions: List of OpenAlgo-format position dicts
            {symbol, exchange, action, quantity, product, price, pricetype}
        auth (str): api_key stored in the OpenAlgo auth DB.

    Returns:
        Tuple of (MockResponse, response_data) matching OpenAlgo broker interface.
    """
    api_key = auth
    api_secret = os.getenv("BROKER_API_SECRET", "")

    class MockResponse:
        def __init__(self, code):
            self.status_code = code
            self.status = code

    if not api_key or not api_secret:
        return MockResponse(401), {
            "status": "error",
            "message": "BROKER_API_KEY / BROKER_API_SECRET not configured",
        }

    # Detect margin mode; log it so operators can see whether cross or isolated margin is active
    margin_mode = get_margin_mode(auth)
    logger.info(f"[DeltaExchange] Account margin mode: {margin_mode}")
    if margin_mode == "cross":
        logger.info(
            "[DeltaExchange] Cross-margin mode detected: available_margin represents total "
            "wallet balance shared across all positions, not per-position isolation."
        )

    transformed = transform_margin_positions(positions)

    if not transformed:
        return MockResponse(400), {
            "status": "error",
            "message": "No valid positions to calculate margin — check symbols are in master contract DB",
        }

    client = get_httpx_client()
    aggregated = {"total_margin_required": 0.0, "span_margin": 0.0, "exposure_margin": 0.0}
    failed = []
    ok_count = 0

    for pos in transformed:
        product_id = pos["product_id"]
        path = f"/v2/products/{product_id}/margin_required"

        # Build query string (must match signed string exactly)
        params = {
            "size": str(pos["size"]),
            "side": pos["side"],
            "order_type": pos["order_type"],
        }
        if "limit_price" in pos:
            params["limit_price"] = pos["limit_price"]

        query_string = "?" + "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        url = BASE_URL + path + query_string

        try:
            headers = get_auth_headers(
                method="GET",
                path=path,
                query_string=query_string,
                payload="",
                api_key=api_key,
                api_secret=api_secret,
            )

            response = client.get(url, headers=headers, timeout=30.0)
            response_data = response.json()

            logger.info(
                f"[DeltaExchange] margin_required product_id={product_id}: "
                f"HTTP {response.status_code}"
            )

            parsed = parse_margin_response(response_data)

            if parsed.get("status") == "success":
                d = parsed["data"]
                aggregated["total_margin_required"] += d.get("total_margin_required", 0)
                aggregated["span_margin"] += d.get("span_margin", 0)
                aggregated["exposure_margin"] += d.get("exposure_margin", 0)
                ok_count += 1
            else:
                logger.warning(
                    f"[DeltaExchange] margin_required failed for product_id={product_id}: "
                    f"{parsed.get('message')}"
                )
                failed.append(str(product_id))

        except Exception as e:
            logger.error(f"[DeltaExchange] Error fetching margin for product_id={product_id}: {e}")
            failed.append(str(product_id))

    if ok_count == 0:
        msg = f"Margin calculation failed for all positions."
        if failed:
            msg += f" Failed product_ids: {', '.join(failed)}"
        return MockResponse(500), {"status": "error", "message": msg}

    logger.info(
        f"[DeltaExchange] Margin aggregation done: {ok_count}/{len(transformed)} positions. "
        f"total_margin={aggregated['total_margin_required']:.2f}"
    )

    return MockResponse(200), {"status": "success", "data": aggregated}
