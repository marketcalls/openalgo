# blueprints/brokerage_charges.py
# REST API for trade-level brokerage estimation (Fyers / Zerodha / Dhan / Groww).
# Powers the "Brokerage" popup in the Position Calculator and the Charges column
# in the order book. The estimate is read from the data-driven tariff table in
# data/broker_charges_comparison.csv.

from flask import Blueprint, jsonify, request, session

from services.brokerage_charges import SUPPORTED_BROKERS, estimate_brokerage
from utils.logging import get_logger
from utils.session import check_session_validity

logger = get_logger(__name__)

brokerage_charges_bp = Blueprint("brokerage_charges_bp", __name__, url_prefix="/brokerage-charges")


def _unsupported_error():
    return (
        jsonify(
            {
                "status": "error",
                "message": "Brokerage is supported only for Fyers, Zerodha, Dhan and Groww",
            }
        ),
        403,
    )


def _order_payload(payload: dict) -> dict:
    """Extract and validate the fields shared by single and batch estimates."""
    return {
        "broker": session.get("broker", ""),
        "exchange": payload.get("exchange", "NSE"),
        "product": payload.get("product", "MIS"),
        "symbol": payload.get("symbol", ""),
        "side": payload.get("side", "BUY"),
        "quantity": payload.get("quantity"),
        "price": payload.get("price"),
        "instrumenttype": payload.get("instrumenttype"),
        "lot_size": payload.get("lotSize") or payload.get("lot_size"),
    }


@brokerage_charges_bp.route("/api/estimate", methods=["POST"])
@check_session_validity
def estimate():
    """Estimate broker charges for a single trade.

    Body: { symbol, exchange, product, side, quantity, price, instrumenttype?, lotSize? }
    """
    broker = (session.get("broker") or "").lower()
    if broker not in SUPPORTED_BROKERS:
        return _unsupported_error()

    payload = request.get_json(silent=True) or {}
    try:
        result = estimate_brokerage(**_order_payload(payload))
    except (TypeError, ValueError) as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400

    return jsonify({"status": "success", "data": result})


@brokerage_charges_bp.route("/api/estimate/batch", methods=["POST"])
@check_session_validity
def estimate_batch():
    """Estimate broker charges for many orders (the order book page).

    Body: { orders: [ { symbol, exchange, product, side, quantity,
                        price, instrumenttype?, lotSize? }, ... ] }
    """
    broker = (session.get("broker") or "").lower()
    if broker not in SUPPORTED_BROKERS:
        return _unsupported_error()

    payload = request.get_json(silent=True) or {}
    orders = payload.get("orders") or []
    if not isinstance(orders, list) or not orders:
        return jsonify({"status": "error", "message": "orders must be a non-empty list"}), 400

    results = []
    for item in orders:
        try:
            results.append({"status": "success", "data": estimate_brokerage(**_order_payload(item))})
        except (TypeError, ValueError) as exc:
            results.append({"status": "error", "message": str(exc)})

    return jsonify({"status": "success", "data": results})
