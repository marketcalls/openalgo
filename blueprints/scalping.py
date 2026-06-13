"""
Scalping Blueprint - Keyboard-driven options scalping terminal.

Serves the symbol/expiry/strike resolution API for the /scalping React page.
Reuses OpenAlgo option services and order constants. Order placement and
position management endpoints are added in later phases.

Order constants (docs/prompt/order-constants.md):
- Underlying exchange : NSE_INDEX, BSE_INDEX
- Leg exchange        : NFO (NSE index options), BFO (BSE index options)
- Product             : NRML, MIS  (CNC is equity-only and not used here)
- Price type          : MARKET (entry/exit)
- Action              : BUY, SELL
"""

from flask import Blueprint, jsonify, request, session

from database.auth_db import get_api_key_for_tradingview
from services.expiry_service import get_expiry_dates
from services.option_chain_service import get_option_chain
from utils.logging import get_logger
from utils.session import check_session_validity

logger = get_logger(__name__)

scalping_bp = Blueprint("scalping_bp", __name__, url_prefix="/")

# Supported index underlyings for v1, mapped to their index (quote) exchange and
# F&O (tradable) exchange. Keep this the single source of truth for the dropdown.
SUPPORTED_UNDERLYINGS = {
    "NIFTY": {"index_exchange": "NSE_INDEX", "fo_exchange": "NFO"},
    "BANKNIFTY": {"index_exchange": "NSE_INDEX", "fo_exchange": "NFO"},
    "FINNIFTY": {"index_exchange": "NSE_INDEX", "fo_exchange": "NFO"},
    "MIDCPNIFTY": {"index_exchange": "NSE_INDEX", "fo_exchange": "NFO"},
    "NIFTYNXT50": {"index_exchange": "NSE_INDEX", "fo_exchange": "NFO"},
    "SENSEX": {"index_exchange": "BSE_INDEX", "fo_exchange": "BFO"},
    "BANKEX": {"index_exchange": "BSE_INDEX", "fo_exchange": "BFO"},
}


def _get_api_key():
    """Resolve the current user's OpenAlgo API key from session."""
    username = session.get("user")
    if not username:
        return None
    return get_api_key_for_tradingview(username)


def _normalize_expiry(expiry: str) -> str:
    """Normalize an expiry string to DDMMMYY uppercase (e.g. '10-JUL-25' -> '10JUL25')."""
    return expiry.replace("-", "").replace(" ", "").upper()


@scalping_bp.route("/scalping/api/underlyings", methods=["GET"])
@check_session_validity
def underlyings():
    """Return the supported index underlyings and their exchanges for the dropdown."""
    data = [
        {
            "underlying": name,
            "index_exchange": cfg["index_exchange"],
            "fo_exchange": cfg["fo_exchange"],
        }
        for name, cfg in SUPPORTED_UNDERLYINGS.items()
    ]
    return jsonify({"status": "success", "data": data})


@scalping_bp.route("/scalping/api/expiry", methods=["GET"])
@check_session_validity
def expiry():
    """Return option expiry dates (DDMMMYY) for a supported underlying."""
    underlying = (request.args.get("underlying") or "").strip().upper()
    if underlying not in SUPPORTED_UNDERLYINGS:
        return jsonify({"status": "error", "message": f"Unsupported underlying: {underlying}"}), 400

    api_key = _get_api_key()
    if not api_key:
        return jsonify(
            {"status": "error", "message": "API key not configured. Generate one at /apikey"}
        ), 401

    fo_exchange = SUPPORTED_UNDERLYINGS[underlying]["fo_exchange"]
    success, response, status_code = get_expiry_dates(
        symbol=underlying, exchange=fo_exchange, instrumenttype="options", api_key=api_key
    )
    if not success:
        return jsonify(response), status_code

    raw_dates = response.get("data", []) or []
    normalized = [_normalize_expiry(d) for d in raw_dates]
    return jsonify({"status": "success", "data": normalized})


@scalping_bp.route("/scalping/api/strikes", methods=["GET"])
@check_session_validity
def strikes():
    """Return the option chain (CE/PE strikes around ATM) for an underlying + expiry."""
    underlying = (request.args.get("underlying") or "").strip().upper()
    if underlying not in SUPPORTED_UNDERLYINGS:
        return jsonify({"status": "error", "message": f"Unsupported underlying: {underlying}"}), 400

    expiry_date = (request.args.get("expiry") or "").strip().upper()
    if not expiry_date:
        return jsonify({"status": "error", "message": "expiry parameter is required"}), 400

    try:
        strike_count = int(request.args.get("strike_count", 10))
    except (TypeError, ValueError):
        strike_count = 10
    strike_count = max(1, min(strike_count, 50))

    api_key = _get_api_key()
    if not api_key:
        return jsonify(
            {"status": "error", "message": "API key not configured. Generate one at /apikey"}
        ), 401

    index_exchange = SUPPORTED_UNDERLYINGS[underlying]["index_exchange"]
    success, response, status_code = get_option_chain(
        underlying=underlying,
        exchange=index_exchange,
        expiry_date=_normalize_expiry(expiry_date),
        strike_count=strike_count,
        api_key=api_key,
    )
    if not success:
        return jsonify(response), status_code

    # Pass through the chain plus the F&O exchange the legs trade on, so the
    # frontend can subscribe and (in Phase 1) place orders with the right exchange.
    response["fo_exchange"] = SUPPORTED_UNDERLYINGS[underlying]["fo_exchange"]
    response["index_exchange"] = index_exchange
    return jsonify(response), status_code
