# broker/hdfcsky/mapping/margin_data.py
#
# Transformations for HDFC Sky's margin calculator (POST /oapi/v1/margin).
#
# Request legs mirror the docs' sample:
#   {"segment": "FutOpt", "series": "OPTIDX", "exchange": "BFO",
#    "side": "SELL", "mode": "NEW", "symbol": "SENSEX24AUG24200CE",
#    "underlying": "76000", "token": "74643", "quantity": "25",
#    "price": "332.85", "product": "0"}
# `segment`, `series` and the numeric `product` come from the GenericDTO
# proto's Segment / Series / ProdType enums.
#
# The response carries a portfolio-netted `result.combined_margin` plus
# `result.individual_margin_values` (one entry per leg).

from broker.hdfcsky.mapping.transform_data import PRODUCT_NUMERIC_CODES
from utils.logging import get_logger

logger = get_logger(__name__)

# OpenAlgo exchange -> HDFC Sky `segment` (proto Segment enum).
_SEGMENT_MAP = {
    "NSE": "Capital",
    "BSE": "Capital",
    "NSE_INDEX": "Capital",
    "BSE_INDEX": "Capital",
    "NFO": "FutOpt",
    "BFO": "FutOpt",
    "CDS": "Currency",
    "MCX": "Commodities",
}

# Margin components that ADD to the requirement, and the one that subtracts.
_MARGIN_COMPONENTS = (
    "span",
    "exposure_margin",
    "premium_margin",
    "var_margin",
    "extreme_loss_margin",
    "delivery_margin",
    "additional_margin",
    "span_spread_margin",
    "somtier_margin",
)
_MARGIN_BENEFIT = "premium_benefit"


def _float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def to_segment(exchange):
    return _SEGMENT_MAP.get(exchange, "Capital")


def build_margin_leg(position, row, series_type, underlying_price):
    """Build one HDFC Sky margin request leg.

    Args:
        position: the OpenAlgo position dict (symbol, exchange, action,
            quantity, price, product).
        row: the instrument's SymToken row.
        series_type: the exchange series code (EQ / OPTIDX / IO / FUTCOM ...).
        underlying_price: last traded price of the underlying, or 0.0.
    """
    return {
        "segment": to_segment(row.exchange),
        "series": series_type,
        "exchange": row.brexchange,
        "side": str(position.get("action", "BUY")).upper(),
        "mode": "NEW",
        "symbol": row.brsymbol,
        "underlying": str(underlying_price or 0),
        "token": str(row.token),
        "quantity": str(int(float(position.get("quantity", 0) or 0))),
        "price": str(_float(position.get("price", 0))),
        "product": PRODUCT_NUMERIC_CODES.get(
            str(position.get("product", "MIS")).upper(), "2"
        ),
    }


def _sum_components(block):
    """Net margin requirement for one margin block."""
    if not isinstance(block, dict):
        return 0.0, 0.0, 0.0
    total = sum(_float(block.get(key)) for key in _MARGIN_COMPONENTS)
    total -= _float(block.get(_MARGIN_BENEFIT))
    return max(total, 0.0), _float(block.get("span")), _float(block.get("exposure_margin"))


def parse_margin_response(result):
    """HDFC Sky margin `result` block -> the OpenAlgo standard payload.

    Prefers `combined_margin` (the portfolio-netted figure that captures
    spread/hedge benefit). Falls back to summing `individual_margin_values`
    when the combined block is empty or all-zero, which the API does for
    single-leg requests.
    """
    combined = (result or {}).get("combined_margin") or {}
    individuals = (result or {}).get("individual_margin_values") or []

    total, span, exposure = _sum_components(combined)

    if total <= 0 and individuals:
        logger.debug("HDFC Sky combined_margin empty; summing individual legs")
        span = exposure = total = 0.0
        for leg in individuals:
            leg_total, leg_span, leg_exposure = _sum_components(leg)
            total += leg_total
            span += leg_span
            exposure += leg_exposure

    return {
        "status": "success",
        "data": {
            "total_margin_required": round(total, 2),
            "span_margin": round(span, 2),
            "exposure_margin": round(exposure, 2),
        },
    }
