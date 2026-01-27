# Mapping OpenAlgo API Request https://openalgo.in/docs
# Mapping Upstox Margin API https://upstox.com/developer/api-documentation/margin

from broker.upstox.mapping.transform_data import map_product_type
from database.token_db import get_token
from utils.logging import get_logger

logger = get_logger(__name__)


def transform_margin_positions(positions):
    """
    Transform OpenAlgo margin position format to Upstox margin format.

    Args:
        positions: List of positions in OpenAlgo format

    Returns:
        List of positions in Upstox format
    """
    transformed_positions = []
    skipped_positions = []

    for position in positions:
        try:
            symbol = position["symbol"]
            exchange = position["exchange"]

            # Get the instrument key for Upstox (format: EXCHANGE_SEGMENT|TOKEN)
            # Note: get_token() returns instrument_key for Upstox, not get_br_symbol()
            instrument_key = get_token(symbol, exchange)

            # Validate instrument key exists and is not None
            if (
                not instrument_key
                or instrument_key is None
                or str(instrument_key).lower() == "none"
            ):
                logger.warning(f"Instrument key not found for: {symbol} on exchange: {exchange}")
                skipped_positions.append(f"{symbol} ({exchange})")
                continue

            # Validate instrument key format (Upstox format: EXCHANGE_SEGMENT|TOKEN)
            instrument_key_str = str(instrument_key).strip()
            if not instrument_key_str or "|" not in instrument_key_str:
                logger.warning(
                    f"Invalid instrument key format for {symbol} ({exchange}): '{instrument_key_str}'"
                )
                skipped_positions.append(
                    f"{symbol} ({exchange}) - invalid key: {instrument_key_str}"
                )
                continue

            # Transform the position
            transformed_position = {
                "instrument_key": instrument_key_str,
                "quantity": int(position["quantity"]),
                "transaction_type": position["action"].upper(),
                "product": map_product_type(position["product"]),
            }

            # Add price if provided (optional field)
            if position.get("price") and float(position["price"]) > 0:
                transformed_position["price"] = float(position["price"])

            transformed_positions.append(transformed_position)
            logger.debug(
                f"Successfully transformed position: {symbol} ({exchange}) with key: {instrument_key_str}"
            )

        except Exception as e:
            logger.error(f"Error transforming position: {position}, Error: {e}")
            skipped_positions.append(f"{position.get('symbol', 'unknown')} - Error: {str(e)}")
            continue

    # Log summary
    if skipped_positions:
        logger.warning(
            f"Skipped {len(skipped_positions)} position(s) due to missing/invalid instrument keys: {', '.join(skipped_positions)}"
        )

    if transformed_positions:
        logger.info(
            f"Successfully transformed {len(transformed_positions)} position(s) for margin calculation"
        )

    return transformed_positions


def parse_margin_response(response_data):
    """
    Parse Upstox margin response to OpenAlgo standard format.

    Args:
        response_data: Raw response from Upstox margin API

    Returns:
        Standardized margin response matching OpenAlgo format
    """
    try:
        if not response_data or not isinstance(response_data, dict):
            return {"status": "error", "message": "Invalid response from broker"}

        # Check if the response status is success
        if response_data.get("status") != "success":
            error_message = response_data.get("message", "Failed to calculate margin")
            # Check for errors array
            if "errors" in response_data:
                errors = response_data["errors"]
                if isinstance(errors, list) and len(errors) > 0:
                    error_message = errors[0].get("message", error_message)
            return {"status": "error", "message": error_message}

        # Extract margin data from Upstox response
        data = response_data.get("data", {})

        # Extract top-level margin values
        required_margin = data.get("required_margin", 0)
        final_margin = data.get("final_margin", 0)

        # Calculate margin benefit (difference between required and final margin)
        margin_benefit = required_margin - final_margin

        # Extract margin breakdown (array of margins per instrument)
        margins = data.get("margins", [])

        # Aggregate margin components from all instruments
        total_span = 0
        total_exposure = 0

        for margin in margins:
            total_span += margin.get("span_margin", 0)
            total_exposure += margin.get("exposure_margin", 0)

        # Return standardized format matching OpenAlgo API specification
        return {
            "status": "success",
            "data": {
                "total_margin_required": required_margin,
                "span_margin": total_span,
                "exposure_margin": total_exposure,
            },
        }

    except Exception as e:
        logger.error(f"Error parsing margin response: {e}")
        return {"status": "error", "message": f"Failed to parse margin response: {str(e)}"}
