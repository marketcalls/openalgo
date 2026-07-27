from typing import Dict, List

from flask import Blueprint, flash, jsonify, redirect, render_template, request, session, url_for

from database.symbol import enhanced_search_symbols
from database.token_db_enhanced import fno_search_symbols
from database.token_db_enhanced import get_distinct_expiries_cached as get_distinct_expiries
from database.token_db_enhanced import get_distinct_underlyings_cached as get_distinct_underlyings
from utils.constants import FNO_EXCHANGES
from utils.logging import get_logger
from utils.session import check_session_validity

logger = get_logger(__name__)

search_bp = Blueprint("search_bp", __name__, url_prefix="/search")


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

    # Search is allowed when:
    #   1) a query is provided, OR
    #   2) an exchange is selected (exchange-only browse for ANY exchange — NSE, BSE,
    #      NFO, BFO, MCX, CDS, BCD, NCDEX, NCO, NSE_INDEX, BSE_INDEX, GLOBAL_INDEX,
    #      and crypto exchanges).
    # Without either, refuse — full-table scans aren't useful and are slow.
    if not query and not exchange:
        logger.info("Empty search query received without exchange filter")
        flash("Please enter a search term or select an exchange.", "error")
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
                "contract_value": result.contract_value,
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


def _parse_multi(value: str | None) -> list[str]:
    """Split a comma-separated query parameter into a clean uppercase list."""
    if not value:
        return []
    return [v.strip().upper() for v in value.split(",") if v.strip()]


def _fno_to_api_dict(r: dict) -> dict:
    """Reduce an FNO cache result to the public API shape."""
    return {
        "symbol": r["symbol"],
        "brsymbol": r["brsymbol"],
        "name": r["name"],
        "exchange": r["exchange"],
        "brexchange": r.get("brexchange", ""),
        "token": r["token"],
        "expiry": r["expiry"],
        "strike": r["strike"],
        "lotsize": r.get("lotsize"),
        "contract_value": r.get("contract_value"),
        "instrumenttype": r["instrumenttype"],
        "freeze_qty": r.get("freeze_qty", 1),
    }


@search_bp.route("/api/search")
@check_session_validity
def api_search():
    """API endpoint for AJAX search suggestions with FNO filters.

    Accepts comma-separated values for ``exchange`` and ``instrumenttype`` so
    callers can request multiple exchanges (e.g. ``NSE,BSE``) or instrument
    types (e.g. ``FUT,CE``) in a single request. Single-value callers continue
    to work — a bare value is treated as a one-element list.
    """
    query = request.args.get("q", "").strip() or None

    exchanges = _parse_multi(request.args.get("exchange"))
    inst_types = _parse_multi(request.args.get("instrumenttype"))

    expiry = request.args.get("expiry", "").strip() or None
    underlying = request.args.get("underlying", "").strip() or None
    strike_min_str = request.args.get("strike_min", "").strip()
    strike_max_str = request.args.get("strike_max", "").strip()

    strike_min = float(strike_min_str) if strike_min_str else None
    strike_max = float(strike_max_str) if strike_max_str else None

    has_fno_filters = any([expiry, inst_types, underlying, strike_min, strike_max])

    # Refuse to scan everything: require either a query or at least one exchange.
    if not query and not exchanges:
        logger.debug("Empty API search query received without exchange filter")
        return jsonify({"results": [], "total": 0})

    from database.qty_freeze_db import get_freeze_qty_for_option

    # Outer loop iterates exchanges (may be a single None for "all"); inner loop
    # iterates instrument types so multi-value combinations are evaluated as
    # the union. We dedup by (symbol, exchange) so overlapping filters do not
    # produce duplicate rows.
    exch_iter = exchanges or [None]
    inst_iter = inst_types or [None]

    seen: set[tuple] = set()
    aggregated: list[dict] = []

    for exch in exch_iter:
        # Decide which engine handles this exchange. The FNO engine fires when
        # any FNO-specific filter is set, OR the exchange itself is FNO.
        is_fno_path = has_fno_filters or (exch is not None and exch in FNO_EXCHANGES)

        for inst in inst_iter:
            if is_fno_path:
                rows = fno_search_symbols(
                    query=query,
                    exchange=exch,
                    expiry=expiry,
                    instrumenttype=inst,
                    strike_min=strike_min,
                    strike_max=strike_max,
                    underlying=underlying,
                )
                for r in rows:
                    key = (r.get("symbol"), r.get("exchange"))
                    if key in seen:
                        continue
                    seen.add(key)
                    aggregated.append(_fno_to_api_dict(r))
            else:
                rows = enhanced_search_symbols(query, exch)
                for result in rows:
                    key = (result.symbol, result.exchange)
                    if key in seen:
                        continue
                    seen.add(key)
                    aggregated.append(
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
                            "contract_value": result.contract_value,
                            "instrumenttype": result.instrumenttype,
                            "freeze_qty": get_freeze_qty_for_option(
                                result.symbol, result.exchange
                            ),
                        }
                    )

    logger.debug(f"API search found {len(aggregated)} results across {len(exch_iter)} exchange(s)")
    return jsonify({"results": aggregated, "total": len(aggregated)})


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
    """API endpoint to get available underlying symbols for FNO.

    By default returns options-bearing underlyings only — the right shape for
    option-chain / IV-chart / GEX dropdowns. Pass ``include_futures=true`` to
    also include underlyings whose only live derivatives are futures (e.g. MCX
    commodities like NATURALGASMINI, COPPER, LEADMINI). Used by /search/token.
    """
    exchange = request.args.get("exchange", "").strip() or None
    include_futures = request.args.get("include_futures", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )

    logger.debug(
        f"Fetching underlyings: exchange={exchange}, include_futures={include_futures}"
    )
    underlyings = get_distinct_underlyings(exchange=exchange, include_futures=include_futures)

    # Filter out exchange test symbols (e.g. 011NSETEST, 021BSETEST)
    underlyings = [u for u in underlyings if "NSETEST" not in u and "BSETEST" not in u]

    return jsonify({"status": "success", "underlyings": underlyings})
