# broker/rupeezy/api/funds.py
#
# GET /user/funds returns separate NSE (cash + F&O + currency) and MCX
# buckets. OpenAlgo shows one account view, so the two are summed.

from broker.rupeezy.api.client import request_json
from utils.logging import get_logger

logger = get_logger(__name__)


def _f(value):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _positions_pnl(auth_token):
    """(realized, unrealized) summed over the position book at live prices,
    so the two always add up to the book's net P&L. A position whose split is
    unknown (no price) is left out of both. None if positions cannot be read."""
    from broker.rupeezy.api.order_api import get_positions
    from broker.rupeezy.mapping.order_data import map_position_data, position_pnl_split

    try:
        payload = get_positions(auth_token)
        if not isinstance(payload, dict) or payload.get("status") == "error":
            return None
        realized = unrealized = 0.0
        for row in map_position_data(payload):
            split = position_pnl_split(row)
            if split is None:
                logger.warning(f"Rupeezy funds P&L leaves out {row.get('_symbol')}: no live price")
                continue
            realized += split[0]
            unrealized += split[1]
        return realized, unrealized
    except Exception:
        logger.exception("Could not compute Rupeezy P&L from positions")
        return None


def get_margin_data(auth_token):
    """Funds -> OpenAlgo margin dict. Returns {} on error."""
    try:
        payload = request_json("GET", "/user/funds", auth_token)
    except Exception:
        logger.exception("Error fetching Rupeezy funds")
        return {}

    # Documented response has the buckets at the top level; tolerate a
    # {"status", "data": {...}} envelope too.
    body = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    if payload.get("status") == "error" or not any(
        k in body for k in ("exchange_combined", "nse", "mcx")
    ):
        logger.error(f"Error fetching Rupeezy funds: {payload.get('message')}")
        return {}

    # `exchange_combined` is Vortex's own NSE + MCX total. Prefer it; sum the
    # two buckets only if it is absent.
    combined = body.get("exchange_combined")
    buckets = [combined] if combined else [body.get("nse") or {}, body.get("mcx") or {}]

    def total(key):
        return sum(_f(b.get(key)) for b in buckets)

    # Vortex's funds call has no unrealised figure. Both P&L fields come from
    # the position book instead: taking realized from the funds buckets and
    # unrealized from positions counted a partially closed position's booked
    # part twice. The buckets are the fallback only when positions can't be read.
    pnl = _positions_pnl(auth_token)
    if pnl is None:
        realized, unrealized = total("booked_profit") + total("mtm_and_booked_loss"), 0.0
    else:
        realized, unrealized = pnl

    # total_utilization is reported negative (a debit); OpenAlgo shows it positive.
    return {
        "availablecash": f"{total('net_available'):.2f}",
        "collateral": f"{total('collateral'):.2f}",
        "m2munrealized": f"{unrealized:.2f}",
        "m2mrealized": f"{realized:.2f}",
        "utiliseddebits": f"{abs(total('total_utilization')):.2f}",
    }
