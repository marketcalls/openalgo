# Mapping OpenAlgo API Request https://openalgo.in/docs
# Mapping mStock Type B Margin API https://tradingapi.mstock.com/docs/v1/typeB/Margins/

from database.token_db import get_br_symbol, get_token
from utils.logging import get_logger

logger = get_logger(__name__)


def transform_margin_positions(positions):
    """
    Transform OpenAlgo margin position format to mStock Type B margin format.

    Args:
        positions: List of positions in OpenAlgo format

    Returns:
        List of positions in mStock Type B format
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

            # Validate token is a valid number/string
            token_str = str(token).strip()
            if not token_str or not token_str.replace(".", "").replace("-", "").isdigit():
                logger.warning(f"Invalid token format for {symbol} ({exchange}): '{token_str}'")
                skipped_positions.append(f"{symbol} ({exchange}) - invalid token: {token_str}")
                continue

            # Get broker symbol for mStock
            symbol_name = get_br_symbol(symbol, exchange)

            # Transform the position to mStock Type B format
            transformed_position = {
                "product_type": map_product_type(position["product"]),
                "transaction_type": position["action"].upper(),
                "quantity": str(position["quantity"]),
                "price": str(position.get("price", "0")),
                "exchange": exchange,
                "symbol_name": symbol_name,
                "token": token_str,
                "trigger_price": float(position.get("trigger_price", 0)),
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
    Maps OpenAlgo product type to mStock Type B product type.

    OpenAlgo: CNC, NRML, MIS
    mStock: DELIVERY, CARRYFORWARD, INTRADAY, MARGIN
    """
    product_type_mapping = {
        "CNC": "DELIVERY",
        "NRML": "CARRYFORWARD",
        "MIS": "INTRADAY",
    }
    return product_type_mapping.get(product, "INTRADAY")


def parse_margin_response(response_data):
    """
    Parse mStock Type B margin calculator response to OpenAlgo standard format.

    Args:
        response_data: Raw response from mStock Type B margin calculator API

    Returns:
        Standardized margin response matching OpenAlgo format
    """
    try:
        if not response_data or not isinstance(response_data, dict):
            return {"status": "error", "message": "Invalid response from broker"}

        # Check if the response has the expected structure
        # mStock returns status as "true"/"false" string or boolean
        if response_data.get("status") not in [True, "true"]:
            return {
                "status": "error",
                "message": response_data.get("message", "Failed to calculate margin"),
            }

        # Extract margin data from mStock's response
        data = response_data.get("data", {})
        summary = data.get("summary", {})

        # Get total charges (total margin required)
        total_margin_required = summary.get("total_charges", 0)

        # Extract SPAN and exposure margins from breakup
        span_margin = 0
        exposure_margin = 0

        breakup = summary.get("breakup", [])
        for item in breakup:
            if item.get("name") == "SPANMARGIN":
                span_margin = item.get("amount", 0)
            elif item.get("name") == "EXPOMARGIN":
                exposure_margin = item.get("amount", 0)

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
