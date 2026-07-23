# broker/hdfcsky/api/funds.py
#
# HDFC Sky funds: GET /oapi/v2/funds/view?client_id=<id>&type=all
#
# The V2 payload is a label/value table rather than named fields:
#   {"data": {"client_id": "...", "headers": ["Description", ""],
#             "values": [{"0": "Available Margin", "1": "8239.85"},
#                        {"0": "Margin Used",      "1": "19.34"}, ...]}}
# so the mapping below keys off the label text.

from broker.hdfcsky.api.baseurl import base_params, get_hdfcsky_headers, get_root_url
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)

# HDFC Sky funds label (normalized: lowercase, no spaces) -> OpenAlgo key.
_LABEL_MAP = {
    "availablemargin": "availablecash",
    "marginused": "utiliseddebits",
    "pledgebenefit": "collateral",
    "realizedmtm": "m2mrealized",
    "unrealizedmtm": "m2munrealized",
}

_EMPTY = {
    "availablecash": "0.00",
    "collateral": "0.00",
    "m2munrealized": "0.00",
    "m2mrealized": "0.00",
    "utiliseddebits": "0.00",
}


def _norm(label):
    return "".join(str(label).lower().split())


def _to_float(value):
    try:
        # Values arrive as strings and may carry thousands separators.
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return 0.0


def get_margin_data(auth_token):
    """Fetch and normalize HDFC Sky funds into the OpenAlgo common format."""
    try:
        client = get_httpx_client()
        response = client.get(
            f"{get_root_url()}/oapi/v2/funds/view",
            headers=get_hdfcsky_headers(auth_token),
            params={**base_params(auth_token), "type": "all"},
        )
        payload = response.json()
    except Exception as e:
        logger.exception(f"Error fetching HDFC Sky margin data: {e}")
        return {}

    if payload.get("status") == "error":
        logger.error(f"Error fetching HDFC Sky margin data: {payload.get('message')}")
        return {}

    data = payload.get("data") or {}
    values = data.get("values") or []
    if not isinstance(values, list):
        logger.error(f"Unexpected HDFC Sky funds payload shape: {type(values)}")
        return {}

    processed = dict(_EMPTY)
    for row in values:
        if not isinstance(row, dict):
            continue
        key = _LABEL_MAP.get(_norm(row.get("0", "")))
        if key:
            processed[key] = f"{_to_float(row.get('1')):.2f}"

    return processed
