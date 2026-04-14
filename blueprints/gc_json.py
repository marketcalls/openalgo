# blueprints/gc_json.py

import logging
import os
from collections import OrderedDict

from flask import Blueprint, jsonify, redirect, render_template, request, session, url_for

from database.auth_db import get_api_key_for_tradingview
from database.symbol import enhanced_search_symbols
from utils.session import check_session_validity

logger = logging.getLogger(__name__)

host = os.getenv("HOST_SERVER")

gc_json_bp = Blueprint("gc_json_bp", __name__, url_prefix="/gocharting")


@gc_json_bp.route("/", methods=["GET", "POST"])
@check_session_validity
def gocharting_json():
    if request.method == "POST":
        try:
            symbol_input = request.json.get("symbol")
            exchange = request.json.get("exchange")
            product = request.json.get("product")
            action = request.json.get("action")
            quantity = request.json.get("quantity")

            if not all([symbol_input, exchange, product, action, quantity]):
                logger.error("Missing required fields in GoCharting request")
                return jsonify({"error": "Missing required fields"}), 400

            logger.info(
                f"Processing GoCharting request - Symbol: {symbol_input}, Exchange: {exchange}, Product: {product}, Action: {action}, Quantity: {quantity}"
            )

            # Get actual API key for GoCharting
            api_key = get_api_key_for_tradingview(session.get("user"))
            broker = session.get("broker")

            if not api_key:
                logger.error(f"API key not found for user: {session.get('user')}")
                return jsonify({"error": "API key not found"}), 404

            # Use enhanced search function
            symbols = enhanced_search_symbols(symbol_input, exchange)
            if not symbols:
                logger.warning(f"Symbol not found: {symbol_input}")
                return jsonify({"error": "Symbol not found"}), 404

            symbol_data = symbols[0]  # Take the first match
            logger.info(f"Found matching symbol: {symbol_data.symbol}")

            # Create the JSON response object with OrderedDict for placeorder API
            json_data = OrderedDict(
                [
                    ("apikey", api_key),  # Use actual API key
                    ("strategy", "GoCharting"),
                    ("symbol", symbol_data.symbol),
                    ("action", action.upper()),
                    ("exchange", symbol_data.exchange),
                    ("pricetype", "MARKET"),
                    ("product", product),
                    ("quantity", str(quantity)),
                ]
            )

            logger.info("Successfully generated GoCharting webhook data")
            return jsonify(json_data)

        except Exception as e:
            logger.exception(f"Error processing GoCharting request: {str(e)}")
            return jsonify({"error": str(e)}), 500

    return render_template("gocharting.html", host=host)
