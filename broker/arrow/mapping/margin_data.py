# Mapping OpenAlgo margin request <-> Arrow margin API (edge.arrow.trade/margin/order).
#
# Arrow's margin endpoint is PER-ORDER and is token-based. It returns
# `requiredMargin` (+ a charges breakdown) but NOT a SPAN/exposure split, so the
# standardized OpenAlgo response reports span_margin/exposure_margin as 0 and
# total_margin_required as the sum of per-order requiredMargin.

from database.token_db import get_token
from utils.logging import get_logger

logger = get_logger(__name__)


def _map_margin_product(product):
    """OpenAlgo product -> Arrow margin product (doc: M=Margin, C=Cash).
    TODO(arrow): confirm CNC->C (cash/delivery), NRML/MIS->M (margin)."""
    return "C" if product == "CNC" else "M"


def _map_margin_order(pricetype):
    """OpenAlgo pricetype -> Arrow margin order type. The margin endpoint
    documents only LMT/MKT."""
    return "MKT" if pricetype == "MARKET" else "LMT"


def transform_margin_positions(positions):
    """Transform OpenAlgo positions into Arrow /margin/order request bodies."""
    bodies = []
    skipped = []
    for position in positions:
        try:
            symbol = position["symbol"]
            exchange = position["exchange"]
            token = get_token(symbol, exchange)
            if not token:
                skipped.append(f"{symbol} ({exchange})")
                continue
            bodies.append(
                {
                    "exchange": exchange,
                    "token": str(token),
                    "quantity": str(position["quantity"]),
                    "product": _map_margin_product(position["product"]),
                    "price": str(position.get("price", 0)),
                    "transactionType": "B" if position["action"].upper() == "BUY" else "S",
                    "order": _map_margin_order(position["pricetype"]),
                }
            )
        except Exception as e:
            logger.error(f"Error transforming margin position {position}: {e}")
            skipped.append(f"{position.get('symbol', 'unknown')}")
    if skipped:
        logger.warning(f"Skipped {len(skipped)} margin position(s): {', '.join(skipped)}")
    return bodies


def parse_margin_response(order_data_list):
    """Aggregate Arrow per-order margin `data` dicts into the OpenAlgo standard.

    Arrow does not break out SPAN/exposure, so those are 0.
    """
    total_margin_required = 0.0
    for data in order_data_list:
        try:
            total_margin_required += float(data.get("requiredMargin", 0) or 0)
        except (TypeError, ValueError):
            continue
    return {
        "status": "success",
        "data": {
            "total_margin_required": round(total_margin_required, 2),
            "span_margin": 0.0,
            "exposure_margin": 0.0,
        },
    }
