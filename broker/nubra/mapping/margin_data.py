# Mapping OpenAlgo API Request https://openalgo.in/docs
# Mapping Nubra Trading API V3 margin (POST /sentinel/orders/funds_required)

from broker.nubra.mapping.transform_data import (
    build_entry_trigger,
    map_order_delivery_type,
    map_order_side,
    map_price_type,
    map_validity_type,
    sanitize_strat_tag,
)
from database.token_db import get_token
from utils.logging import get_logger

logger = get_logger(__name__)


def transform_margin_positions(positions):
    """
    Transform OpenAlgo margin positions into a Nubra V3 funds_required payload.

    V3 reuses the placement payload verbatim and adds one top-level field,
    ``requestType``. There is no basket wrapper any more -- several independent
    single orders are simply several items in ``orders``:

        {
          "requestType": "NEW",
          "orders": [
            {"refId": 72329, "qty": 1, "side": "BUY", "deliveryType": "IDAY",
             "priceType": "LIMIT", "validityType": "DAY", "isMultiLeg": false,
             "executionMode": "ENTRY", "entryPrice": 127000,
             "stratTags": ["openalgo-margin"]}
          ]
        }

    Returns None when no position could be resolved to a numeric ref_id.
    """
    transformed_orders = []
    skipped_positions = []

    for position in positions:
        try:
            symbol = position["symbol"]
            exchange = position["exchange"]

            # Get the token for the symbol
            token = get_token(symbol, exchange)

            # Validate token exists
            if not token:
                logger.warning(f"Token not found for symbol: {symbol} on exchange: {exchange}")
                skipped_positions.append(f"{symbol} ({exchange})")
                continue

            # Validate token is a valid number (Nubra expects numeric refId)
            token_str = str(token).strip()
            if not token_str.replace(".", "").replace("-", "").isdigit():
                logger.warning(f"Invalid token format for {symbol} ({exchange}): '{token_str}'")
                skipped_positions.append(f"{symbol} ({exchange}) - invalid token: {token_str}")
                continue

            ref_id = int(float(token_str))

            pricetype = str(position.get("pricetype", "MARKET")).upper()
            price_type = map_price_type(pricetype)

            nubra_order = {
                "refId": ref_id,
                "qty": int(position["quantity"]),
                "side": map_order_side(position["action"]),
                "deliveryType": map_order_delivery_type(position["product"]),
                "priceType": price_type,
                "validityType": map_validity_type(pricetype),
                "isMultiLeg": False,
                "executionMode": "ENTRY",
                "stratTags": [sanitize_strat_tag(position.get("strategy", "openalgo-margin"))],
            }

            # entryPrice is required for LIMIT and must be omitted for MARKET.
            if price_type == "LIMIT":
                price = float(position.get("price", 0) or 0)
                nubra_order["entryPrice"] = int(round(price * 100))

            # Carry the stop trigger too. The V3 margin request reuses the
            # placement payload verbatim, so omitting entryConfig prices an
            # untriggered LIMIT/MARKET order rather than the SL/SL-M the caller
            # asked about. MarginCalculatorSchema resolves trigger_price for
            # exactly this reason.
            entry_config = build_entry_trigger(
                pricetype, position.get("trigger_price"), position["action"]
            )
            if entry_config:
                nubra_order["entryConfig"] = entry_config

            transformed_orders.append(nubra_order)
            logger.debug(
                f"Successfully transformed position: {symbol} ({exchange}) with refId: {ref_id}"
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

    return {"requestType": "NEW", "orders": transformed_orders}


def parse_margin_response(response_data):
    """
    Parse the Nubra V3 funds_required response into the OpenAlgo standard format.

    V3 response:
    {
      "code": 1,
      "marginInfo": {"totalMargin": 0, "message": null},
      "brokerageInfo": {"totalChargesFloat": 13565.63879385},
      "totalFundsRequired": 13565,
      "willDefaultBePlacedAsAmo": true,
      "willBeAutoSliced": false
    }

    V3 no longer breaks the requirement into span/exposure -- it returns a
    single ``marginInfo.totalMargin`` plus estimated charges. ``totalMargin``
    is the blocked margin component while ``totalFundsRequired`` includes
    charges, so the latter is the number a caller needs before placing.
    """
    try:
        if not response_data or not isinstance(response_data, dict):
            return {"status": "error", "message": "Invalid response from broker"}

        margin_info = response_data.get("marginInfo")
        brokerage_info = response_data.get("brokerageInfo") or {}

        # An error response carries no marginInfo block. Note code == 1 is the
        # V3 success marker, so code alone must not be treated as an error.
        #
        # V3 reports the reason in "error", not "message" -- reading only
        # "message" turns a precise diagnosis ("Orders cannot be placed from
        # this IP address...") into "Unknown error from Nubra".
        if not isinstance(margin_info, dict):
            message = (
                response_data.get("error")
                or response_data.get("message")
                or "Unknown error from Nubra"
            )
            return {"status": "error", "message": str(message)}

        total_margin = float(margin_info.get("totalMargin", 0) or 0)
        total_funds_required = float(response_data.get("totalFundsRequired", 0) or 0)
        total_charges = float(brokerage_info.get("totalChargesFloat", 0) or 0)

        # Return standardized format matching the OpenAlgo API specification.
        # V3 gives no span/exposure split; report the blocked margin as span and
        # leave exposure at zero rather than inventing a breakdown.
        return {
            "status": "success",
            "data": {
                "total_margin_required": total_funds_required or total_margin,
                "span_margin": total_margin,
                "exposure_margin": 0.0,
                "total_charges": round(total_charges, 2),
            },
        }

    except Exception as e:
        logger.error(f"Error parsing margin response: {e}")
        return {"status": "error", "message": f"Failed to parse margin response: {str(e)}"}
