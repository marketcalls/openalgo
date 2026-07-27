from broker.iiflcapital.baseurl import BASE_URL
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)


def _to_float(value, default=0.0):
    try:
        if value in (None, "", "-"):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _headers(auth_token):
    return {
        "Authorization": f"Bearer {auth_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _extract_result(payload):
    if not isinstance(payload, dict):
        return {}

    result = payload.get("result", payload)
    if isinstance(result, dict):
        return result
    if isinstance(result, list) and result and isinstance(result[0], dict):
        return result[0]
    return {}


def _fetch_limits(client, endpoint, auth_token):
    try:
        response = client.get(f"{BASE_URL}{endpoint}", headers=_headers(auth_token))
    except Exception:
        logger.exception(f"IIFL Capital limits request failed for endpoint: {endpoint}")
        return {}

    logger.info(f"IIFL Capital limits API response status [{endpoint}]: {response.status_code}")
    logger.info(f"IIFL Capital limits API raw response [{endpoint}]: {response.text}")

    if response.status_code != 200:
        return {}

    try:
        payload = response.json()
    except Exception:
        logger.exception(f"IIFL Capital limits JSON parse failed for endpoint: {endpoint}")
        return {}

    return _extract_result(payload)


def _has_limits_data(limit_data):
    if not isinstance(limit_data, dict):
        return False

    keys = (
        "tradingLimit",
        "openingCashLimit",
        "intradayPayin",
        "collateralMargin",
        "utilizedMargin",
        "creditForSell",
        "adhocMargin",
        "utilizedSpanMargin",
        "utilizedExposureMargin",
    )
    return any(limit_data.get(key) not in (None, "", "-") for key in keys)


def _has_nonzero_limits(limit_data):
    if not isinstance(limit_data, dict):
        return False

    keys = (
        "tradingLimit",
        "openingCashLimit",
        "intradayPayin",
        "collateralMargin",
        "utilizedMargin",
        "creditForSell",
        "adhocMargin",
        "utilizedSpanMargin",
        "utilizedExposureMargin",
    )
    return any(abs(_to_float(limit_data.get(key), 0.0)) > 0 for key in keys)


def _sum_limit_field(limit_rows, field, fallback_field=None):
    total = 0.0
    for row in limit_rows:
        if not isinstance(row, dict):
            continue
        value = row.get(field)
        if value in (None, "", "-") and fallback_field:
            value = row.get(fallback_field)
        total += _to_float(value, 0.0)
    return total


def _format_margin_data(limit_data):
    available = _to_float(limit_data.get("tradingLimit", limit_data.get("openingCashLimit", 0.0)))
    collateral = _to_float(limit_data.get("collateralMargin", 0.0))
    utilized = _to_float(limit_data.get("utilizedMargin", 0.0))

    return {
        "availablecash": f"{available:.2f}",
        "collateral": f"{collateral:.2f}",
        "m2munrealized": "0.00",
        "m2mrealized": "0.00",
        "utiliseddebits": f"{utilized:.2f}",
        "openingcashlimit": f"{_to_float(limit_data.get('openingCashLimit', 0.0)):.2f}",
        "creditforsell": f"{_to_float(limit_data.get('creditForSell', 0.0)):.2f}",
        "adhocmargin": f"{_to_float(limit_data.get('adhocMargin', 0.0)):.2f}",
        "utilizedspanmargin": f"{_to_float(limit_data.get('utilizedSpanMargin', 0.0)):.2f}",
        "utilizedexposuremargin": f"{_to_float(limit_data.get('utilizedExposureMargin', 0.0)):.2f}",
    }


def get_margin_data(auth_token):
    """
    Fetch margin/limits from IIFL Capital and normalize to OpenAlgo fields.

    IIFL exposes pooled limits (`/limits`) and segment-wise limits
    (`/limits/equity`, `/limits/fno`). We prefer pooled values when they are
    meaningful and fallback to segment totals when pooled limits are missing
    or zero.
    """
    client = get_httpx_client()

    pooled_limits = _fetch_limits(client, "/limits", auth_token)
    equity_limits = _fetch_limits(client, "/limits/equity", auth_token)
    fno_limits = _fetch_limits(client, "/limits/fno", auth_token)

    has_pooled = _has_limits_data(pooled_limits)
    has_equity = _has_limits_data(equity_limits)
    has_fno = _has_limits_data(fno_limits)

    pooled_nonzero = _has_nonzero_limits(pooled_limits)
    has_nonzero_segment = _has_nonzero_limits(equity_limits) or _has_nonzero_limits(fno_limits)
    has_any_segment = has_equity or has_fno

    # For accounts where pooled limits are meaningful, prefer `/limits`.
    # Segment-wise endpoints can mirror pooled funds and summing them may
    # double-count balances.
    if pooled_nonzero:
        return _format_margin_data(pooled_limits)

    # Fallback to segment-wise totals when pooled is unavailable or does not
    # carry usable values but segment endpoints do.
    if has_any_segment and (not has_pooled or has_nonzero_segment):
        segments = [equity_limits, fno_limits]
        combined_limits = {
            "tradingLimit": _sum_limit_field(segments, "tradingLimit", "openingCashLimit"),
            "openingCashLimit": _sum_limit_field(segments, "openingCashLimit"),
            "collateralMargin": _sum_limit_field(segments, "collateralMargin"),
            "utilizedMargin": _sum_limit_field(segments, "utilizedMargin"),
            "creditForSell": _sum_limit_field(segments, "creditForSell"),
            "adhocMargin": _sum_limit_field(segments, "adhocMargin"),
            "utilizedSpanMargin": _sum_limit_field(segments, "utilizedSpanMargin"),
            "utilizedExposureMargin": _sum_limit_field(segments, "utilizedExposureMargin"),
        }
        return _format_margin_data(combined_limits)

    if has_pooled:
        return _format_margin_data(pooled_limits)

    return {}
