# Mapping OpenAlgo API Request https://openalgo.in/docs
# Mapping Fyers Margin API

from broker.fyers.mapping.transform_data import map_action, map_order_type, map_product_type
from database.token_db import get_br_symbol
from utils.logging import get_logger

logger = get_logger(__name__)


def transform_margin_positions(positions):
    """
    Transform OpenAlgo margin position format to Fyers margin format.

    OpenAlgo Format:
    {
        "symbol": "NIFTY",
        "exchange": "NSE",
        "action": "BUY",
        "quantity": 50,
        "pricetype": "MARKET",
        "product": "NRML",
        "price": 0,
        "trigger_price": 0
    }

    Fyers Format:
    {
        "symbol": "NSE:NIFTY23DECFUT",
        "qty": 50,
        "side": 1,  # 1=Buy, -1=Sell
        "type": 2,  # 1=Limit, 2=Market, 3=SL-M, 4=SL-L
        "productType": "MARGIN",
        "limitPrice": 0.0,
        "stopLoss": 0.0,
        "stopPrice": 0.0,
        "takeProfit": 0.0
    }

    Args:
        positions: List of positions in OpenAlgo format

    Returns:
        List of positions in Fyers format
    """
    transformed_positions = []
    skipped_positions = []

    for position in positions:
        try:
            symbol = position["symbol"]
            exchange = position["exchange"]

            # Get the broker symbol for Fyers
            br_symbol = get_br_symbol(symbol, exchange)

            # Validate symbol exists and is not None
            if not br_symbol or br_symbol is None or str(br_symbol).lower() == "none":
                logger.warning(f"Symbol not found for: {symbol} on exchange: {exchange}")
                skipped_positions.append(f"{symbol} ({exchange})")
                continue

            # Validate symbol is a valid string
            br_symbol_str = str(br_symbol).strip()
            if not br_symbol_str:
                logger.warning(
                    f"Invalid symbol format for {symbol} ({exchange}): '{br_symbol_str}'"
                )
                skipped_positions.append(f"{symbol} ({exchange}) - invalid symbol: {br_symbol_str}")
                continue

            # Transform the position
            transformed_position = {
                "symbol": br_symbol_str,
                "qty": int(position["quantity"]),
                "side": map_action(position["action"].upper()),
                "type": map_order_type(position["pricetype"]),
                "productType": map_product_type(position["product"]),
                "limitPrice": float(position.get("price", 0.0)),
                "stopLoss": 0.0,
                "stopPrice": float(position.get("trigger_price", 0.0)),
                "takeProfit": 0.0,
            }

            transformed_positions.append(transformed_position)
            logger.debug(
                f"Successfully transformed position: {symbol} ({exchange}) -> {br_symbol_str}"
            )

        except Exception as e:
            logger.error(f"Error transforming position: {position}, Error: {e}")
            skipped_positions.append(f"{position.get('symbol', 'unknown')} - Error: {str(e)}")
            continue

    # Log summary
    if skipped_positions:
        logger.warning(
            f"Skipped {len(skipped_positions)} position(s) due to missing/invalid symbols: {', '.join(skipped_positions)}"
        )

    if transformed_positions:
        logger.info(
            f"Successfully transformed {len(transformed_positions)} position(s) for margin calculation"
        )

    return transformed_positions


def parse_margin_response(response_data):
    """
    Parse Fyers margin response to OpenAlgo standard format.

    Fyers API returns total margin only, without detailed breakdown:
    - margin_avail: Available margin in account
    - margin_total: Approximate margin required for the order
    - margin_new_order: Total margin required including existing positions

    Unlike Angel/Zerodha, Fyers doesn't provide margin breakdown (SPAN/Exposure).
    We map margin_new_order to total_margin_required and set span/exposure to 0.

    Args:
        response_data: Raw response from Fyers API

    Expected response structure:
    {
        "s": "ok",
        "code": 200,
        "message": "",
        "data": {
            "margin_avail": 1999.9,
            "margin_total": 147738.0563,
            "margin_new_order": 147738.0563
        }
    }

    Returns:
        Standardized margin response matching OpenAlgo format:
        {
            "status": "success",
            "data": {
                "total_margin_required": 147738.0563,
                "span_margin": 0,
                "exposure_margin": 0
            }
        }
    """
    try:
        if not response_data or not isinstance(response_data, dict):
            return {"status": "error", "message": "Invalid response from broker"}

        # Check if the response has the expected structure
        # Fyers uses 's' field for status: 'ok' for success
        if response_data.get("s") != "ok":
            error_message = response_data.get("message", "Failed to calculate margin")
            error_code = response_data.get("code", "Unknown")
            return {
                "status": "error",
                "message": f"Fyers API Error (Code {error_code}): {error_message}",
            }

        # Extract margin data
        data = response_data.get("data", {})

        # Extract values from Fyers response
        margin_avail = data.get("margin_avail", 0)
        margin_total = data.get("margin_total", 0)
        margin_new_order = data.get("margin_new_order", 0)

        logger.info("=" * 80)
        logger.info("FYERS MARGIN API - DETAILED BREAKDOWN")
        logger.info("=" * 80)
        logger.info(f"Available Margin:        Rs. {margin_avail:,.2f}")
        logger.info(f"Margin Total:            Rs. {margin_total:,.2f}")
        logger.info(f"Margin New Order:        Rs. {margin_new_order:,.2f}")
        logger.info("")
        logger.info("NOTES:")
        logger.info("  - margin_avail: Available margin in your account")
        logger.info("  - margin_total: Approximate margin required for the order")
        logger.info("  - margin_new_order: Total margin including existing positions")
        logger.info("")
        logger.warning("⚠ IMPORTANT: Fyers does not provide SPAN/Exposure breakdown")
        logger.warning("⚠ Using margin_new_order as total_margin_required")
        logger.info("=" * 80)

        # Return standardized format matching OpenAlgo specification
        # Note: Fyers doesn't provide span_margin and exposure_margin breakdown
        # We use margin_new_order as the total margin required
        return {
            "status": "success",
            "data": {
                "total_margin_required": margin_new_order,
                "span_margin": 0,  # Fyers doesn't provide SPAN margin breakdown
                "exposure_margin": 0,  # Fyers doesn't provide Exposure margin breakdown
            },
        }

    except Exception as e:
        logger.error(f"Error parsing margin response: {e}")
        return {"status": "error", "message": f"Failed to parse margin response: {str(e)}"}
