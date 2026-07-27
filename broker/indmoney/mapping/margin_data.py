# Mapping OpenAlgo API Request https://openalgo.in/docs
# Mapping IndMoney Margin API https://api.indstocks.com/margin

from database.token_db import get_token
from utils.logging import get_logger

logger = get_logger(__name__)


def transform_margin_positions(positions):
    """
    Transform OpenAlgo margin position format to IndMoney margin format.

    Note: IndMoney margin API calculates margin for single orders only,
    not batch calculations like Angel Broking.

    Args:
        positions: List of positions in OpenAlgo format

    Returns:
        List of positions in IndMoney format
    """
    transformed_positions = []
    skipped_positions = []

    for position in positions:
        try:
            symbol = position["symbol"]
            exchange = position["exchange"]

            # Get the token (securityID) for the symbol
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

            # Transform the position to IndMoney margin API format
            transformed_position = {
                "segment": map_segment(exchange),
                "txnType": position["action"].upper(),  # BUY/SELL
                "quantity": str(position["quantity"]),  # String as per API spec
                "price": str(position.get("price", 0)),  # String as per API spec
                "product": map_product_type(position["product"]),
                "securityID": token_str,
                "exchange": map_exchange_type(exchange),
            }

            transformed_positions.append(transformed_position)
            logger.debug(
                f"Successfully transformed position: {symbol} ({exchange}) with securityID: {token_str}"
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


def map_segment(exchange):
    """
    Maps OpenAlgo exchange to IndMoney segment.

    OpenAlgo: NSE, BSE, NFO, BFO, CDS, BCD, MCX
    IndMoney: DERIVATIVE, EQUITY
    """
    segment_mapping = {
        "NSE": "EQUITY",
        "BSE": "EQUITY",
        "NFO": "DERIVATIVE",
        "BFO": "DERIVATIVE",
        "CDS": "DERIVATIVE",
        "BCD": "DERIVATIVE",
        "MCX": "DERIVATIVE",
    }
    return segment_mapping.get(exchange, "EQUITY")


def map_exchange_type(exchange):
    """
    Maps OpenAlgo exchange to IndMoney exchange format.

    OpenAlgo: NSE, BSE, NFO, BFO, CDS, BCD, MCX
    IndMoney: NSE, BSE
    """
    exchange_mapping = {
        "NSE": "NSE",
        "BSE": "BSE",
        "NFO": "NSE",
        "BFO": "BSE",
        "CDS": "NSE",
        "BCD": "BSE",
        "MCX": "MCX",
    }
    return exchange_mapping.get(exchange, "NSE")


def map_product_type(product):
    """
    Maps OpenAlgo product type to IndMoney product type.

    OpenAlgo: CNC, NRML, MIS
    IndMoney: MARGIN, INTRADAY, CNC
    """
    product_type_mapping = {
        "CNC": "CNC",
        "NRML": "MARGIN",
        "MIS": "INTRADAY",
    }
    return product_type_mapping.get(product, "INTRADAY")


def parse_margin_response(response_data):
    """
    Parse IndMoney margin calculator response to OpenAlgo standard format.

    Args:
        response_data: Raw response from IndMoney margin calculator API

    Returns:
        Standardized margin response matching OpenAlgo format
    """
    try:
        if not response_data or not isinstance(response_data, dict):
            return {"status": "error", "message": "Invalid response from broker"}

        # Check if the response has the expected structure
        if response_data.get("status") == "error":
            return {
                "status": "error",
                "message": response_data.get("message", "Failed to calculate margin"),
            }

        # Extract margin data from IndMoney's margin calculator response
        data = response_data.get("data", {})

        # Extract only the three required values as per OpenAlgo API specification
        total_margin = data.get("total_margin", 0)
        span_margin = data.get("span_margin", 0)
        exposure_margin = data.get("exposure_margin", 0)

        # Return standardized format matching OpenAlgo API specification
        # Only return the three essential margin fields
        return {
            "status": "success",
            "data": {
                "total_margin_required": total_margin,
                "span_margin": span_margin,
                "exposure_margin": exposure_margin,
            },
        }

    except Exception as e:
        logger.error(f"Error parsing margin response: {e}")
        return {"status": "error", "message": f"Failed to parse margin response: {str(e)}"}
