# Mapping OpenAlgo margin request <-> Arrow margin API (edge.arrow.trade/margin/order).
#
# Arrow's margin endpoint is PER-ORDER and takes the broker trading symbol
# (e.g. "SBIN-EQ", "NIFTY30JUN26F") in `symbol` -- its validator calls the
# field `tradingSymbol` in error messages. It returns `requiredMargin` (+ a
# charges breakdown) but NOT a SPAN/exposure split, so the standardized
# OpenAlgo response reports span_margin/exposure_margin as 0 and
# total_margin_required as the sum of per-order requiredMargin.

from database.token_db import get_br_symbol
from utils.logging import get_logger

logger = get_logger(__name__)

# OpenAlgo product -> Arrow product code (pyarrow-client ProductType enum:
# MIS="I" intraday, CNC="C" cash/delivery, NRML="M" margin/carry).
_PRODUCT_MAP = {"CNC": "C", "MIS": "I", "NRML": "M"}


def _map_margin_product(product):
    return _PRODUCT_MAP.get(str(product).upper(), "M")


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
            br_symbol = get_br_symbol(symbol, exchange)
            if not br_symbol:
                skipped.append(f"{symbol} ({exchange})")
                continue
            bodies.append(
                {
                    "exchange": exchange,
                    "symbol": br_symbol,
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


def _to_float(value):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def parse_margin_response(order_data_list):
    """Aggregate Arrow per-order /margin/order `data` dicts into the OpenAlgo
    standard. Arrow does not break out SPAN/exposure, so those are 0.
    `total_charges` sums the transaction-cost breakdown (charge.total) --
    capital blocked is `total_margin_required`; both are debited on execution.
    """
    total_margin_required = 0.0
    total_charges = 0.0
    for data in order_data_list:
        total_margin_required += _to_float(data.get("requiredMargin"))
        total_charges += _to_float((data.get("charge") or {}).get("total"))
    return {
        "status": "success",
        "data": {
            "total_margin_required": round(total_margin_required, 2),
            "span_margin": 0.0,
            "exposure_margin": 0.0,
            "total_charges": round(total_charges, 2),
        },
    }


def parse_basket_margin_response(data):
    """Map Arrow's /margin/basket response `data` to the OpenAlgo standard.

    Arrow returns the portfolio-level requirement in `final_margin` (after
    cross-leg benefit; `initial_margin` is pre-benefit) plus per-order
    `margin` and `charge` breakdowns.
    """
    total_charges = 0.0
    for order in data.get("orders") or []:
        total_charges += _to_float((order.get("charge") or {}).get("total"))
    return {
        "status": "success",
        "data": {
            "total_margin_required": round(_to_float(data.get("final_margin")), 2),
            "span_margin": 0.0,
            "exposure_margin": 0.0,
            "total_charges": round(total_charges, 2),
        },
    }
