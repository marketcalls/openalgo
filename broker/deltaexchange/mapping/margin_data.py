# mapping/margin_data.py
# Mapping OpenAlgo margin positions to Delta Exchange margin_required API format
# Delta Exchange endpoint: GET /v2/products/{product_id}/margin_required

from database.token_db import get_token
from utils.logging import get_logger

logger = get_logger(__name__)


def transform_margin_positions(positions):
    """
    Transform OpenAlgo margin position list to Delta Exchange format.

    Each OpenAlgo position is converted to a dict with the fields needed
    to call GET /v2/products/{product_id}/margin_required:
        product_id  (int)  – from token DB (token = product_id on Delta)
        size        (int)  – absolute quantity
        side        (str)  – "buy" or "sell"
        order_type  (str)  – "limit_order" or "market_order"
        limit_price (str)  – required if order_type == "limit_order"

    Args:
        positions: List of dicts in OpenAlgo format
            {symbol, exchange, action (BUY/SELL), quantity, product,
             price (optional), pricetype (optional)}

    Returns:
        List of dicts in Delta Exchange margin format, skipping invalid entries.
    """
    transformed = []
    skipped = []

    for pos in positions:
        try:
            symbol = pos["symbol"]
            exchange = pos.get("exchange", "CRYPTO")

            # token == product_id on Delta Exchange
            token = get_token(symbol, exchange)
            if not token:
                logger.warning(f"Token not found for {symbol} on {exchange}")
                skipped.append(symbol)
                continue

            product_id = int(token)
            side = pos["action"].lower()  # "buy" or "sell"

            pricetype = pos.get("pricetype", "MARKET").upper()
            if pricetype in ("LIMIT", "SL"):
                order_type = "limit_order"
            else:
                order_type = "market_order"

            entry = {
                "product_id": product_id,
                "size": int(pos["quantity"]),
                "side": side,
                "order_type": order_type,
            }

            price = pos.get("price", 0)
            if order_type == "limit_order" and price:
                entry["limit_price"] = str(price)

            transformed.append(entry)
            logger.debug(
                f"Transformed margin position: {symbol} → product_id={product_id} "
                f"size={entry['size']} side={side}"
            )

        except Exception as e:
            logger.error(f"Error transforming margin position {pos}: {e}")
            skipped.append(str(pos.get("symbol", "unknown")))

    if skipped:
        logger.warning(f"Skipped {len(skipped)} position(s): {', '.join(skipped)}")

    return transformed


def parse_margin_response(response_data):
    """
    Parse the Delta Exchange GET /v2/products/{product_id}/margin_required response.

    Expected response shape:
        {
          "success": true,
          "result": {
            "initial_margin":      "500.00",   // margin required to open
            "maintenance_margin":  "250.00",   // margin to keep position open
            "order_size":          10
          }
        }

    OpenAlgo margin format (3 fields):
        total_margin_required  ← initial_margin
        span_margin            ← initial_margin  (Delta has no SPAN concept; use same)
        exposure_margin        ← 0.00            (no separate exposure on crypto)

    Returns:
        {"status": "success", "data": {...}} or {"status": "error", "message": ...}
    """
    try:
        if not response_data or not isinstance(response_data, dict):
            return {"status": "error", "message": "Invalid response from Delta Exchange"}

        if not response_data.get("success", False):
            error = response_data.get("error", {})
            msg = error.get("message", "Unknown error") if isinstance(error, dict) else str(error)
            return {"status": "error", "message": msg}

        result = response_data.get("result", {})
        if not isinstance(result, dict):
            return {"status": "error", "message": "Unexpected margin result format"}

        initial_margin = _f(result.get("initial_margin", 0))

        return {
            "status": "success",
            "data": {
                "total_margin_required": initial_margin,
                "span_margin": initial_margin,
                "exposure_margin": 0.0,
            },
        }

    except Exception as e:
        logger.error(f"Error parsing margin_required response: {e}")
        return {"status": "error", "message": f"Failed to parse margin response: {e}"}


def _f(value):
    """Safe float conversion."""
    try:
        return float(value or 0)
    except (ValueError, TypeError):
        return 0.0
