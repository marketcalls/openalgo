from typing import Dict, List

from flask import Blueprint, flash, jsonify, redirect, render_template, request, session, url_for

from database.symbol import enhanced_search_symbols
from database.token_db_enhanced import fno_search_symbols
from database.token_db_enhanced import get_distinct_expiries_cached as get_distinct_expiries
from database.token_db_enhanced import get_distinct_underlyings_cached as get_distinct_underlyings
from utils.logging import get_logger
from utils.session import check_session_validity

logger = get_logger(__name__)

search_bp = Blueprint("search_bp", __name__, url_prefix="/search")

# FNO exchanges that support advanced filters
FNO_EXCHANGES = ["NFO", "BFO", "MCX", "CDS"]


@search_bp.route("/token")
@check_session_validity
def token():
    """Route for the search form page"""
    return render_template("token.html")


@search_bp.route("/")
@check_session_validity
def search():
    """Main search route for full results page with FNO filters"""
    query = request.args.get("symbol", "").strip() or None
    exchange = request.args.get("exchange")

    # FNO filter parameters
    expiry = request.args.get("expiry", "").strip() or None
    instrumenttype = request.args.get("instrumenttype", "").strip() or None
    underlying = request.args.get("underlying", "").strip() or None
    strike_min_str = request.args.get("strike_min", "").strip()
    strike_max_str = request.args.get("strike_max", "").strip()

    # Parse strike range
    strike_min = float(strike_min_str) if strike_min_str else None
    strike_max = float(strike_max_str) if strike_max_str else None

    # Check if any FNO filters are applied
    has_fno_filters = any([expiry, instrumenttype, underlying, strike_min, strike_max])

    # For non-FNO exchanges, query is required
    # For FNO exchanges with filters, query is optional
    if not query and not (exchange in FNO_EXCHANGES and has_fno_filters):
        logger.info("Empty search query received without FNO filters")
        flash("Please enter a search term or select FNO filters.", "error")
        return render_template("token.html")

    # Use FNO search if any FNO filters are applied or it's an FNO exchange
    if has_fno_filters or exchange in FNO_EXCHANGES:
        logger.info(
            f"FNO search: query={query}, exchange={exchange}, expiry={expiry}, "
            f"type={instrumenttype}, underlying={underlying}, strike={strike_min}-{strike_max}"
        )
        # fno_search_symbols returns list of dicts directly (cache-based)
        results_dicts = fno_search_symbols(
            query=query,
            exchange=exchange,
            expiry=expiry,
            instrumenttype=instrumenttype,
            strike_min=strike_min,
            strike_max=strike_max,
            underlying=underlying,
        )
    else:
        logger.info(f"Standard search: query={query}, exchange={exchange}")
        results = enhanced_search_symbols(query, exchange)
        # Import freeze qty function for non-FNO exchanges
        from database.qty_freeze_db import get_freeze_qty_for_option

        # Convert SymToken objects to dicts
        results_dicts = [
            {
                "symbol": result.symbol,
                "brsymbol": result.brsymbol,
                "name": result.name,
                "exchange": result.exchange,
                "brexchange": result.brexchange,
                "token": result.token,
                "expiry": result.expiry,
                "strike": result.strike,
                "lotsize": result.lotsize,
                "instrumenttype": result.instrumenttype,
                "tick_size": result.tick_size,
                "freeze_qty": get_freeze_qty_for_option(result.symbol, result.exchange),
            }
            for result in results
        ]

    if not results_dicts:
        logger.info(f"No results found for query: {query}")
        flash("No matching symbols found.", "error")
        return render_template("token.html")

    logger.info(f"Found {len(results_dicts)} results for query: {query}")
    return render_template("search.html", results=results_dicts)


