# broker/hdfcsecurities/api/funds.py
#
# HDFC Securities InvestRight funds: GET /oapi/v1/user/margins?api_key=<key>
#
# The response nests everything under `data.equity` and mixes key casing within
# a single payload -- the three top-level totals are snake_case while the three
# breakdown objects are camelCase:
#
#   {"status": "success",
#    "data": {"equity": {
#        "total_available_limit": 9.99,
#        "total_utilised_limit": 184,
#        "total_limit": 9.99,
#        "totalAvailableLimitDetails": {"cash": ..., "mtf": ..., ...},
#        "totalUtilizationDetails":    {"cash": ..., "mtf": ..., ...},
#        "totalLimitDetails": {"bank_hold": ..., "intraday_sales_proceed": ...,
#                              "ledger_balance": ..., "adhoc_limit": ...,
#                              "pledge_limit": ...}}}}
#
# Mapping to the OpenAlgo common format:
#   availablecash  <- total_available_limit
#   utiliseddebits <- total_utilised_limit
#   collateral     <- totalLimitDetails.pledge_limit
#   m2mrealized / m2munrealized  are NOT in this payload at all. InvestRight
#     reports realized P&L only per position (realised_pl_overall_position /
#     realised_pl_t_day_position), so the realized figure is summed from the
#     position book and the unrealized figure is marked to the live LTP -- the
#     same numbers the position book itself shows, rather than a silent 0.00.

from broker.hdfcsecurities.api.baseurl import (
    base_params,
    get_hdfcsecurities_headers,
    get_root_url,
)
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)

_EMPTY = {
    "availablecash": "0.00",
    "collateral": "0.00",
    "m2munrealized": "0.00",
    "m2mrealized": "0.00",
    "utiliseddebits": "0.00",
}


def _to_float(value):
    try:
        # Values are numeric in the sample but may arrive as strings with
        # thousands separators.
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return 0.0


def _mtm_from_positions(auth_token):
    """(realized, unrealized) P&L, summed from the position book.

    The funds payload carries no P&L, so both figures come from the same source
    the position book uses: InvestRight's own realized P&L per position, and an
    unrealized leg marked to the LTP that api/order_api.get_positions() injects.
    Any failure degrades to (0.0, 0.0) -- funds must still return.
    """
    try:
        from broker.hdfcsecurities.api.order_api import _position_rows, get_positions

        realized = unrealized = 0.0
        for position in _position_rows(get_positions(auth_token)):
            realized += _to_float(position.get("realised_pl_overall_position"))
            net_qty = _to_float(position.get("net_qty"))
            if not net_qty:
                continue
            ltp = _to_float(position.get("ltp"))
            if not ltp:
                continue
            # Mark the OPEN leg only: a long carries the buy average, a short
            # the sell average. The closed leg is already in `realized`.
            if net_qty > 0:
                cost = _to_float(position.get("average_buy_price"))
            else:
                cost = _to_float(position.get("average_sell_price"))
            unrealized += (ltp - cost) * net_qty
        return realized, unrealized
    except Exception as e:
        logger.warning(f"Could not derive MTM from the HDFC Securities position book: {e}")
        return 0.0, 0.0


def get_margin_data(auth_token):
    """Fetch and normalize InvestRight funds into the OpenAlgo common format."""
    try:
        client = get_httpx_client()
        response = client.get(
            f"{get_root_url()}/oapi/v1/user/margins",
            headers=get_hdfcsecurities_headers(auth_token),
            params=base_params(),
        )
        # A 404 or gateway error arrives with an empty or HTML body, so guard
        # the decode rather than letting it raise JSONDecodeError.
        try:
            payload = response.json()
        except ValueError:
            logger.error(
                f"Non-JSON HDFC Securities funds response (HTTP {response.status_code}): "
                f"{response.text[:200]!r}"
            )
            return {}
    except Exception as e:
        logger.exception(f"Error fetching HDFC Securities margin data: {e}")
        return {}

    # An expired or revoked token answers with an error shape that may carry no
    # "status" field, so check the HTTP code and a bare "error" key too.
    # Returning {} (never a zero-filled dict) is what lets blueprints/auth.py
    # detect the dead session and re-authenticate.
    if (
        not isinstance(payload, dict)
        or response.status_code >= 400
        or payload.get("status") == "error"
        or payload.get("error")
    ):
        message = (
            payload.get("message") or payload.get("error") if isinstance(payload, dict) else payload
        )
        logger.error(
            f"Error fetching HDFC Securities margin data (HTTP {response.status_code}): {message}"
        )
        return {}

    equity = (payload.get("data") or {}).get("equity")
    if not isinstance(equity, dict):
        logger.error(f"Unexpected HDFC Securities funds payload shape: {type(equity)}")
        return {}

    limit_details = equity.get("totalLimitDetails") or {}

    processed = dict(_EMPTY)
    processed["availablecash"] = f"{_to_float(equity.get('total_available_limit')):.2f}"
    processed["utiliseddebits"] = f"{_to_float(equity.get('total_utilised_limit')):.2f}"
    processed["collateral"] = f"{_to_float(limit_details.get('pledge_limit')):.2f}"

    realized, unrealized = _mtm_from_positions(auth_token)
    processed["m2mrealized"] = f"{realized:.2f}"
    processed["m2munrealized"] = f"{unrealized:.2f}"

    return processed
