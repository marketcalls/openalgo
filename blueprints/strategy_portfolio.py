"""Strategy Portfolio Blueprint.

Persists Strategy Builder strategies to a local SQLite portfolio with two
fixed watchlists: `mytrades` and `simulation`. Single-user, session-authed
(no /api/v1 exposure — UI-only).
"""

import os

from flask import Blueprint, jsonify, request

from database.strategy_portfolio_db import (
    WATCHLISTS,
    delete_portfolio_entry,
    get_portfolio_entry,
    list_portfolio,
    save_portfolio_entry,
)
from limiter import limiter
from utils.logging import get_logger
from utils.session import check_session_validity

logger = get_logger(__name__)

strategy_portfolio_bp = Blueprint("strategy_portfolio_bp", __name__, url_prefix="/")

# Reasonable read / write rate limits — it's a UI endpoint, not a hot path.
PORTFOLIO_READ_LIMIT = os.getenv("STRATEGY_PORTFOLIO_READ_LIMIT", "60 per minute")
PORTFOLIO_WRITE_LIMIT = os.getenv("STRATEGY_PORTFOLIO_WRITE_LIMIT", "20 per minute")


def _validate_payload(data: dict) -> tuple[bool, str | None]:
    if not isinstance(data, dict):
        return False, "Invalid payload"
    for field in ("name", "watchlist", "underlying", "exchange"):
        if not data.get(field):
            return False, f"'{field}' is required"
    if data["watchlist"] not in WATCHLISTS:
        return False, f"watchlist must be one of {list(WATCHLISTS)}"
    legs = data.get("legs")
    if not isinstance(legs, list) or len(legs) == 0:
        return False, "at least one leg is required"
    if len(data["name"]) > 120:
        return False, "name too long (max 120 chars)"
    return True, None


@strategy_portfolio_bp.route("/api/strategy-portfolio", methods=["GET"])
@check_session_validity
@limiter.limit(PORTFOLIO_READ_LIMIT)
def list_strategies():
    """List saved strategies; optional ?watchlist= filter."""
    watchlist = request.args.get("watchlist")
    if watchlist and watchlist not in WATCHLISTS:
        return (
            jsonify({"status": "error", "message": "invalid watchlist"}),
            400,
        )
    items = list_portfolio(watchlist)
    return jsonify({"status": "success", "items": items})


@strategy_portfolio_bp.route("/api/strategy-portfolio/<int:entry_id>", methods=["GET"])
@check_session_validity
@limiter.limit(PORTFOLIO_READ_LIMIT)
def get_strategy(entry_id: int):
    entry = get_portfolio_entry(entry_id)
    if not entry:
        return jsonify({"status": "error", "message": "not found"}), 404
    return jsonify({"status": "success", "item": entry})


@strategy_portfolio_bp.route("/api/strategy-portfolio", methods=["POST"])
@check_session_validity
@limiter.limit(PORTFOLIO_WRITE_LIMIT)
def create_strategy():
    data = request.get_json(silent=True) or {}
    ok, err = _validate_payload(data)
    if not ok:
        return jsonify({"status": "error", "message": err}), 400
    row = save_portfolio_entry(
        name=data["name"].strip(),
        watchlist=data["watchlist"],
        underlying=data["underlying"],
        exchange=data["exchange"],
        expiry=data.get("expiry"),
        legs=data["legs"],
        notes=data.get("notes"),
    )
    if not row:
        return jsonify({"status": "error", "message": "failed to save"}), 500
    return jsonify({"status": "success", "item": row})


@strategy_portfolio_bp.route("/api/strategy-portfolio/<int:entry_id>", methods=["PUT"])
@check_session_validity
@limiter.limit(PORTFOLIO_WRITE_LIMIT)
def update_strategy(entry_id: int):
    data = request.get_json(silent=True) or {}
    ok, err = _validate_payload(data)
    if not ok:
        return jsonify({"status": "error", "message": err}), 400
    row = save_portfolio_entry(
        entry_id=entry_id,
        name=data["name"].strip(),
        watchlist=data["watchlist"],
        underlying=data["underlying"],
        exchange=data["exchange"],
        expiry=data.get("expiry"),
        legs=data["legs"],
        notes=data.get("notes"),
    )
    if not row:
        return jsonify({"status": "error", "message": "not found"}), 404
    return jsonify({"status": "success", "item": row})


@strategy_portfolio_bp.route(
    "/api/strategy-portfolio/<int:entry_id>", methods=["DELETE"]
)
@check_session_validity
@limiter.limit(PORTFOLIO_WRITE_LIMIT)
def delete_strategy(entry_id: int):
    ok = delete_portfolio_entry(entry_id)
    if not ok:
        return jsonify({"status": "error", "message": "not found"}), 404
    return jsonify({"status": "success"})
