"""SMIFS God Quant funds for OpenAlgo."""
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger
from broker.smifs.api.baseurl import get_url

logger = get_logger(__name__)


def get_margin_data(auth_token):
    try:
        client = get_httpx_client()
        r = client.get(get_url("/v1/funds/limits"), headers={"access-token": auth_token})
        f = r.json() if r.status_code == 200 else {}
    except Exception as e:  # noqa: BLE001
        logger.error(f"SMIFS funds fetch failed: {e}")
        f = {}
    return {
        "availablecash": f"{float(f.get('availableBalance', 0)):.2f}",
        "collateral": f"{float(f.get('collateralAmount', 0)):.2f}",
        "m2munrealized": "0.00",
        "m2mrealized": "0.00",
        "utiliseddebits": f"{float(f.get('utilizedAmount', 0)):.2f}",
    }


def test_auth_token(auth_token):
    try:
        client = get_httpx_client()
        r = client.get(get_url("/v1/funds/limits"), headers={"access-token": auth_token})
        return (r.status_code == 200), (None if r.status_code == 200 else "invalid token")
    except Exception as e:  # noqa: BLE001
        return False, str(e)
