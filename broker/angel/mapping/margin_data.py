# Mapping OpenAlgo API Request https://openalgo.in/docs
# Mapping Angel Broking Margin API https://smartapi.angelbroking.com/docs/Margin

from database.token_db import get_token
from utils.logging import get_logger

logger = get_logger(__name__)


def transform_margin_positions(positions):
    """
    Transform OpenAlgo margin position format to Angel Broking margin format.

    Args:
        positions: List of positions in OpenAlgo format

    Returns:
        List of positions in Angel Broking format
    """
    transformed_positions = []
    skipped_positions = []

    for position in positions:
        try:
            symbol = position["symbol"]
            exchange = position["exchange"]

            # Get the token for the symbol
            token = get_token(symbol, exchange)

            # Validate token exists and is not None
            if not token or token is None or str(token).lower() == "none":
                logger.warning(f"Token not found for symbol: {symbol} on exchange: {exchange}")
                skipped_positions.append(f"{symbol} ({exchange})")
                continue

            # Validate token is a valid number/string (Angel expects numeric token)
            token_str = str(token).strip()
            if not token_str or not token_str.replace(".", "").replace("-", "").isdigit():
                logger.warning(f"Invalid token format for {symbol} ({exchange}): '{token_str}'")
                skipped_positions.append(f"{symbol} ({exchange}) - invalid token: {token_str}")
                continue

            # Transform the position
            transformed_position = {
                "exchange": exchange,
                "qty": int(position["quantity"]),
                "price": float(position.get("price", 0)),
                "productType": map_product_type(position["product"]),
                "token": token_str,
                "tradeType": position["action"].upper(),
                "orderType": map_order_type(position["pricetype"]),
            }

            transformed_positions.append(transformed_position)
            logger.debug(
                f"Successfully transformed position: {symbol} ({exchange}) with token: {token_str}"
            )

        except Exception as e:
            logger.error(f"Error transforming position: {position}, Error: {e}")
            skipped_positions.append(f"{position.get('symbol', 'unknown')} - Error: {str(e)}")
            continue

    # Log summary
    if skipped_positions:
        logger.warning(
            f"Skipped {len(skipped_positions)} position(s) due to missing/invalid tokens: {', '.join(skipped_positions)}"
        )

    if transformed_positions:
        logger.info(
            f"Successfully transformed {len(transformed_positions)} position(s) for margin calculation"
        )

    return transformed_positions


def map_product_type(product):
    """
    Maps OpenAlgo product type to Angel Broking product type.

    OpenAlgo: CNC, NRML, MIS
    Angel: DELIVERY, CARRYFORWARD, INTRADAY, MARGIN
    """
    product_type_mapping = {
        "CNC": "DELIVERY",
        "NRML": "CARRYFORWARD",
        "MIS": "INTRADAY",
    }
    return product_type_mapping.get(product, "INTRADAY")


def map_order_type(pricetype):
    """
    Maps OpenAlgo price type to Angel Broking order type.

    OpenAlgo: MARKET, LIMIT, SL, SL-M
    Angel: MARKET, LIMIT, STOPLOSS_LIMIT, STOPLOSS_MARKET
    """
    order_type_mapping = {
        "MARKET": "MARKET",
        "LIMIT": "LIMIT",
        "SL": "STOPLOSS_LIMIT",
        "SL-M": "STOPLOSS_MARKET",
    }
    return order_type_mapping.get(pricetype, "MARKET")


def parse_margin_response(response_data):
    """
    Parse Angel Broking margin calculator response to OpenAlgo standard format.

    Args:
        response_data: Raw response from Angel Broking margin calculator API

    Returns:
        Standardized margin response matching OpenAlgo format
    """
    try:
        if not response_data or not isinstance(response_data, dict):
            return {"status": "error", "message": "Invalid response from broker"}

        # Check if the response has the expected structure
        if response_data.get("status") is False:
            return {
                "status": "error",
                "message": response_data.get("message", "Failed to calculate margin"),
            }

        # Extract margin data from Angel's margin calculator response
        data = response_data.get("data", {})
        margin_components = data.get("marginComponents", {})

        # Extract values from Angel's response
        total_margin_required = data.get("totalMarginRequired", 0)
        span_margin = margin_components.get("spanMargin", 0)

        # Angel API doesn't provide exposure margin explicitly, so set it to 0
        exposure_margin = 0

        # Return standardized format matching OpenAlgo API specification
        return {
            "status": "success",
            "data": {
                "total_margin_required": total_margin_required,
                "span_margin": span_margin,
                "exposure_margin": exposure_margin,
            },
        }

    except Exception as e:
        logger.error(f"Error parsing margin response: {e}")
        return {"status": "error", "message": f"Failed to parse margin response: {str(e)}"}
