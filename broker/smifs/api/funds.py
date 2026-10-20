"""SMIFS God Quant funds for OpenAlgo."""

from broker.smifs.api.baseurl import get_url
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)


def _get_json(client, path, auth_token, default):
    r = client.get(get_url(path), headers={"access-token": auth_token})
    return r.json() if r.status_code == 200 else default


def get_margin_data(auth_token):
    """Fund limits, with realised and unrealised M2M summed from the day's positions."""
    try:
        client = get_httpx_client()
        f = _get_json(client, "/v1/funds/limits", auth_token, {})
        positions = _get_json(client, "/v1/positions", auth_token, [])
    except Exception as e:  # noqa: BLE001
        logger.error(f"SMIFS funds fetch failed: {e}")
        f, positions = {}, []
    if not isinstance(positions, list):
        positions = []
    realised = sum(float(p.get("realizedProfit", 0) or 0) for p in positions)
    unrealised = sum(float(p.get("unrealizedProfit", 0) or 0) for p in positions)
    return {
        "availablecash": f"{float(f.get('availableBalance', 0)):.2f}",
        "collateral": f"{float(f.get('collateralAmount', 0)):.2f}",
        "m2munrealized": f"{unrealised:.2f}",
        "m2mrealized": f"{realised:.2f}",
        "utiliseddebits": f"{float(f.get('utilizedAmount', 0)):.2f}",
    }


def test_auth_token(auth_token):
    try:
        client = get_httpx_client()
        r = client.get(get_url("/v1/funds/limits"), headers={"access-token": auth_token})
        return (r.status_code == 200), (None if r.status_code == 200 else "invalid token")
    except Exception as e:  # noqa: BLE001
        return False, str(e)
