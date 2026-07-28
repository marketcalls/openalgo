# api/funds.py — TradeSmart (Noren v2) account funds & margin

from broker.tradesmart.api.baseurl import post, resolve_uid
from utils.logging import get_logger

logger = get_logger(__name__)


def calculate_pnl(entry):
    """Calculate realized and unrealized PnL for a position entry."""
    unrealized_pnl = float(entry.get("urmtom", 0))
    realized_pnl = float(entry.get("rpnl", 0))

    # Fallback when the broker doesn't supply the m2m fields directly
    if unrealized_pnl == 0 and float(entry.get("netqty", 0)) != 0:
        price_factor = float(entry.get("prcftr", 1))
        unrealized_pnl = (
            (float(entry.get("lp", 0)) - float(entry.get("netavgprc", 0)))
            * float(entry.get("netqty", 0))
            * price_factor
        )

    return realized_pnl, unrealized_pnl


def get_margin_data(auth_token):
    """Fetch and process margin and position data.

    Returns the OpenAlgo common funds dict (all 2-dp strings); ``{}`` on error.
    """
    userid = resolve_uid(auth_token)
    data = {"uid": userid, "actid": userid}

    # Fetch margin/limits
    margin_response = post("/Limits", data, auth_token)
    try:
        margin_data = margin_response.json()
    except Exception:
        logger.error(f"Limits returned non-JSON: {margin_response.text}")
        return {}

    if margin_data.get("stat") != "Ok":
        logger.info(f"Error fetching margin data: {margin_data.get('emsg')}")
        return {}

    # Fetch positions for realized/unrealized P&L aggregation
    position_response = post("/PositionBook", data, auth_token)
    try:
        position_data = position_response.json()
    except Exception:
        position_data = None

    total_realised = 0.0
    total_unrealised = 0.0
    if isinstance(position_data, list):
        for entry in position_data:
            realized_pnl, unrealized_pnl = calculate_pnl(entry)
            total_realised += realized_pnl
            total_unrealised += unrealized_pnl

    try:
        total_available_margin = (
            float(margin_data.get("cash", 0))
            + float(margin_data.get("payin", 0))
            - float(margin_data.get("marginused", 0))
        )
        total_collateral = float(margin_data.get("brkcollamt", 0))
        total_used_margin = float(margin_data.get("marginused", 0))

        return {
            "availablecash": f"{total_available_margin:.2f}",
            "collateral": f"{total_collateral:.2f}",
            "m2munrealized": f"{total_unrealised:.2f}",
            "m2mrealized": f"{total_realised:.2f}",
            "utiliseddebits": f"{total_used_margin:.2f}",
        }
    except (KeyError, ValueError) as e:
        logger.error(f"Error processing margin data: {e}")
        return {}
