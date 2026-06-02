# Mapping OpenAlgo API Request https://openalgo.in/docs
# Mapping Dhan Margin API https://dhanhq.co/docs/v2/funds/

from broker.dhan.mapping.transform_data import map_exchange_type
from database.token_db import get_token
from utils.logging import get_logger

logger = get_logger(__name__)


def transform_margin_position(position, client_id):
    """
    Transform a single OpenAlgo margin position to Dhan margin format.

    Args:
        position: Position in OpenAlgo format
        client_id: Dhan client ID

    Returns:
        Dict in Dhan margin format or None if transformation fails
    """
    try:
        token = get_token(position["symbol"], position["exchange"])

        if not token:
            logger.warning(
                f"Token not found for symbol: {position['symbol']} on exchange: {position['exchange']}"
            )
            return None

        exchange_segment = map_exchange_type(position["exchange"])
        if not exchange_segment:
            logger.warning(f"Invalid exchange: {position['exchange']}")
            return None

        transformed = {
            "dhanClientId": client_id,
            "exchangeSegment": exchange_segment,
            "transactionType": position["action"].upper(),
            "quantity": int(position["quantity"]),
            "productType": map_product_type_for_margin(position["product"]),
            "securityId": str(token),
            "price": float(position.get("price", 0)),
        }

        trigger_price = position.get("trigger_price", 0)
        if trigger_price and float(trigger_price) > 0:
            transformed["triggerPrice"] = float(trigger_price)

        return transformed

    except Exception as e:
        logger.error(f"Error transforming position: {position}, Error: {e}")
        return None


def map_product_type_for_margin(product):
    """
    Maps OpenAlgo product type to Dhan product type for margin calculation.

    OpenAlgo: CNC, NRML, MIS
    Dhan: CNC, MARGIN, INTRADAY, MTF, CO, BO
    """
    product_type_mapping = {
        "CNC": "CNC",
        "NRML": "MARGIN",
        "MIS": "INTRADAY",
    }
    return product_type_mapping.get(product, "INTRADAY")


def parse_margin_response(response_data):
    """
    Parse Dhan single-order margin response to OpenAlgo standard format.

    Args:
        response_data: Raw response from Dhan API

    Returns:
        Standardized margin response matching OpenAlgo RESTX margin format
    """
    try:
        if not response_data or not isinstance(response_data, dict):
            return {"status": "error", "message": "Invalid response from broker"}

        status = str(response_data.get("status", "")).lower()
        if response_data.get("errorType") or status in {"error", "failed", "failure"}:
            error_message = (
                response_data.get("errorMessage")
                or response_data.get("message")
                or response_data.get("errors")
                or "Failed to calculate margin"
            )
            return {"status": "error", "message": str(error_message)}

        total_margin = float(response_data.get("totalMargin", 0))
        span_margin = float(response_data.get("spanMargin", 0))
        exposure_margin = float(response_data.get("exposureMargin", 0))

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
