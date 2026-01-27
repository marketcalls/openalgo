# Mapping OpenAlgo API Request https://openalgo.in/docs
# Mapping Dhan Sandbox Margin API https://dhanhq.co/docs/v2/funds/

from broker.dhan_sandbox.mapping.transform_data import (
    map_exchange_type,
    map_order_type,
    map_product_type,
)
from database.token_db import get_token
from utils.logging import get_logger

logger = get_logger(__name__)


def transform_margin_position(position, client_id):
    """
    Transform a single OpenAlgo margin position to Dhan Sandbox margin format.

    Note: Dhan Sandbox margin calculator API accepts only one order at a time, not a batch.

    Args:
        position: Position in OpenAlgo format
        client_id: Dhan client ID

    Returns:
        Dict in Dhan Sandbox margin format or None if transformation fails
    """
    try:
        # Get the token for the symbol
        token = get_token(position["symbol"], position["exchange"])

        if not token:
            logger.warning(
                f"Token not found for symbol: {position['symbol']} on exchange: {position['exchange']}"
            )
            return None

        # Map exchange segment
        exchange_segment = map_exchange_type(position["exchange"])
        if not exchange_segment:
            logger.warning(f"Invalid exchange: {position['exchange']}")
            return None

        # Transform the position
        transformed = {
            "dhanClientId": client_id,
            "exchangeSegment": exchange_segment,
            "transactionType": position["action"].upper(),
            "quantity": int(position["quantity"]),
            "productType": map_product_type_for_margin(position["product"]),
            "securityId": str(token),
            "price": float(position.get("price", 0)),
        }

        # Add trigger price if present
        trigger_price = position.get("trigger_price", 0)
        if trigger_price and float(trigger_price) > 0:
            transformed["triggerPrice"] = float(trigger_price)

        return transformed

    except Exception as e:
        logger.error(f"Error transforming position: {position}, Error: {e}")
        return None


def map_product_type_for_margin(product):
    """
    Maps OpenAlgo product type to Dhan Sandbox product type for margin calculation.

    OpenAlgo: CNC, NRML, MIS
    Dhan Sandbox: CNC, MARGIN, INTRADAY, MTF, CO, BO
    """
    product_type_mapping = {
        "CNC": "CNC",
        "NRML": "MARGIN",
        "MIS": "INTRADAY",
    }
    return product_type_mapping.get(product, "INTRADAY")


def parse_margin_response(response_data):
    """
    Parse Dhan Sandbox margin response to OpenAlgo standard format.

    Args:
        response_data: Raw response from Dhan Sandbox API

    Returns:
        Standardized margin response
    """
    try:
        if not response_data or not isinstance(response_data, dict):
            return {"status": "error", "message": "Invalid response from broker"}

        # Check for error response
        if response_data.get("errorType") or response_data.get("status") == "failed":
            error_message = response_data.get("errorMessage", "Failed to calculate margin")
            return {"status": "error", "message": error_message}

        # Return standardized format with Dhan Sandbox-specific fields
        return {
            "status": "success",
            "data": {
                "total_margin_required": response_data.get("totalMargin", 0),
                "span_margin": response_data.get("spanMargin", 0),
                "exposure_margin": response_data.get("exposureMargin", 0),
                "available_balance": response_data.get("availableBalance", 0),
                "variable_margin": response_data.get("variableMargin", 0),
                "insufficient_balance": response_data.get("insufficientBalance", 0),
                "brokerage": response_data.get("brokerage", 0),
                "leverage": response_data.get("leverage", "1.00"),
                "raw_response": response_data,  # Include raw response for debugging
            },
        }

    except Exception as e:
        logger.error(f"Error parsing margin response: {e}")
        return {"status": "error", "message": f"Failed to parse margin response: {str(e)}"}


def parse_batch_margin_response(responses):
    """
    Parse multiple Dhan Sandbox margin responses and aggregate them.

    Args:
        responses: List of individual margin responses

    Returns:
        Aggregated margin response
    """
    try:
        total_margin = 0
        total_span = 0
        total_exposure = 0
        total_brokerage = 0
        available_balance = 0
        insufficient_balance = 0
        all_responses = []

        for response in responses:
            if response.get("status") == "success":
                data = response.get("data", {})
                total_margin += data.get("total_margin_required", 0)
                total_span += data.get("span_margin", 0)
                total_exposure += data.get("exposure_margin", 0)
                total_brokerage += data.get("brokerage", 0)
                # Take the max available balance (it should be same for all)
                available_balance = max(available_balance, data.get("available_balance", 0))
                all_responses.append(data.get("raw_response", {}))

        # Calculate total insufficient balance
        insufficient_balance = max(0, total_margin - available_balance)

        return {
            "status": "success",
            "data": {
                "total_margin_required": total_margin,
                "span_margin": total_span,
                "exposure_margin": total_exposure,
                "available_balance": available_balance,
                "total_brokerage": total_brokerage,
                "insufficient_balance": insufficient_balance,
                "total_positions": len(responses),
                "individual_margins": all_responses,
            },
        }

    except Exception as e:
        logger.error(f"Error parsing batch margin response: {e}")
        return {"status": "error", "message": f"Failed to parse batch margin response: {str(e)}"}
