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

    # total_utilization is reported negative (a debit); OpenAlgo shows it positive.
    return {
        "availablecash": f"{total('net_available'):.2f}",
        "collateral": f"{total('collateral'):.2f}",
        # Vortex does not split unrealised MTM out of the funds call.
        "m2munrealized": "0.00",
        "m2mrealized": f"{total('booked_profit') + total('mtm_and_booked_loss'):.2f}",
        "utiliseddebits": f"{abs(total('total_utilization')):.2f}",
    }