@search_bp.route("/api/search")
@check_session_validity
def api_search():
    """API endpoint for AJAX search suggestions with FNO filters"""
    query = request.args.get("q", "").strip() or None
    exchange = request.args.get("exchange")

    # FNO filter parameters
    expiry = request.args.get("expiry", "").strip() or None
    instrumenttype = request.args.get("instrumenttype", "").strip() or None
    underlying = request.args.get("underlying", "").strip() or None
    strike_min_str = request.args.get("strike_min", "").strip()
    strike_max_str = request.args.get("strike_max", "").strip()

    # Parse strike range
    strike_min = float(strike_min_str) if strike_min_str else None
    strike_max = float(strike_max_str) if strike_max_str else None

    # Check if any FNO filters are applied
    has_fno_filters = any([expiry, instrumenttype, underlying, strike_min, strike_max])

    # Allow filter-only search for FNO exchanges
    if not query and not (exchange in FNO_EXCHANGES and has_fno_filters):
        logger.debug("Empty API search query received without FNO filters")
        return jsonify({"results": []})

    # Use FNO search if any FNO filters are applied
    if has_fno_filters or exchange in FNO_EXCHANGES:
        logger.debug(
            f"FNO API search: query={query}, exchange={exchange}, filters={has_fno_filters}"
        )
        # fno_search_symbols returns list of dicts directly (cache-based)
        results_dicts = fno_search_symbols(
            query=query,
            exchange=exchange,
            expiry=expiry,
            instrumenttype=instrumenttype,
            strike_min=strike_min,
            strike_max=strike_max,
            underlying=underlying,
        )
        # Reduce fields for API response (freeze_qty already in results)
        results_dicts = [
            {
                "symbol": r["symbol"],
                "brsymbol": r["brsymbol"],
                "name": r["name"],
                "exchange": r["exchange"],
                "brexchange": r.get("brexchange", ""),
                "token": r["token"],
                "expiry": r["expiry"],
                "strike": r["strike"],
                "lotsize": r.get("lotsize"),
                "instrumenttype": r["instrumenttype"],
                "freeze_qty": r.get("freeze_qty", 1),
            }
            for r in results_dicts
        ]
    else:
        logger.debug(f"Standard API search: query={query}, exchange={exchange}")
        results = enhanced_search_symbols(query, exchange)
        # Import freeze qty function for non-FNO exchanges
        from database.qty_freeze_db import get_freeze_qty_for_option

        # Convert SymToken objects to dicts
        results_dicts = [
            {
                "symbol": result.symbol,
                "brsymbol": result.brsymbol,
                "name": result.name,
                "exchange": result.exchange,
                "brexchange": result.brexchange,
                "token": result.token,
                "expiry": result.expiry,
                "strike": result.strike,
                "lotsize": result.lotsize,
                "instrumenttype": result.instrumenttype,
                "freeze_qty": get_freeze_qty_for_option(result.symbol, result.exchange),
            }
            for result in results
        ]

    logger.debug(f"API search found {len(results_dicts)} results")
    return jsonify({"results": results_dicts})


@search_bp.route("/api/expiries")
@check_session_validity
def api_expiries():
    """API endpoint to get available expiry dates for FNO symbols"""
    exchange = request.args.get("exchange", "").strip() or None
    underlying = request.args.get("underlying", "").strip() or None

    logger.debug(f"Fetching expiries: exchange={exchange}, underlying={underlying}")
    expiries = get_distinct_expiries(exchange=exchange, underlying=underlying)

    return jsonify({"status": "success", "expiries": expiries})


@search_bp.route("/api/underlyings")
@check_session_validity
def api_underlyings():
    """API endpoint to get available underlying symbols for FNO"""
    exchange = request.args.get("exchange", "").strip() or None

    logger.debug(f"Fetching underlyings: exchange={exchange}")
    underlyings = get_distinct_underlyings(exchange=exchange)

    # Filter out exchange test symbols (e.g. 011NSETEST, 021BSETEST)
    underlyings = [u for u in underlyings if "NSETEST" not in u and "BSETEST" not in u]

    return jsonify({"status": "success", "underlyings": underlyings})
