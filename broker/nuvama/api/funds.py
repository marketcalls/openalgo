"""Nuvama funds: GET limits/rmssublimits/{userid}/ (EQLimitsDao).

Fields used (docs 12-limits.md):
- data.cshAvl: cash available
- data.mrgAvl.stkColVal + data.mrgAvl.mfOthColVal: collateral from pledged
  stock and funds
- data.mrgUtd.mrgUtd: margin used
- data.mrgUtd.rlPnl / data.mrgUtd.unRlMtm: realised P&L and unrealised MTM

Every value is taken as Nuvama reports it; a missing one reads as 0.
"""

from broker.nuvama.api.baseurl import BASE_EQ, account_path, nuvama_request
from utils.logging import get_logger

logger = get_logger(__name__)


def _f(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def get_margin_data(auth_token):
    try:
        url = f"{BASE_EQ}limits/rmssublimits/{account_path(auth_token)}/"
        response = nuvama_request("GET", url, auth_token)
    except Exception:
        logger.exception("Nuvama limits request failed")
        return {}

    if not response.ok:
        logger.error(f"Nuvama limits answered {response.status_code}: {response.error_message()}")
        return {}

    data = response.data.get("data") or {}
    available = data.get("mrgAvl") or {}
    utilised = data.get("mrgUtd") or {}

    collateral = _f(available.get("stkColVal")) + _f(available.get("mfOthColVal"))
    return {
        "availablecash": f"{_f(data.get('cshAvl')):.2f}",
        "collateral": f"{collateral:.2f}",
        "m2munrealized": f"{_f(utilised.get('unRlMtm')):.2f}",
        "m2mrealized": f"{_f(utilised.get('rlPnl')):.2f}",
        "utiliseddebits": f"{_f(utilised.get('mrgUtd')):.2f}",
    }
