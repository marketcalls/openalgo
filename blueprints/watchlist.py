# blueprints/watchlist.py
"""
Watchlist management for the charting terminal.

Session-authenticated rather than API-key authenticated: these are the logged-in
user's own lists, read from the browser they are already signed in to, and there
is nothing here an external platform needs.

Prices are deliberately not served here. The panel gets them from the app's
shared market-data feed, which already streams every instrument on screen and
falls back to /api/v1/multiquotes when that feed is unavailable.

The store is database/watchlist_db.py. This layer is validation, ownership and
HTTP status codes, and nothing else.
"""

from flask import Blueprint, jsonify, request, session

from database.watchlist_db import (
    MAX_ITEMS_PER_LIST,
    add_item,
    clear_watchlist,
    create_watchlist,
    delete_watchlist,
    get_watchlists,
    remove_item,
    rename_watchlist,
    reorder_items,
)
from utils.logging import get_logger
from utils.session import check_session_validity

logger = get_logger(__name__)

watchlist_bp = Blueprint("watchlist_bp", __name__)

#: Long enough to be descriptive, short enough to fit the picker without
#: truncating. Matches the column width in the model.
MAX_NAME_LENGTH = 64


def _user():
    """The signed-in username, or None."""
    return session.get("user")


def _name_from(payload) -> tuple[str | None, tuple | None]:
    """Pull and validate a list name. Returns (name, error_response)."""
    name = (payload.get("name") or "").strip()
    if not name:
        return None, (jsonify({"status": "error", "message": "Name is required"}), 400)
    if len(name) > MAX_NAME_LENGTH:
        return None, (
            jsonify(
                {
                    "status": "error",
                    "message": f"Name must be {MAX_NAME_LENGTH} characters or fewer",
                }
            ),
            400,
        )
    return name, None


@watchlist_bp.route("/watchlist/api/lists", methods=["GET"])
@check_session_validity
def lists():
    """Every list the user has, each with its instruments in display order."""
    return jsonify({"status": "success", "data": get_watchlists(_user())})


@watchlist_bp.route("/watchlist/api/lists", methods=["POST"])
@check_session_validity
def create_list():
    """Create a list.

    ``items`` covers both "make a copy" and importing a list from a file, so
    duplicating a list is one request rather than one per instrument.
    """
    payload = request.get_json(silent=True) or {}
    name, error = _name_from(payload)
    if error:
        return error

    items = payload.get("items")
    if items is not None and not isinstance(items, list):
        return jsonify({"status": "error", "message": "items must be a list"}), 400

    created = create_watchlist(_user(), name, items)
    if created is None:
        # The store returns None for a name clash and for the list cap alike.
        # A clash is what a user actually hits, and it is the one they can act
        # on, so it is what the message describes.
        return jsonify({"status": "error", "message": f'A list named "{name}" already exists'}), 409
    return jsonify({"status": "success", "data": created}), 201


@watchlist_bp.route("/watchlist/api/lists/<int:watchlist_id>", methods=["PATCH"])
@check_session_validity
def rename_list(watchlist_id: int):
    """Rename a list."""
    payload = request.get_json(silent=True) or {}
    name, error = _name_from(payload)
    if error:
        return error

    if not rename_watchlist(_user(), watchlist_id, name):
        return jsonify(
            {"status": "error", "message": "List not found, or that name is already used"}
        ), 409
    return jsonify({"status": "success"})


@watchlist_bp.route("/watchlist/api/lists/<int:watchlist_id>", methods=["DELETE"])
@check_session_validity
def remove_list(watchlist_id: int):
    """Delete a list and its instruments."""
    if not delete_watchlist(_user(), watchlist_id):
        return jsonify({"status": "error", "message": "List not found"}), 404
    return jsonify({"status": "success"})


@watchlist_bp.route("/watchlist/api/lists/<int:watchlist_id>/clear", methods=["POST"])
@check_session_validity
def clear_list(watchlist_id: int):
    """Empty a list, keeping the list itself."""
    if not clear_watchlist(_user(), watchlist_id):
        return jsonify({"status": "error", "message": "List not found"}), 404
    return jsonify({"status": "success"})


@watchlist_bp.route("/watchlist/api/lists/<int:watchlist_id>/items", methods=["POST"])
@check_session_validity
def add_symbol(watchlist_id: int):
    """Add an instrument to a list."""
    payload = request.get_json(silent=True) or {}
    symbol = (payload.get("symbol") or "").strip()
    exchange = (payload.get("exchange") or "").strip()
    if not symbol or not exchange:
        return jsonify({"status": "error", "message": "symbol and exchange are required"}), 400

    item = add_item(_user(), watchlist_id, symbol, exchange)
    if item is None:
        return jsonify(
            {
                "status": "error",
                "message": f"List not found, or it already holds {MAX_ITEMS_PER_LIST} instruments",
            }
        ), 409
    return jsonify({"status": "success", "data": item}), 201


@watchlist_bp.route(
    "/watchlist/api/lists/<int:watchlist_id>/items/<int:item_id>", methods=["DELETE"]
)
@check_session_validity
def remove_symbol(watchlist_id: int, item_id: int):
    """Remove an instrument from a list."""
    if not remove_item(_user(), watchlist_id, item_id):
        return jsonify({"status": "error", "message": "Instrument not found"}), 404
    return jsonify({"status": "success"})


@watchlist_bp.route("/watchlist/api/lists/<int:watchlist_id>/items/order", methods=["PUT"])
@check_session_validity
def order_symbols(watchlist_id: int):
    """Reorder the instruments inside one list."""
    payload = request.get_json(silent=True) or {}
    order = payload.get("order")
    if not isinstance(order, list):
        return jsonify({"status": "error", "message": "order must be a list of ids"}), 400

    if not reorder_items(_user(), watchlist_id, [i for i in order if isinstance(i, int)]):
        return jsonify({"status": "error", "message": "List not found"}), 404
    return jsonify({"status": "success"})
