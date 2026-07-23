# broker/hdfcsky/api/funds.py
#
# HDFC Sky funds: GET /oapi/v1/funds/view?client_id=<id>&type=all
#
# The docs describe a V2 endpoint (/oapi/v2/funds/view) but it is not deployed:
# production answers 404 with an EMPTY body, so response.json() cannot be called
# unguarded. V1 is the live endpoint.
#
# V1 returns a label/value table plus two named MTM fields:
#   {"data": {"client_id": "S2998278", "headers": ["Description", "all"],
#             "realized_mtm": "0.00", "unrealized_mtm": "0.00",
#             "values": [["Available Margin", "100.00"],
#                        ["Margin Used", "0.00"], ...]},
#    "message": "", "status": "success"}
#
# Rows arrive as two-element PAIRS. The V2 doc showed {"0": label, "1": value}
# dicts instead, so both shapes are accepted in case V2 ever goes live.

from broker.hdfcsky.api.baseurl import base_params, get_hdfcsky_headers, get_root_url
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)

# HDFC Sky funds label (normalized: lowercase, no spaces) -> OpenAlgo key.
# MTF rows are deliberately excluded - they are a separate margin-funding
# facility and must not inflate the cash/collateral figures.
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


def _row_pair(row):
    """Return (label, value) from either a ["label", "value"] pair or a
    {"0": label, "1": value} dict. Returns None for anything else."""
    if isinstance(row, dict):
        return row.get("0"), row.get("1")
    if isinstance(row, (list, tuple)) and len(row) >= 2:
        return row[0], row[1]
    return None


def get_margin_data(auth_token):
    """Fetch and normalize HDFC Sky funds into the OpenAlgo common format."""
    try:
        client = get_httpx_client()
        response = client.get(
            f"{get_root_url()}/oapi/v1/funds/view",
            headers=get_hdfcsky_headers(auth_token),
            params={**base_params(auth_token), "type": "all"},
        )
        # A 404 or gateway error arrives with an empty or HTML body, so guard
        # the decode rather than letting it raise JSONDecodeError.
        try:
            payload = response.json()
        except ValueError:
            logger.error(
                f"Non-JSON HDFC Sky funds response (HTTP {response.status_code}): "
                f"{response.text[:200]!r}"
            )
            return {}
    except Exception as e:
        logger.exception(f"Error fetching HDFC Sky margin data: {e}")
        return {}

    # An expired or revoked token answers 401 {"error": "invalid credentials"} -
    # note there is no "status" field on that shape, so check the HTTP code and
    # the bare "error" key too. Returning {} (never a zero-filled dict) is what
    # lets blueprints/auth.py detect the dead session and re-authenticate.
    if (
        not isinstance(payload, dict)
        or response.status_code >= 400
        or payload.get("status") == "error"
        or payload.get("error")
    ):
        message = (
            payload.get("message") or payload.get("error")
            if isinstance(payload, dict)
            else payload
        )
        logger.error(
            f"Error fetching HDFC Sky margin data (HTTP {response.status_code}): {message}"
        )
        return {}

    data = payload.get("data") or {}
    values = data.get("values") or []
    if not isinstance(values, list):
        logger.error(f"Unexpected HDFC Sky funds payload shape: {type(values)}")
        return {}

    processed = dict(_EMPTY)
    for row in values:
        pair = _row_pair(row)
        if not pair:
            continue
        key = _LABEL_MAP.get(_norm(pair[0]))
        if key:
            processed[key] = f"{_to_float(pair[1]):.2f}"

    # V1 also reports the MTM figures as named top-level fields. Prefer them:
    # they are the authoritative values and are present even when the labelled
    # rows are not.
    for field, key in (("realized_mtm", "m2mrealized"), ("unrealized_mtm", "m2munrealized")):
        if data.get(field) is not None:
            processed[key] = f"{_to_float(data[field]):.2f}"

    return processed
