# Mapping OpenAlgo API Request https://openalgo.in/docs
# Mapping Kotak Neo Margin API

from broker.kotak.mapping.transform_data import (
    map_order_type,
    map_product_type,
    reverse_map_exchange,
)
from database.token_db import get_token
from utils.logging import get_logger

logger = get_logger(__name__)


def transform_margin_position(position):
    """
    Transform a single OpenAlgo margin position to Kotak margin format.

    Note: Kotak margin API accepts only one order at a time, not a batch.

    Args:
        position: Position in OpenAlgo format

    Returns:
        Dict in Kotak margin format or None if transformation fails
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
        exchange_segment = reverse_map_exchange(position["exchange"])
        if not exchange_segment:
            logger.warning(f"Invalid exchange: {position['exchange']}")
            return None

        # Map transaction type
        transaction_type = "B" if position["action"].upper() == "BUY" else "S"

        # Transform the position (all values must be strings for Kotak API)
        transformed = {
            "brkName": "KOTAK",
            "brnchId": "ONLINE",
            "exSeg": exchange_segment,
            "prc": str(position.get("price", "0")),
            "prcTp": map_order_type(position["pricetype"]),
            "prod": map_product_type(position["product"]),
            "qty": str(position["quantity"]),
            "tok": str(token),
            "trnsTp": transaction_type,
        }

        return transformed

    except Exception as e:
        logger.error(f"Error transforming position: {position}, Error: {e}")
        return None


def parse_margin_response(response_data):
    """
    Parse Kotak margin response to OpenAlgo standard format.

    Args:
        response_data: Raw response from Kotak API

    Returns:
        Standardized margin response
    """
    try:
        if not response_data or not isinstance(response_data, dict):
            return {"status": "error", "message": "Invalid response from broker"}

        # Check if the response status is Ok
        if response_data.get("stat") != "Ok":
            # Kotak's error field is "emsg" ({"stat":"Not_Ok","emsg":"Invalid
            # session","stCode":1003}, as funds.py already reads it). Reading
            # only "errMsg" replaced every reason with the generic text below.
            error_message = (
                response_data.get("emsg")
                or response_data.get("errMsg")
                or "Failed to calculate margin"
            )
            return {"status": "error", "message": error_message}

        # check-margin (kotak-api-docs/10-portfolio-margins.md):
        #   ordMrgn  -> margin required for this order
        #   mrgnUsd  -> margin already used on the account
        #   reqdMrgn -> ordMrgn + mrgnUsd (12500 + 40.4 = 12540.4 in the doc)
        # reqdMrgn counted the account's existing usage into the order, and
        # once per leg when a basket is summed (issue #2156). Report ordMrgn.
        order_margin = response_data.get("ordMrgn")
        if order_margin in (None, ""):
            logger.warning(f"Kotak check-margin returned no ordMrgn: {response_data}")
            return {"status": "error", "message": "Broker did not return the order margin"}
        total_margin_required = float(order_margin)

        # Return standardized format matching OpenAlgo API specification
        return {
            "status": "success",
            "data": {
                "total_margin_required": total_margin_required,
                "span_margin": 0,  # Kotak doesn't provide separate span margin
                "exposure_margin": 0,  # Kotak doesn't provide separate exposure margin
            },
        }

    except Exception as e:
        logger.error(f"Error parsing margin response: {e}")
        return {"status": "error", "message": f"Failed to parse margin response: {str(e)}"}


def parse_batch_margin_response(responses):
    """
    Sum per-leg Kotak margins into one basket figure.

    Kotak's check-margin prices one order at a time, so the sum carries no
    hedge benefit between legs (a calendar spread is quoted at the margin of
    its legs taken separately).

    Any failed leg fails the basket. Skipping it reported the margin of a
    different basket, and with every leg failed it reported a "success" of 0
    (issue #2156).
    """
    failures = [
        r.get("message", "Failed to calculate margin")
        for r in responses
        if r.get("status") != "success"
    ]
    if failures:
        return {"status": "error", "message": "; ".join(dict.fromkeys(failures))}

    total_required_margin = sum(r["data"]["total_margin_required"] for r in responses)
    return {
        "status": "success",
        "data": {
            "total_margin_required": round(total_required_margin, 2),
            "span_margin": 0,  # Kotak doesn't provide separate span margin
            "exposure_margin": 0,  # Kotak doesn't provide separate exposure margin
        },
    }
