# services/pnl_attribution_service.py
"""Live positions or holdings split by strategy, and today's M2M per position.

Backs POST /api/v1/pnl/attribution. It reads the broker's own rows (the
positionbook and holdings services) and the strategy book's legs
(database/strategy_book_db.py), and joins them with
services/strategy_attribution.py, the single place that decides who owns what.
The /positionbook and /holdings responses are not changed.

With `include_m2m` each position row also carries today's M2M
(services/position_m2m.py), computed from today's fills and the previous close.
"""

from database.auth_db import get_auth_token_broker
from database.strategy_book_db import StrategyBookUnavailable
from utils.logging import get_logger

logger = get_logger(__name__)


def _m2m_for_positions(api_key: str, positions: list[dict]):
    """Today's M2M per position row, from today's fills and the previous close
    (services/position_m2m.py). Returns (results keyed by row, error message).
    A failed fetch is reported, never turned into zeros: the caller then falls
    back to the broker's own P&L instead of showing a wrong M2M."""
    from services.position_m2m import SUPPORTED_EXCHANGES, compute_m2m
    from services.quotes_service import get_multiquotes
    from services.tradebook_service import get_tradebook

    # No broker call when nothing here can use the answer (no positions, or only
    # exchanges M2M is not computed for): it would only spend rate-limited quota.
    if not any(row.get("exchange") in SUPPORTED_EXCHANGES for row in positions):
        return compute_m2m(positions, [], {}), None

    ok, tradebook, _ = get_tradebook(api_key=api_key)
    if not ok:
        return {}, "today's trades are unavailable"
    trades = tradebook.get("data") or []

    symbols = sorted(
        {
            (row.get("symbol"), row.get("exchange"))
            for row in positions
            if row.get("exchange") in SUPPORTED_EXCHANGES
        }
    )
    prev_closes: dict[tuple, float | None] = {}
    if symbols:
        ok, quotes, _ = get_multiquotes(
            [{"symbol": symbol, "exchange": exchange} for symbol, exchange in symbols],
            api_key=api_key,
        )
        if not ok:
            return {}, "previous closes are unavailable"
        for item in quotes.get("results") or []:
            prev = (item.get("data") or {}).get("prev_close")
            prev_closes[(item.get("symbol"), item.get("exchange"))] = prev

    return compute_m2m(positions, trades, prev_closes), None


def get_pnl_attribution(api_key: str, kind: str, include_m2m: bool = False):
    """Live positions or holdings split into per-strategy slices, optionally
    with today's M2M per position.

    Returns (success, response, http status). A strategy book that cannot be
    read is a 503, never an answer of "everything is unattributed".
    """
    from database.strategy_book_db import get_strategy_legs as _get_strategy_legs
    from services.holdings_service import get_holdings
    from services.positionbook_service import get_positionbook
    from services.strategy_attribution import KIND_HOLDINGS, KIND_POSITIONS, attribute

    if kind not in (KIND_POSITIONS, KIND_HOLDINGS):
        return False, {"status": "error", "message": "kind must be positions or holdings"}, 400

    auth_token, broker = get_auth_token_broker(api_key)
    if not auth_token:
        return False, {"status": "error", "message": "Invalid openalgo apikey"}, 403

    try:
        # An unreadable book is unknown, not empty: reporting everything as
        # unattributed would look like a healthy answer.
        try:
            legs = _get_strategy_legs()
        except StrategyBookUnavailable as e:
            return False, {"status": "error", "message": str(e)}, 503

        if kind == KIND_POSITIONS:
            success, response, status_code = get_positionbook(api_key=api_key)
        else:
            success, response, status_code = get_holdings(api_key=api_key)
        if not success:
            return False, response, status_code

        data = response.get("data")
        rows = data.get("holdings") if kind == KIND_HOLDINGS and isinstance(data, dict) else data
        if not isinstance(rows, list):
            rows = []

        data = attribute(rows, legs, kind)

        if include_m2m and kind == KIND_POSITIONS:
            m2m_results, m2m_error = _m2m_for_positions(api_key, rows)
            data["m2m_error"] = m2m_error
            for raw, out in zip(rows, data["rows"], strict=True):
                m2m = m2m_results.get((raw.get("symbol"), raw.get("exchange"), raw.get("product")))
                if m2m is None:
                    out["m2m_available"] = False
                    out["m2m_reason"] = m2m_error or "not computed"
                    out["m2m_fixed"] = None
                    out["m2m"] = None
                    out["overnight_quantity"] = None
                    out["prev_close"] = None
                    out["pnl_equals_m2m"] = False
                    continue
                out["m2m_available"] = m2m["available"]
                out["m2m_reason"] = m2m["reason"]
                out["m2m_fixed"] = m2m["m2m_fixed"]
                out["m2m"] = m2m["m2m"]
                out["overnight_quantity"] = m2m["overnight_quantity"]
                out["prev_close"] = m2m["prev_close"]
                # A broker whose own P&L on a carried leg is already the day's M2M
                # (Kotak values the leg at the previous settlement) says so on the
                # row; the two views then coincide, and a page can say so.
                out["pnl_equals_m2m"] = (
                    raw.get("average_price_basis") == "carry_forward_valuation"
                    and abs(m2m["overnight_quantity"]) > 1e-9
                )

        return True, {"status": "success", "data": data}, 200
    except Exception as e:
        logger.exception(f"Error computing P&L attribution: {e}")
        return False, {"status": "error", "message": str(e)}, 500
