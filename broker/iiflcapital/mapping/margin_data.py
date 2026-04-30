# Mapping OpenAlgo API Request https://openalgo.in/docs
# Mapping IIFL Capital SPAN and Exposure Margin API

from broker.iiflcapital.mapping.transform_data import map_exchange
from database.token_db import get_token
from utils.logging import get_logger

logger = get_logger(__name__)


def transform_margin_positions(positions):
    """
    Transform OpenAlgo margin positions to IIFL Capital span/exposure format.

    Args:
        positions: List of positions in OpenAlgo format

    Returns:
        List of positions in IIFL Capital format
    """
    transformed_positions = []
    skipped_positions = []

    for position in positions:
        try:
            symbol = position["symbol"]
            exchange = position["exchange"]
            action = str(position["action"]).upper()
            quantity = int(float(position["quantity"]))

            token = get_token(symbol, exchange)
            if token in (None, "", "None"):
                logger.warning(f"Token not found for symbol: {symbol} on exchange: {exchange}")
                skipped_positions.append(f"{symbol} ({exchange})")
                continue

            if action not in {"BUY", "SELL"}:
                logger.warning(f"Invalid action for margin position {symbol} ({exchange}): {action}")
                skipped_positions.append(f"{symbol} ({exchange}) - invalid action: {action}")
                continue

            if quantity <= 0:
                logger.warning(f"Invalid quantity for margin position {symbol} ({exchange}): {quantity}")
                skipped_positions.append(f"{symbol} ({exchange}) - invalid quantity: {quantity}")
                continue

            transformed_positions.append(
                {
                    "instrumentId": str(token),
                    "exchange": map_exchange(exchange),
                    "transactionType": action,
                    "quantity": quantity,
                }
            )

        except Exception as error:
            logger.error(f"Error transforming margin position: {position}, Error: {error}")
            skipped_positions.append(
                f"{position.get('symbol', 'unknown')} ({position.get('exchange', 'unknown')})"
            )

    if skipped_positions:
        logger.warning(
            "Skipped %s margin position(s): %s",
            len(skipped_positions),
            ", ".join(skipped_positions),
        )

    if transformed_positions:
        logger.info(
            "Successfully transformed %s position(s) for IIFL Capital margin calculation",
            len(transformed_positions),
        )

    return transformed_positions


def parse_margin_response(response_data):
    """
    Parse IIFL Capital span/exposure response to OpenAlgo standard format.

    Args:
        response_data: Raw response from IIFL Capital margin API

    Returns:
        Standardized margin response matching OpenAlgo format
    """
    try:
        if not response_data or not isinstance(response_data, dict):
            return {"status": "error", "message": "Invalid response from broker"}

        status = str(response_data.get("status", "")).lower()
        if status == "error":
            return {
                "status": "error",
                "message": response_data.get("message", "Failed to calculate margin"),
            }

        result = response_data.get("result", response_data)
        if not isinstance(result, dict):
            return {"status": "error", "message": "Invalid margin payload from broker"}

        span_margin = _safe_float(result.get("span", 0))
        exposure_margin = _safe_float(result.get("exposureMargin", 0))
        total_margin_required = _safe_float(
            result.get("totalMargin", span_margin + exposure_margin)
        )

        return {
            "status": "success",
            "data": {
                "total_margin_required": total_margin_required,
                "span_margin": span_margin,
                "exposure_margin": exposure_margin,
                "margin_benefit": 0.0,
            },
        }

    except Exception as error:
        logger.error(f"Error parsing IIFL Capital margin response: {error}")
        return {"status": "error", "message": f"Failed to parse margin response: {error}"}


def _safe_float(value, default=0.0):
    """Convert broker values to float safely."""
    if value in (None, ""):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
