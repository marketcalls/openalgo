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

import math

from flask import Blueprint, jsonify, request, session

from database.auth_db import get_api_key_for_tradingview, get_auth_token
from database.settings_db import get_analyze_mode
from services.expiry_service import get_expiry_dates
from services.option_chain_service import get_option_chain
from utils.logging import get_logger
from utils.session import check_session_validity

# Note: order/close/cancel services are imported lazily inside their routes to
# avoid a circular import at module load (mirrors blueprints/orders.py).

logger = get_logger(__name__)

scalping_bp = Blueprint("scalping_bp", __name__, url_prefix="/")

# Strategy tag stamped on every scalping order (shown in order/trade books).
SCALPING_STRATEGY = "Scalping"

# Order constants enforced on the order endpoint.
VALID_PRODUCTS = {"MIS", "NRML"}  # CNC is equity-only and not used here
VALID_ACTIONS = {"BUY", "SELL"}
VALID_LEG_EXCHANGES = {"NFO", "BFO"}

# Safety rails (server-side; the UI also enforces the lot cap).
MAX_LOTS = 20  # max lots per manual click (matches the UI selector)
MAX_ORDER_QUANTITY = 100_000  # absolute sanity ceiling to block fat-finger/abuse

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


def _resolve_session_auth():
    """Return (auth_token, broker, api_key, error_response, status_code).

    api_key is only populated in analyze (sandbox) mode, mirroring blueprints/orders.py:
    in analyze mode services route to the sandbox using the API key; in live mode they
    use auth_token + broker.
    """
    username = session.get("user")
    if not username:
        return None, None, None, {"status": "error", "message": "Not authenticated"}, 401

    auth_token = get_auth_token(username)
    broker = session.get("broker")
    if not auth_token or not broker:
        return None, None, None, {"status": "error", "message": "Authentication error"}, 401

    api_key = get_api_key_for_tradingview(username) if get_analyze_mode() else None
    return auth_token, broker, api_key, None, None


@scalping_bp.route("/scalping/api/order", methods=["POST"])
@check_session_validity
def order():
    """Place a single MARKET order for a scalping leg (BUY/SELL CE/PE)."""
    data = request.get_json(silent=True) or {}

    symbol = (data.get("symbol") or "").strip()
    exchange = (data.get("exchange") or "").strip().upper()
    action = (data.get("action") or "").strip().upper()
    product = (data.get("product") or "MIS").strip().upper()

    try:
        quantity = int(data.get("quantity", 0))
    except (TypeError, ValueError):
        quantity = 0

    # `lots` is sent on manual entry orders so the lot cap can be enforced
    # server-side. SL auto-exits omit it (they close a raw position quantity).
    lots = data.get("lots")

    if not symbol:
        return jsonify({"status": "error", "message": "symbol is required"}), 400
    if exchange not in VALID_LEG_EXCHANGES:
        return jsonify({"status": "error", "message": f"Invalid exchange: {exchange}"}), 400
    if action not in VALID_ACTIONS:
        return jsonify({"status": "error", "message": f"Invalid action: {action}"}), 400
    if product not in VALID_PRODUCTS:
        return jsonify({"status": "error", "message": f"Invalid product: {product}"}), 400
    if quantity <= 0:
        return jsonify({"status": "error", "message": "quantity must be positive"}), 400
    if quantity > MAX_ORDER_QUANTITY:
        return jsonify({"status": "error", "message": "quantity exceeds the safety limit"}), 400
    if lots is not None:
        try:
            lots = int(lots)
        except (TypeError, ValueError):
            return jsonify({"status": "error", "message": "lots must be an integer"}), 400
        if lots < 1 or lots > MAX_LOTS:
            return jsonify(
                {"status": "error", "message": f"lots must be between 1 and {MAX_LOTS}"}
            ), 400

    auth_token, broker, api_key, err, code = _resolve_session_auth()
    if err:
        return jsonify(err), code

    from services.place_order_service import place_order

    order_data = {
        "strategy": SCALPING_STRATEGY,
        "symbol": symbol,
        "exchange": exchange,
        "action": action,
        "pricetype": "MARKET",
        "product": product,
        "quantity": quantity,
    }

    success, response, status_code = place_order(
        order_data=order_data, api_key=api_key, auth_token=auth_token, broker=broker
    )
    return jsonify(response), status_code


