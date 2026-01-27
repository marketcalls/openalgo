# Mapping OpenAlgo API Request https://openalgo.in/docs
# Mapping Groww Margin API

from broker.groww.mapping.transform_data import (
    map_order_type,
    map_product_type,
    map_segment_type,
    map_transaction_type,
)
from database.token_db import get_br_symbol
from utils.logging import get_logger

logger = get_logger(__name__)


def map_margin_exchange(exchange):
    """
    Maps the OpenAlgo Exchange to Groww Exchange values for margin API.
    Groww only accepts NSE/BSE - segment (CASH/FNO) is passed separately.
    """
    exchange_mapping = {
        "NSE": "NSE",
        "BSE": "BSE",
        "NFO": "NSE",  # F&O on NSE - segment=FNO handles the distinction
        "BFO": "BSE",  # F&O on BSE - segment=FNO handles the distinction
    }
    return exchange_mapping.get(exchange.upper(), "NSE")


def transform_margin_positions(positions):
    """
    Transform OpenAlgo margin positions to Groww margin format.

    Args:
        positions: List of positions in OpenAlgo format

    Returns:
        Tuple of (segment, transformed_positions_list)
        - segment: "CASH" or "FNO"
        - transformed_positions_list: List of positions in Groww format
    """
    transformed_positions = []
    segment = None

    for position in positions:
        try:
            symbol = position["symbol"]
            exchange = position["exchange"]

            # Determine segment from exchange
            position_segment = map_segment_type(exchange)

            # All positions in a request must be from the same segment
            if segment is None:
                segment = position_segment
            elif segment != position_segment:
                logger.warning(
                    f"Mixed segments detected. Groww only supports single segment per request. Using first segment: {segment}"
                )
                continue

            # Get broker symbol from database (Groww uses different symbol format)
            broker_symbol = get_br_symbol(symbol, exchange)
            if not broker_symbol:
                logger.warning(
                    f"Broker symbol not found for {symbol} on {exchange}, using original symbol"
                )
                broker_symbol = symbol

            # Transform the position
            transformed_position = {
                "trading_symbol": broker_symbol,
                "transaction_type": map_transaction_type(position["action"]),
                "quantity": int(position["quantity"]),
                "order_type": map_order_type(position["pricetype"]),
                "product": map_product_type(position["product"]),
                "exchange": map_margin_exchange(exchange),
            }

            # Add price if provided (for LIMIT orders)
            if position.get("price") and float(position["price"]) > 0:
                transformed_position["price"] = float(position["price"])

            transformed_positions.append(transformed_position)

        except Exception as e:
            logger.error(f"Error transforming position: {position}, Error: {e}")
            continue

    # Default to CASH if no positions were successfully transformed
    if segment is None:
        segment = "CASH"

    return segment, transformed_positions


def parse_margin_response(response_data):
    """
    Parse Groww margin response to OpenAlgo standard format.

    Args:
        response_data: Raw response from Groww API

    Returns:
        Standardized margin response
    """
    try:
        if not response_data or not isinstance(response_data, dict):
            return {"status": "error", "message": "Invalid response from broker"}

        # Check if the response status is SUCCESS
        if response_data.get("status") != "SUCCESS":
            error_message = response_data.get("message", "Failed to calculate margin")
            # Check for errors array
            if "errors" in response_data and isinstance(response_data["errors"], list):
                if len(response_data["errors"]) > 0:
                    error_message = response_data["errors"][0].get("message", error_message)
            return {"status": "error", "message": error_message}

        # Extract margin data from payload
        payload = response_data.get("payload", {})

        # Calculate total margin
        total_requirement = float(payload.get("total_requirement", 0))

        # Return standardized format matching OpenAlgo API specification
        return {
            "status": "success",
            "data": {
                "total_margin_required": total_requirement,
                "span_margin": float(payload.get("span_required") or 0),
                "exposure_margin": float(payload.get("exposure_required") or 0),
            },
        }

    except Exception as e:
        logger.error(f"Error parsing margin response: {e}")
        return {"status": "error", "message": f"Failed to parse margin response: {str(e)}"}
