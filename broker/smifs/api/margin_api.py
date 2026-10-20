"""SMIFS God Quant margin calculator for OpenAlgo.

Uses POST /v1/funds/margin/multi, which estimates the margin of up to twenty
legs together and reports the hedge benefit. The figures come from the
platform's own model and are an estimate, not a broker margin statement.
"""

from types import SimpleNamespace

from broker.smifs.api.baseurl import get_url
from broker.smifs.mapping.margin_data import (
    MAX_LEGS,
    parse_margin_response,
    transform_margin_positions,
)
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)


def _headers(auth):
    return {"access-token": auth, "Content-Type": "application/json"}


def _ltp_lookup(auth):
    client = get_httpx_client()

    def lookup(segment, security_id):
        try:
            r = client.post(
                get_url("/v1/marketfeed/ltp"),
                headers=_headers(auth),
                json={segment: [int(security_id)]},
            )
            if r.status_code != 200:
                return 0
            row = (r.json().get("data", {}).get(segment, {}) or {}).get(str(security_id), {})
            return float(row.get("last_price", 0) or 0)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"SMIFS LTP lookup for margin failed: {e}")
            return 0

    return lookup


def _reply(status_code):
    """A response-like object carrying both `status` and `status_code`."""
    return SimpleNamespace(status=status_code, status_code=status_code)


def calculate_margin_api(positions, auth):
    """OpenAlgo margin positions -> (response, OpenAlgo margin dict)."""
    scrips, skipped = transform_margin_positions(positions, _ltp_lookup(auth))
    if not scrips:
        message = "; ".join(skipped) or "no positions were given"
        return _reply(400), {"status": "error", "message": message}
    if len(scrips) > MAX_LEGS:
        return _reply(400), {
            "status": "error",
            "message": f"SMIFS accepts at most {MAX_LEGS} legs in one margin call",
        }
    client = get_httpx_client()
    r = client.post(
        get_url("/v1/funds/margin/multi"), headers=_headers(auth), json={"scrips": scrips}
    )
    try:
        body = r.json()
    except Exception:  # noqa: BLE001
        body = {}
    if r.status_code != 200:
        message = body.get("errorMessage") if isinstance(body, dict) else None
        return _reply(r.status_code), {
            "status": "error",
            "message": message or f"HTTP {r.status_code}",
        }
    result = parse_margin_response(body)
    if skipped:
        result["data"]["skipped_legs"] = skipped
    return _reply(200), result