@scalping_bp.route("/scalping/api/close_all", methods=["POST"])
@check_session_validity
def close_all():
    """Square off all open positions (F6)."""
    auth_token, broker, api_key, err, code = _resolve_session_auth()
    if err:
        return jsonify(err), code

    from services.close_position_service import close_position

    success, response, status_code = close_position(
        position_data={}, api_key=api_key, auth_token=auth_token, broker=broker
    )
    return jsonify(response), status_code


@scalping_bp.route("/scalping/api/cancel_all", methods=["POST"])
@check_session_validity
def cancel_all():
    """Cancel all open orders (F7)."""
    auth_token, broker, api_key, err, code = _resolve_session_auth()
    if err:
        return jsonify(err), code

    from services.cancel_all_order_service import cancel_all_orders

    success, response, status_code = cancel_all_orders(
        order_data={}, api_key=api_key, auth_token=auth_token, broker=broker
    )
    return jsonify(response), status_code


@scalping_bp.route("/scalping/api/sl", methods=["GET"])
@check_session_validity
def get_sl_states():
    """Return active stop-loss states to rehydrate the terminal on load."""
    from database.scalping_db import get_active_sl_states

    return jsonify({"status": "success", "data": get_active_sl_states()})


@scalping_bp.route("/scalping/api/sl", methods=["POST"])
@check_session_validity
def upsert_sl():
    """Create or update the stop-loss config for a (symbol, exchange, product) leg."""
    from database.scalping_db import upsert_sl_state

    data = request.get_json(silent=True) or {}
    symbol = (data.get("symbol") or "").strip()
    exchange = (data.get("exchange") or "").strip().upper()
    product = (data.get("product") or "").strip().upper()

    if not symbol or exchange not in VALID_LEG_EXCHANGES or product not in VALID_PRODUCTS:
        return jsonify({"status": "error", "message": "Invalid symbol/exchange/product"}), 400

    # Validate the side and coerce/range-check numeric fields so the browser SL
    # engine can never persist corrupt values (negative qty, NaN/inf prices).
    side = (data.get("side") or "BUY").strip().upper()
    if side not in VALID_ACTIONS:
        return jsonify({"status": "error", "message": f"Invalid side: {side}"}), 400

    try:
        quantity = int(data.get("quantity", 0) or 0)
    except (TypeError, ValueError):
        return jsonify({"status": "error", "message": "quantity must be an integer"}), 400
    if quantity < 0 or quantity > MAX_ORDER_QUANTITY:
        return jsonify({"status": "error", "message": "quantity out of range"}), 400

    cleaned = {
        "symbol": symbol,
        "exchange": exchange,
        "product": product,
        "side": side,
        "quantity": quantity,
    }
    for field in ("entry_price", "initial_sl", "trailing_step", "highest_price",
                  "lowest_price", "current_sl"):
        if data.get(field) is not None:
            try:
                val = float(data[field])
            except (TypeError, ValueError):
                return jsonify({"status": "error", "message": f"{field} must be a number"}), 400
            if not math.isfinite(val) or val < 0:
                return jsonify({"status": "error", "message": f"{field} out of range"}), 400
            cleaned[field] = val
    if "trailing_enabled" in data:
        cleaned["trailing_enabled"] = bool(data["trailing_enabled"])
    if "is_active" in data:
        cleaned["is_active"] = bool(data["is_active"])

    result = upsert_sl_state(cleaned)
    if result is None:
        return jsonify({"status": "error", "message": "Failed to save SL state"}), 500
    return jsonify({"status": "success", "data": result})


@scalping_bp.route("/scalping/api/sl", methods=["DELETE"])
@check_session_validity
def delete_sl():
    """Remove the stop-loss state for a leg (position closed or SL cleared)."""
    from database.scalping_db import delete_sl_state

    data = request.get_json(silent=True) or {}
    symbol = (data.get("symbol") or "").strip()
    exchange = (data.get("exchange") or "").strip().upper()
    product = (data.get("product") or "").strip().upper()

    if not symbol or exchange not in VALID_LEG_EXCHANGES or product not in VALID_PRODUCTS:
        return jsonify({"status": "error", "message": "Invalid symbol/exchange/product"}), 400

    deleted = delete_sl_state(symbol, exchange, product)
    return jsonify({"status": "success", "deleted": deleted})
