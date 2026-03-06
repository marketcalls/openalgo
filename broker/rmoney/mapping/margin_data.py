# Mapping OpenAlgo API Request https://openalgo.in/docs
# RMoney XTS Margin Calculator API mappings

from broker.rmoney.mapping.transform_data import map_exchange_numeric, map_order_type, map_product_type
from database.token_db import get_token
from utils.logging import get_logger

logger = get_logger(__name__)


def _safe_float(value, field_name, default=0.0):
    try:
        return float(value if value is not None else default)
    except (TypeError, ValueError):
        logger.warning(f"Invalid RMoney margin field {field_name}: {value!r}. Using {default}.")
        return float(default)


def transform_margin_positions(positions):
    """
    Transform OpenAlgo margin position format to RMoney XTS margin API format.

    RMoney XTS Regular Order Margin API expects a portfolio array with:
    - exchange: Numeric exchange segment code (e.g., 1 for NSECM, 2 for NSEFO)
    - exchangeInstrumentId: Token for the instrument
    - productType: Product type string (MIS, NRML, CNC)
    - orderType: Order type string (MARKET, LIMIT, STOPLIMIT, STOPMARKET)
    - orderSide: Order side string (BUY, SELL)
    - quantity: Order quantity
    - price: Limit price (0 for market orders)
    - stopPrice: Stop loss trigger price (0 for non-SL orders)
    - orderSessionType: Order session type (1 = DAY)

    Args:
        positions: List of positions in OpenAlgo format

    Returns:
        List of positions in RMoney XTS portfolio format
    """
    transformed_positions = []
    skipped_positions = []

    for position in positions:
        try:
            symbol = position.get("symbol")
            exchange = position.get("exchange")

            # Get token for the symbol
            token = get_token(symbol, exchange)

            if not token:
                logger.warning(f"Token not found for: {symbol} on {exchange}")
                skipped_positions.append(f"{symbol} ({exchange})")
                continue

            # Build the transformed position
            transformed = {
                "exchange": map_exchange_numeric(exchange),
                "exchangeInstrumentId": int(token),
                "productType": map_product_type(position.get("product", "MIS")),
                "orderType": map_order_type(position.get("pricetype", "MARKET")),
                "orderSide": position.get("action", "BUY").upper(),
                "quantity": int(position.get("quantity", 1)),
                "price": float(position.get("price", 0)),
                "stopPrice": float(position.get("trigger_price", 0)),
                "orderSessionType": 1,  # DAY
            }

            transformed_positions.append(transformed)
            logger.debug(f"Transformed position: {symbol} ({exchange}) -> token={token}")

        except Exception as e:
            logger.error(f"Error transforming position {position}: {e}")
            skipped_positions.append(f"{position.get('symbol', 'unknown')} - Error: {str(e)}")
            continue

    if skipped_positions:
        logger.warning(
            f"Skipped {len(skipped_positions)} position(s): {', '.join(skipped_positions)}"
        )

    return transformed_positions


def parse_margin_response(response_data):
    """
    Parse RMoney XTS margin calculator response to OpenAlgo standard format.

    RMoney Response Structure:
    {
        "type": "success",
        "code": "s-calculatemargin-0001",
        "description": "Request sent",
        "result": {
            "brokerageDeatils": {
                "IsValid": true,
                "MarginRequired": 150,
                "MarginAvailable": 9816624.5775,
                "MarginShortfall": 0,
                "ErrorMessage": ""
            }
        }
    }

    Args:
        response_data: Raw response from RMoney XTS margin calculator API

    Returns:
        dict: Parsed margin data in OpenAlgo format
    """
    if not response_data or not isinstance(response_data, dict):
        return {
            "status": "error",
            "message": "Invalid response from broker",
        }

    if response_data.get("type") != "success":
        return {
            "status": "error",
            "message": response_data.get("description", "Unknown error"),
        }

    brokerage_details = response_data.get("result", {}).get("brokerageDeatils", {})

    if not brokerage_details:
        return {
            "status": "error",
            "message": "No margin details in response",
        }

    margin_required = _safe_float(brokerage_details.get("MarginRequired", 0), "MarginRequired")
    margin_available = _safe_float(brokerage_details.get("MarginAvailable", 0), "MarginAvailable")
    margin_shortfall = _safe_float(
        brokerage_details.get("MarginShortfall", 0), "MarginShortfall"
    )
    is_valid = brokerage_details.get("IsValid", False)
    error_message = brokerage_details.get("ErrorMessage", "")

    logger.info("=" * 60)
    logger.info("RMONEY MARGIN CALCULATION RESULT")
    logger.info("=" * 60)
    logger.info(f"  IsValid:         {is_valid}")
    logger.info(f"  MarginRequired:  Rs. {margin_required:,.2f}")
    logger.info(f"  MarginAvailable: Rs. {margin_available:,.2f}")
    logger.info(f"  MarginShortfall: Rs. {margin_shortfall:,.2f}")
    if error_message:
        logger.info(f"  ErrorMessage:    {error_message}")
    logger.info("=" * 60)

    return {
        "status": "success",
        "data": {
            "total_margin_required": margin_required,
            "margin_available": margin_available,
            "margin_shortfall": margin_shortfall,
            "is_valid": is_valid,
            "error_message": error_message,
        },
    }
