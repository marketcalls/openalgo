# Mapping OpenAlgo API Request https://openalgo.in/docs
# Mapping Nubra Margin API

from database.token_db import get_token
from utils.logging import get_logger

logger = get_logger(__name__)


def transform_margin_positions(positions):
    """
    Transform OpenAlgo margin position format to Nubra margin format.
    
    Nubra Margin API Payload Structure:
    {
        "with_portfolio": true,
        "with_legs": false,
        "is_basket": true,
        "order_req": {
            "exchange": "NSE",
            "orders": [
                {
                    "ref_id": 12345,
                    "order_qty": 10,
                    "order_side": "ORDER_SIDE_BUY",
                    "order_delivery_type": "ORDER_DELIVERY_TYPE_CNC",
                    "price_type": "MARKET",         # Optional but good to have
                    "order_price": 0,               # Optional for market
                    "order_type": "ORDER_TYPE_REGULAR"
                },
                ...
            ]
        }
    }
    """
    transformed_orders = []
    skipped_positions = []
    
    # We need to determine the exchange for the payload.
    # Assuming all positions in the basket are for the same exchange segment for now.
    # If mixed, we'll take the first one found.
    primary_exchange = None

    for position in positions:
        try:
            symbol = position["symbol"]
            exchange = position["exchange"]
            
            if not primary_exchange:
                primary_exchange = exchange
            
            # Get the token for the symbol
            token = get_token(symbol, exchange)

            # Validate token exists
            if not token:
                logger.warning(f"Token not found for symbol: {symbol} on exchange: {exchange}")
                skipped_positions.append(f"{symbol} ({exchange})")
                continue

            # Validate token is a valid number (Nubra expects numeric ref_id)
            token_str = str(token).strip()
            if not token_str.replace(".", "").replace("-", "").isdigit():
                logger.warning(f"Invalid token format for {symbol} ({exchange}): '{token_str}'")
                skipped_positions.append(f"{symbol} ({exchange}) - invalid token: {token_str}")
                continue
                
            ref_id = int(float(token_str))

            # Map fields
            order_side = map_order_side(position["action"])
            delivery_type = map_product_type(position["product"])
            pricetype = position.get("pricetype", "MARKET")
            price_type = map_price_type(pricetype)
            order_type = map_order_type(pricetype)
            
            price = float(position.get("price", 0))
            price_in_paise = int(round(price * 100)) if price else 0

            # Transform the position
            nubra_order = {
                "ref_id": ref_id,
                "order_qty": int(position["quantity"]),
                "order_side": order_side,
                "order_delivery_type": delivery_type,
                "price_type": price_type,
                "order_price": price_in_paise,
                "order_type": order_type
            }

            transformed_orders.append(nubra_order)
            logger.debug(
                f"Successfully transformed position: {symbol} ({exchange}) with ref_id: {ref_id}"
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

    if not transformed_orders:
        return None

    # Get default basket parameters from first order
    first_order = transformed_orders[0]
    
    # Construct the final Nubra payload structure
    payload_data = {
        "with_portfolio": True,  # Critical for accurate calculation
        "with_legs": False,
        "is_basket": True,       # Always treat as basket for margin batch calculation
        "order_req": {
            "exchange": primary_exchange if primary_exchange else "NSE",
            "orders": transformed_orders,
            # basket_params is REQUIRED when is_basket is true
            "basket_params": {
                "order_side": first_order.get("order_side", "ORDER_SIDE_BUY"),
                "order_delivery_type": first_order.get("order_delivery_type", "ORDER_DELIVERY_TYPE_CNC"),
                "price_type": first_order.get("price_type", "MARKET"),
                "multiplier": 1  # Default multiplier
            }
        }
    }
    
    return payload_data


def map_product_type(product):
    """
    Maps OpenAlgo product type to Nubra order_delivery_type.
    """
    mapping = {
        "CNC": "ORDER_DELIVERY_TYPE_CNC",
        "NRML": "ORDER_DELIVERY_TYPE_CNC", # NRML maps to CNC/Margin
        "MIS": "ORDER_DELIVERY_TYPE_IDAY",
    }
    return mapping.get(product.upper(), "ORDER_DELIVERY_TYPE_IDAY")


def map_order_side(action):
    """
    Maps OpenAlgo action to Nubra order_side.
    """
    mapping = {
        "BUY": "ORDER_SIDE_BUY",
        "SELL": "ORDER_SIDE_SELL",
    }
    return mapping.get(action.upper(), "ORDER_SIDE_BUY")


def map_price_type(pricetype):
    """
    Maps OpenAlgo pricetype to Nubra price_type.
    """
    mapping = {
        "MARKET": "MARKET",
        "LIMIT": "LIMIT",
        "SL": "LIMIT",
        "SL-M": "MARKET",
    }
    return mapping.get(pricetype.upper(), "MARKET")


def map_order_type(pricetype):
    """
    Maps OpenAlgo pricetype to Nubra order_type.
    """
    mapping = {
        "MARKET": "ORDER_TYPE_REGULAR",
        "LIMIT": "ORDER_TYPE_REGULAR",
        "SL": "ORDER_TYPE_STOPLOSS",
        "SL-M": "ORDER_TYPE_STOPLOSS",
    }
    return mapping.get(pricetype.upper(), "ORDER_TYPE_REGULAR")


def parse_margin_response(response_data):
    """
    Parse Nubra margin calculator response to OpenAlgo standard format.

    Nubra Response Example:
    {
      "span": 52000,
      "exposure": 18000,
      "total_margin": 70000,
      "margin_benefit": 0,
      "leg_margin": null,
      "message": null
    }
    """
    try:
        if not response_data or not isinstance(response_data, dict):
            return {"status": "error", "message": "Invalid response from broker"}
        
        # Nubra sometimes returns error code in response
        if response_data.get("code"):
             return {
                "status": "error",
                "message": response_data.get("message", "Unknown error from Nubra"),
            }

        # Extract values
        # Note: Nubra returns total_margin which is the most important field
        # We map it to total_margin_required
        total_margin_required = float(response_data.get("total_margin", 0))
        span_margin = float(response_data.get("span", 0))
        exposure_margin = float(response_data.get("exposure", 0))
        
        # Return standardized format match OpenAlgo API specification
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

