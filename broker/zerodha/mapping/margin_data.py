# Mapping OpenAlgo API Request https://openalgo.in/docs
# Mapping Zerodha Margin API https://kite.trade/docs/connect/v3/margins/

from database.token_db import get_br_symbol
from utils.logging import get_logger

logger = get_logger(__name__)


def transform_margin_positions(positions):
    """
    Transform OpenAlgo margin position format to Zerodha margin format.

    Args:
        positions: List of positions in OpenAlgo format

    Returns:
        List of positions in Zerodha format
    """
    transformed_positions = []
    skipped_positions = []

    for position in positions:
        try:
            symbol = position["symbol"]
            exchange = position["exchange"]

            # Get the broker symbol for Zerodha
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
                "exchange": exchange,
                "tradingsymbol": br_symbol_str,
                "transaction_type": position["action"].upper(),
                "variety": "regular",  # Default variety for margin calculation
                "product": map_product_type(position["product"]),
                "order_type": map_order_type(position["pricetype"]),
                "quantity": int(position["quantity"]),
                "price": float(position.get("price", 0)),
                "trigger_price": float(position.get("trigger_price", 0)),
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


def map_product_type(product):
    """
    Maps OpenAlgo product type to Zerodha product type.

    OpenAlgo: CNC, NRML, MIS
    Zerodha: CNC, NRML, MIS (Direct mapping - no transformation needed)
    """
    product_type_mapping = {
        "CNC": "CNC",
        "NRML": "NRML",
        "MIS": "MIS",
    }
    return product_type_mapping.get(product, "MIS")


def map_order_type(pricetype):
    """
    Maps OpenAlgo price type to Zerodha order type.

    OpenAlgo: MARKET, LIMIT, SL, SL-M
    Zerodha: MARKET, LIMIT, SL, SL-M (Direct mapping - no transformation needed)
    """
    order_type_mapping = {"MARKET": "MARKET", "LIMIT": "LIMIT", "SL": "SL", "SL-M": "SL-M"}
    return order_type_mapping.get(pricetype, "MARKET")


def parse_margin_response(response_data):
    """
    Parse Zerodha margin response to OpenAlgo standard format.

    Zerodha basket margin response structure:
    - data.initial: Total margins from basket calculation (partially optimized)
    - data.final: Total margins WITH full spread benefit (fully optimized)
    - data.orders: Individual order margins in the basket context

    IMPORTANT NOTE ON MARGIN BENEFIT:
    Zerodha's basket API returns initial.total that is ALREADY partially optimized.
    For example, in a short straddle:
    - orders[CE].span = 179,780 (full span)
    - orders[PE].span = 0 (hedged, no span required!)
    - initial.total = sum of optimized orders = 258,139

    To get TRUE margin benefit (matching Zerodha's web UI):
    - TRUE individual total = Call each order separately and sum = 429,255
    - Basket final total = 191,119
    - TRUE margin benefit = 429,255 - 191,119 = 238,136

    But basket API only provides:
    - initial.total - final.total = 258,139 - 191,119 = 67,020 (option_premium)

    This implementation uses basket API values (initial.total - final.total).
    For true individual margins, each position must be queried separately first.

    Args:
        response_data: Raw response from Zerodha API

    Returns:
        Standardized margin response matching OpenAlgo format
    """
    try:
        if not response_data or not isinstance(response_data, dict):
            return {"status": "error", "message": "Invalid response from broker"}

        # Check if the response has the expected structure
        if response_data.get("status") != "success":
            error_message = response_data.get("message", "Failed to calculate margin")
            # Check for error_type field in Zerodha responses
            if "error_type" in response_data:
                error_message = f"{response_data.get('error_type')}: {error_message}"
            return {"status": "error", "message": error_message}

        # Extract margin data
        data = response_data.get("data", {})

        # Initialize variables
        total_margin_required = 0
        span_margin = 0
        exposure_margin = 0
        margin_benefit = 0

        if isinstance(data, dict) and "final" in data:
            # Basket response - use final values which include spread benefit
            initial = data.get("initial", {})
            final = data.get("final", {})

            # Extract all margin components
            # Use initial.total for total_margin_required as per requirement
            total_margin_required = initial.get("total", 0)
            span_margin = final.get("span", 0)
            exposure_margin = final.get("exposure", 0)
            option_premium = final.get("option_premium", 0)
            additional = final.get("additional", 0)
            bo = final.get("bo", 0)
            cash = final.get("cash", 0)
            var = final.get("var", 0)

            # Extract initial values (individual position margins)
            initial_total = initial.get("total", 0)
            initial_span = initial.get("span", 0)
            initial_exposure = initial.get("exposure", 0)
            initial_option_premium = initial.get("option_premium", 0)

            final_total = final.get("total", 0)

            # Calculate margin benefit (savings from spread/hedge recognition)
            # Formula: Margin Benefit = Sum of Individual Margins - Optimized Combined Margin
            # Example: 4,27,882 (individual) - 2,56,121 (optimized) = 1,71,761 (benefit)
            margin_benefit = initial_total - final_total

            logger.info("=" * 80)
            logger.info("ZERODHA BASKET MARGIN - DETAILED BREAKDOWN")
            logger.info("=" * 80)
            logger.info("BASKET INITIAL VALUES (Partially Optimized):")
            logger.info(f"  initial.total           = Rs. {initial_total:,.2f}")
            logger.info(f"  initial.span            = Rs. {initial_span:,.2f}")
            logger.info(f"  initial.exposure        = Rs. {initial_exposure:,.2f}")
            logger.info(f"  initial.option_premium  = Rs. {initial_option_premium:,.2f}")
            logger.info("")
            logger.info("BASKET FINAL VALUES (Fully Optimized):")
            logger.info(f"  final.total             = Rs. {final_total:,.2f}")
            logger.info(f"  final.span              = Rs. {span_margin:,.2f}")
            logger.info(f"  final.exposure          = Rs. {exposure_margin:,.2f}")
            logger.info(f"  final.option_premium    = Rs. {option_premium:,.2f}")
            logger.info(f"  final.additional        = Rs. {additional:,.2f}")
            logger.info(f"  final.bo                = Rs. {bo:,.2f}")
            logger.info(f"  final.cash              = Rs. {cash:,.2f}")
            logger.info(f"  final.var               = Rs. {var:,.2f}")
            logger.info("")
            logger.info("MARGIN BENEFIT (From Basket API):")
            logger.info("  Formula: initial.total - final.total")
            logger.info(
                f"  Calculation: {initial_total:,.2f} - {final_total:,.2f} = Rs. {margin_benefit:,.2f}"
            )
            logger.info(
                f"  Note: This equals option_premium change ({option_premium - initial_option_premium:,.2f})"
            )
            logger.info("")
            logger.warning(
                "⚠ IMPORTANT: Zerodha's basket initial.total is ALREADY partially optimized!"
            )
            logger.warning(
                "⚠ For TRUE margin benefit matching web UI, query each order separately first."
            )
            logger.info("=" * 80)

            # Log individual order margins if available
            orders = data.get("orders", [])
            if orders:
                logger.info("INDIVIDUAL ORDER MARGINS IN BASKET:")
                logger.info("-" * 80)
                basket_orders_sum = 0
                for idx, order in enumerate(orders, 1):
                    order_total = order.get("total", 0)
                    order_span = order.get("span", 0)
                    order_exposure = order.get("exposure", 0)
                    order_premium = order.get("option_premium", 0)
                    basket_orders_sum += order_total

                    hedged_note = " ← HEDGED (Zero SPAN!)" if order_span == 0 else ""
                    logger.info(f"Order {idx}: {order.get('tradingsymbol', 'N/A')}")
                    logger.info(f"  Span:            Rs. {order_span:,.2f}{hedged_note}")
                    logger.info(f"  Exposure:        Rs. {order_exposure:,.2f}")
                    logger.info(f"  Option Premium:  Rs. {order_premium:,.2f}")
                    logger.info(f"  Total:           Rs. {order_total:,.2f}")

                logger.info("-" * 80)
                logger.info(f"Sum of basket orders: Rs. {basket_orders_sum:,.2f}")
                logger.info(f"Matches initial.total: {abs(basket_orders_sum - initial_total) < 1}")
                logger.info("=" * 80)

        elif isinstance(data, list):
            # Orders response - aggregate all order margins
            for order in data:
                span_margin += order.get("span", 0)
                exposure_margin += order.get("exposure", 0)
                total_margin_required += order.get("total", 0)

            # No margin benefit for simple orders (no spread optimization)
            margin_benefit = 0

            logger.debug(
                f"Orders margin: total={total_margin_required}, span={span_margin}, exposure={exposure_margin}"
            )

        # Return standardized format matching OpenAlgo API specification
        response_data = {
            "status": "success",
            "data": {
                "total_margin_required": total_margin_required,
                "span_margin": span_margin,
                "exposure_margin": exposure_margin,
            },
        }

        return response_data

    except Exception as e:
        logger.error(f"Error parsing Zerodha margin response: {e}")
        return {"status": "error", "message": f"Failed to parse margin response: {str(e)}"}
