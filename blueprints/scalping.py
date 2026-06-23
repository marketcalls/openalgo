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
import re
from datetime import datetime, timedelta

import pytz
from flask import Blueprint, jsonify, request, session

from database.auth_db import get_api_key_for_tradingview
from database.settings_db import get_analyze_mode
from services.expiry_service import get_expiry_dates
from services.history_service import get_history
from services.option_chain_service import get_option_chain
from utils.logging import get_logger
from utils.session import check_session_validity

# Note: order/close/cancel services are imported lazily inside their routes to
# avoid a circular import at module load (mirrors blueprints/orders.py).

logger = get_logger(__name__)

scalping_bp = Blueprint("scalping_bp", __name__, url_prefix="/")

# Strategy tag stamped on every scalping order (shown in order/trade books).
SCALPING_STRATEGY = "Scalping"

# Chart history: IST timezone + per-interval lookback (trading days). The bar
# time carries a +5h30m offset so lightweight-charts (which renders UTC) shows
# IST, and the client's live forming candle aligns with the history bars.
IST = pytz.timezone("Asia/Kolkata")
IST_OFFSET_SECONDS = 19800
CHART_INTERVAL_TRADING_DAYS = {"1m": 1, "5m": 3, "15m": 9}

# Order constants enforced on the order endpoint.
VALID_ACTIONS = {"BUY", "SELL"}
# Derivatives (options/futures): lot rules apply. NFO/BFO (index+stock F&O),
# MCX (commodity), CDS (currency).
VALID_LEG_EXCHANGES = {"NFO", "BFO", "MCX", "CDS"}
VALID_EQUITY_EXCHANGES = {"NSE", "BSE"}  # equity: traded in shares, no lot rules
VALID_ORDER_EXCHANGES = VALID_LEG_EXCHANGES | VALID_EQUITY_EXCHANGES
# Products allowed per instrument class.
DERIVATIVE_PRODUCTS = {"MIS", "NRML"}
EQUITY_PRODUCTS = {"MIS", "CNC"}
VALID_PRODUCTS = DERIVATIVE_PRODUCTS | EQUITY_PRODUCTS


def _is_derivative(exchange: str) -> bool:
    return exchange in VALID_LEG_EXCHANGES


def _allowed_products(exchange: str) -> set[str]:
    return DERIVATIVE_PRODUCTS if _is_derivative(exchange) else EQUITY_PRODUCTS


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


# Index underlyings whose spot LTP comes from the index feed (NSE_INDEX/BSE_INDEX);
# everything else on NFO/BFO is a stock (NSE/BSE spot). MCX/CDS use the future.
_NSE_INDEX_UNDERLYINGS = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50", "INDIAVIX"}
_BSE_INDEX_UNDERLYINGS = {"SENSEX", "BANKEX", "SENSEX50"}


def _underlying_quote(underlying: str, fo_exchange: str):
    """Return (symbol, exchange) to subscribe for the underlying's live LTP."""
    if fo_exchange == "NFO":
        return underlying, ("NSE_INDEX" if underlying in _NSE_INDEX_UNDERLYINGS else "NSE")
    if fo_exchange == "BFO":
        return underlying, ("BSE_INDEX" if underlying in _BSE_INDEX_UNDERLYINGS else "BSE")
    return None, None  # MCX/CDS underlying is the current-month future (set separately)


def _current_mode() -> str:
    """Trading mode for segregating scalping state: 'analyze' (sandbox) or 'live'."""
    return "analyze" if get_analyze_mode() else "live"


def _notify_risk_monitor():
    """Tell the server-side risk monitor an SL was saved/deleted (event-driven sync).

    Lazily imported to avoid a circular import at module load. Never raises into
    the request path — a monitor hiccup must not fail the SL save itself.
    """
    try:
        from services.scalping_risk_monitor_service import notify_sl_changed

        notify_sl_changed()
    except Exception as e:
        logger.debug(f"Risk monitor notify skipped: {e}")


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


@scalping_bp.route("/scalping/api/history", methods=["GET"])
@check_session_validity
def chart_history():
    """Return candles for the most recent N trading days at the given interval.

    Powers the scalping charts (candles + volume). ``interval`` is an OpenAlgo
    interval (1m/5m/15m); the lookback scales 1m->1 day, 5m->3, 15m->9. A
    generous calendar window is fetched and the latest N IST dates with data are
    kept (skips weekends/holidays without a calendar lookup). An optional
    ``date=YYYY-MM-DD`` restricts the fetch to a single day (used by the chart's
    periodic reconcile). Works for any exchange (options, futures, equity,
    indices); index symbols simply carry volume 0.
    """
    api_key = _get_api_key()
    if not api_key:
        return jsonify({"status": "error", "message": "API key not configured"}), 401

    symbol = (request.args.get("symbol", "") or "").strip().upper()[:50]
    exchange = (request.args.get("exchange", "") or "").strip().upper()[:20]
    if not symbol or not exchange:
        return jsonify({"status": "error", "message": "symbol and exchange are required"}), 400

    interval = (request.args.get("interval", "1m") or "1m").strip()
    if interval not in CHART_INTERVAL_TRADING_DAYS:
        interval = "1m"

    date_param = (request.args.get("date", "") or "").strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}$", date_param):
        start_date = date_param
        end_date = date_param
        keep_days = 1
    else:
        keep_days = CHART_INTERVAL_TRADING_DAYS[interval]
        today = datetime.now(IST).date()
        start_date = (today - timedelta(days=keep_days * 2 + 5)).strftime("%Y-%m-%d")
        end_date = today.strftime("%Y-%m-%d")

    try:
        success, response, status_code = get_history(
            symbol=symbol,
            exchange=exchange,
            interval=interval,
            start_date=start_date,
            end_date=end_date,
            api_key=api_key,
        )
    except Exception as e:
        logger.exception(f"scalping chart history error for {symbol}.{exchange}: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

    if not success:
        message = response.get("message") if isinstance(response, dict) else str(response)
        return jsonify(
            {"status": "error", "message": message or "History fetch failed"}
        ), status_code

    rows = response.get("data", []) if isinstance(response, dict) else []
    by_date: dict[str, list] = {}
    for r in rows:
        ts = r.get("timestamp")
        if ts is None:
            continue
        try:
            ts = int(float(ts))
        except (TypeError, ValueError):
            continue
        ist_dt = datetime.fromtimestamp(ts, tz=pytz.utc).astimezone(IST)
        by_date.setdefault(ist_dt.strftime("%Y-%m-%d"), []).append((ts, r))

    if not by_date:
        return jsonify(
            {
                "status": "success",
                "symbol": symbol,
                "exchange": exchange,
                "interval": interval,
                "date": None,
                "candles": [],
            }
        ), 200

    selected_dates = sorted(by_date.keys())[-keep_days:]
    latest_date = selected_dates[-1]
    day_rows: list = []
    for dkey in selected_dates:
        day_rows.extend(by_date[dkey])
    day_rows.sort(key=lambda x: x[0])

    candles = []
    for ts, r in day_rows:
        # 5m/15m timestamps are already minute-aligned, so the minute floor is a
        # no-op for them; it only normalizes 1m bars.
        bar_time = ((ts + IST_OFFSET_SECONDS) // 60) * 60
        try:
            candles.append(
                {
                    "time": bar_time,
                    "open": float(r.get("open", 0)),
                    "high": float(r.get("high", 0)),
                    "low": float(r.get("low", 0)),
                    "close": float(r.get("close", 0)),
                    "volume": float(r.get("volume", 0) or 0),
                }
            )
        except (TypeError, ValueError):
            continue

    return jsonify(
        {
            "status": "success",
            "symbol": symbol,
            "exchange": exchange,
            "interval": interval,
            "date": latest_date,
            "candles": candles,
        }
    ), 200


@scalping_bp.route("/scalping/api/all_underlyings", methods=["GET"])
@check_session_validity
def all_underlyings():
    """Return every F&O underlying available for an exchange (indices first).

    Backs the Underlying dropdown, mirroring /search/token. Options mode returns
    options-bearing underlyings; Futures mode also includes futures-only
    underlyings (e.g. MCX commodities like NATURALGASMINI). MCX/CDS always
    include futures-backed names since their options reference the future.
    """
    exchange = (request.args.get("exchange", "NFO").strip() or "NFO").upper()
    instrumenttype = (request.args.get("instrumenttype", "options").strip() or "options").lower()
    include_futures = instrumenttype == "futures" or exchange in ("MCX", "CDS")

    try:
        from database.token_db_enhanced import get_distinct_underlyings_cached

        names = get_distinct_underlyings_cached(exchange=exchange, include_futures=include_futures)
    except Exception as e:  # noqa: BLE001 - degrade gracefully if cache/db unavailable
        logger.exception(f"Error fetching underlyings for {exchange}: {e}")
        names = []

    # Drop exchange test symbols (e.g. 011NSETEST, 021BSETEST).
    names = [u for u in names if "NSETEST" not in u and "BSETEST" not in u]

    # Indices at the top, then the rest alphabetically (matches the search/token UX).
    index_names = _NSE_INDEX_UNDERLYINGS | _BSE_INDEX_UNDERLYINGS
    indices = sorted(u for u in names if u in index_names)
    rest = sorted(u for u in names if u not in index_names)
    return jsonify({"status": "success", "data": indices + rest})


@scalping_bp.route("/scalping/api/expiry", methods=["GET"])
@check_session_validity
def expiry():
    """Return expiry dates (DDMMMYY) for an underlying on an F&O exchange."""
    underlying = (request.args.get("underlying") or "").strip().upper()
    exchange = (request.args.get("exchange") or "").strip().upper()
    instrumenttype = (request.args.get("instrumenttype") or "options").strip().lower()
    if not underlying:
        return jsonify({"status": "error", "message": "underlying is required"}), 400
    if exchange not in VALID_LEG_EXCHANGES:
        return jsonify({"status": "error", "message": f"Invalid exchange: {exchange}"}), 400

    api_key = _get_api_key()
    if not api_key:
        return jsonify(
            {"status": "error", "message": "API key not configured. Generate one at /apikey"}
        ), 401

    success, response, status_code = get_expiry_dates(
        symbol=underlying, exchange=exchange, instrumenttype=instrumenttype, api_key=api_key
    )
    if not success:
        return jsonify(response), status_code

    raw_dates = response.get("data", []) or []
    normalized = [_normalize_expiry(d) for d in raw_dates]
    return jsonify({"status": "success", "data": normalized})


def _parse_expiry(s: str):
    from datetime import datetime

    for fmt in ("%d-%b-%y", "%d-%b-%Y", "%d%b%y"):
        try:
            return datetime.strptime((s or "").upper(), fmt)
        except ValueError:
            continue
    from datetime import datetime as _dt

    return _dt.max


def _mcx_cds_option_chain(underlying, exchange, expiry_ddmmmyy, strike_count, api_key):
    """Option chain for MCX/CDS where the ATM reference is the current-month future
    (no spot symbol exists). Returns (success, response, code) matching get_option_chain.
    """
    from database.symbol import SymToken
    from database.symbol import db_session as symbol_session
    from services.quotes_service import get_quotes

    futs = (
        symbol_session.query(SymToken)
        .filter(
            SymToken.exchange == exchange,
            SymToken.name == underlying,
            SymToken.instrumenttype == "FUT",
        )
        .all()
    )
    futs = sorted(futs, key=lambda r: _parse_expiry(r.expiry))
    if not futs:
        return False, {"status": "error", "message": f"No futures for {underlying} on {exchange}"}, 400
    fut_symbol = futs[0].symbol
    ok, qresp, _qc = get_quotes(symbol=fut_symbol, exchange=exchange, api_key=api_key)
    ltp = float((qresp.get("data") or {}).get("ltp") or 0) if ok and isinstance(qresp, dict) else 0
    if ltp <= 0:
        return False, {"status": "error", "message": f"No LTP for {fut_symbol}"}, 400

    opts = (
        symbol_session.query(SymToken)
        .filter(
            SymToken.exchange == exchange,
            SymToken.name == underlying,
            SymToken.instrumenttype.in_(("CE", "PE")),
        )
        .all()
    )
    by_strike: dict = {}
    for r in opts:
        if _normalize_expiry(r.expiry or "") != expiry_ddmmmyy:
            continue
        by_strike.setdefault(r.strike, {})[r.instrumenttype] = r
    all_strikes = sorted(by_strike)
    if not all_strikes:
        return False, {"status": "error", "message": "No option strikes for that expiry"}, 400

    atm = min(all_strikes, key=lambda s: abs(s - ltp))
    atm_idx = all_strikes.index(atm)
    lo = max(0, atm_idx - strike_count)
    hi = min(len(all_strikes), atm_idx + strike_count + 1)

    chain = []
    for s in all_strikes[lo:hi]:
        n = all_strikes.index(s) - atm_idx
        ce_label = "ATM" if n == 0 else (f"ITM{abs(n)}" if n < 0 else f"OTM{n}")
        pe_label = "ATM" if n == 0 else (f"OTM{abs(n)}" if n < 0 else f"ITM{n}")
        ce = by_strike[s].get("CE")
        pe = by_strike[s].get("PE")
        chain.append(
            {
                "strike": s,
                "ce": {
                    "symbol": ce.symbol if ce else None,
                    "label": ce_label,
                    "lotsize": ce.lotsize if ce else None,
                    "tick_size": ce.tick_size if ce else None,
                },
                "pe": {
                    "symbol": pe.symbol if pe else None,
                    "label": pe_label,
                    "lotsize": pe.lotsize if pe else None,
                    "tick_size": pe.tick_size if pe else None,
                },
            }
        )

    return (
        True,
        {
            "status": "success",
            "underlying": underlying,
            "underlying_ltp": ltp,
            "underlying_symbol": fut_symbol,
            "underlying_exchange": exchange,
            "expiry_date": expiry_ddmmmyy,
            "atm_strike": atm,
            "chain": chain,
            "fo_exchange": exchange,
        },
        200,
    )


@scalping_bp.route("/scalping/api/strikes", methods=["GET"])
@check_session_validity
def strikes():
    """Option chain (CE/PE around ATM) for underlying + expiry on any F&O exchange."""
    underlying = (request.args.get("underlying") or "").strip().upper()
    exchange = (request.args.get("exchange") or "").strip().upper()
    if not underlying:
        return jsonify({"status": "error", "message": "underlying is required"}), 400
    if exchange not in VALID_LEG_EXCHANGES:
        return jsonify({"status": "error", "message": f"Invalid exchange: {exchange}"}), 400

    expiry_date = _normalize_expiry((request.args.get("expiry") or "").strip().upper())
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

    # The scalping ladder only needs the strike list + ATM + symbols (it streams live
    # prices over the WebSocket feed), so default to a structure-only build that skips
    # the slow per-strike broker multiquote. Pass ?quotes=true to include live quotes.
    with_quotes = (request.args.get("quotes", "false").strip().lower() == "true")

    if exchange in ("NFO", "BFO"):
        success, response, status_code = get_option_chain(
            underlying=underlying,
            exchange=exchange,
            expiry_date=expiry_date,
            strike_count=strike_count,
            api_key=api_key,
            with_quotes=with_quotes,
        )
        if isinstance(response, dict):
            response["fo_exchange"] = exchange
            u_sym, u_exch = _underlying_quote(underlying, exchange)
            response["underlying_symbol"] = u_sym
            response["underlying_exchange"] = u_exch
        return jsonify(response), status_code

    # MCX / CDS — ATM from the current-month future.
    success, response, status_code = _mcx_cds_option_chain(
        underlying, exchange, expiry_date, strike_count, api_key
    )
    return jsonify(response), status_code


@scalping_bp.route("/scalping/api/search", methods=["GET"])
@check_session_validity
def search():
    """Search instruments on an exchange (equity on NSE/BSE, futures on NFO/BFO)."""
    exchange = (request.args.get("exchange") or "").strip().upper()
    query = (request.args.get("query") or "").strip()
    if exchange not in VALID_ORDER_EXCHANGES:
        return jsonify({"status": "error", "message": f"Invalid exchange: {exchange}"}), 400
    if len(query) < 2:
        return jsonify({"status": "success", "data": []})

    api_key = _get_api_key()
    if not api_key:
        return jsonify(
            {"status": "error", "message": "API key not configured. Generate one at /apikey"}
        ), 401

    from services.search_service import search_symbols

    success, response, status_code = search_symbols(query=query, exchange=exchange, api_key=api_key)
    return jsonify(response), status_code


@scalping_bp.route("/scalping/api/futures", methods=["GET"])
@check_session_validity
def futures():
    """Return the futures contracts for an underlying on a derivative exchange.

    Lets the UI offer a per-expiry futures picker (underlying + expiry -> the framed
    FUT symbol) for any exchange (NFO/BFO/MCX/CDS).
    """
    underlying = (request.args.get("underlying") or "").strip().upper()
    exchange = (request.args.get("exchange") or "").strip().upper()
    if not underlying:
        return jsonify({"status": "error", "message": "underlying is required"}), 400
    if exchange not in VALID_LEG_EXCHANGES:
        return jsonify({"status": "error", "message": f"Invalid exchange: {exchange}"}), 400

    from datetime import datetime

    from database.symbol import SymToken
    from database.symbol import db_session as symbol_session

    rows = (
        symbol_session.query(SymToken)
        .filter(
            SymToken.exchange == exchange,
            SymToken.name == underlying,
            SymToken.instrumenttype == "FUT",
        )
        .all()
    )

    def parse_expiry(s: str):
        for fmt in ("%d-%b-%y", "%d-%b-%Y", "%d%b%y"):
            try:
                return datetime.strptime((s or "").upper(), fmt)
            except ValueError:
                continue
        return datetime.max

    contracts = sorted(
        ({"symbol": r.symbol, "expiry": r.expiry, "lotsize": r.lotsize} for r in rows),
        key=lambda c: parse_expiry(c["expiry"]),
    )
    return jsonify({"status": "success", "data": contracts})


def _resolve_session_auth():
    """Return (auth_token, broker, api_key, error_response, status_code).

    Resolves the api_key ONLY (auth_token/broker always None) and lets the service
    layer route by mode: api_key alone → sandbox in analyze mode, live broker
    otherwise — the same path the REST API and React dashboard use. We deliberately
    do NOT pass auth_token + broker because:
      - place_order requires `apikey` for validation regardless of auth path, so
        omitting it (live mode) caused "Missing mandatory field(s): apikey";
      - get_positionbook routes by param presence, so passing auth_token + broker
        in analyze mode would read the LIVE book and miss sandbox positions.
    """
    username = session.get("user")
    if not username:
        return None, None, None, {"status": "error", "message": "Not authenticated"}, 401

    api_key = get_api_key_for_tradingview(username)
    if not api_key:
        return (
            None, None, None,
            {"status": "error", "message": "API key required. Generate one at /apikey"},
            401,
        )
    return None, None, api_key, None, None


def _validate_quantity(symbol: str, exchange: str, quantity: int) -> str | None:
    """Validate order quantity against the symbol's lot size server-side.

    Enforces the lot cap (MAX_LOTS) regardless of whether the client supplied
    `lots`, requires the quantity to be a whole number of lots, and rejects
    quantities above the exchange freeze limit. Returns an error string, or None
    if the quantity is valid.
    """
    from database.symbol import SymToken
    from database.symbol import db_session as symbol_session

    rec = (
        symbol_session.query(SymToken)
        .filter(SymToken.symbol == symbol, SymToken.exchange == exchange)
        .first()
    )
    if not rec or not rec.lotsize or rec.lotsize <= 0:
        return f"Unknown symbol or lot size unavailable: {symbol}"

    lotsize = rec.lotsize
    if quantity % lotsize != 0:
        return f"quantity must be a whole number of lots (lot size {lotsize})"
    if quantity > MAX_LOTS * lotsize:
        return f"quantity exceeds the {MAX_LOTS}-lot cap"

    # Exchange single-order freeze limit (best-effort; don't block on lookup error).
    try:
        from database.qty_freeze_db import get_freeze_qty_for_option

        freeze = get_freeze_qty_for_option(symbol, exchange)
        if freeze and freeze > 0 and quantity > freeze:
            return f"quantity exceeds the exchange freeze limit ({freeze})"
    except Exception as e:
        logger.warning(f"Scalping freeze-qty lookup failed for {symbol}: {e}")

    return None


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
    if exchange not in VALID_ORDER_EXCHANGES:
        return jsonify({"status": "error", "message": f"Invalid exchange: {exchange}"}), 400
    if action not in VALID_ACTIONS:
        return jsonify({"status": "error", "message": f"Invalid action: {action}"}), 400
    if product not in _allowed_products(exchange):
        return jsonify({"status": "error", "message": f"Invalid product for {exchange}: {product}"}), 400
    if quantity <= 0:
        return jsonify({"status": "error", "message": "quantity must be positive"}), 400
    if quantity > MAX_ORDER_QUANTITY:
        return jsonify({"status": "error", "message": "quantity exceeds the safety limit"}), 400

    if _is_derivative(exchange):
        # Derivatives trade in lots: enforce the lot cap + lot-size multiple + freeze.
        if lots is not None:
            try:
                lots = int(lots)
            except (TypeError, ValueError):
                return jsonify({"status": "error", "message": "lots must be an integer"}), 400
            if lots < 1 or lots > MAX_LOTS:
                return jsonify(
                    {"status": "error", "message": f"lots must be between 1 and {MAX_LOTS}"}
                ), 400
        qty_err = _validate_quantity(symbol, exchange, quantity)
        if qty_err:
            return jsonify({"status": "error", "message": qty_err}), 400
    # Equity (NSE/BSE) trades in whole shares; quantity bounds above are sufficient.

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

    # Pass the client-supplied LTP (from the live WebSocket feed) through as a prefetched
    # quote. In analyze/sandbox mode the sandbox engine uses it instead of fetching its own
    # per-order quote (which retries with sleeps and stalls placement). Ignored in live mode.
    prefetched_quote = None
    ltp_raw = data.get("ltp")
    if ltp_raw is not None:
        try:
            ltp_val = float(ltp_raw)
            if ltp_val > 0:
                prefetched_quote = {"ltp": ltp_val}
        except (TypeError, ValueError):
            prefetched_quote = None

    success, response, status_code = place_order(
        order_data=order_data,
        api_key=api_key,
        auth_token=auth_token,
        broker=broker,
        prefetched_quote=prefetched_quote,
    )
    # Record this instrument in the scalping list so Close-All / the position book
    # stay scoped to the scalping strategy (broker positions carry no strategy tag).
    if success:
        from database.scalping_db import track_symbol

        track_symbol(symbol, exchange, product, mode=_current_mode())
    return jsonify(response), status_code


def _reducing_exit(symbol, exchange, product, action, quantity, auth_token, broker, api_key):
    """Freeze-safe, whole-lot risk-reducing exit. Returns (success, response, code).

    Bypasses the entry lot cap (a stop-loss / close must flatten any size), requires
    whole-lot quantities for derivatives, and splits into freeze-sized whole-lot
    chunks so no single order exceeds the exchange freeze limit. Used by both
    close_leg (single) and close_all (per scalping position).
    """
    split_chunk = 0  # max whole-lot quantity per order (0 => no chunking)
    if _is_derivative(exchange):
        from database.symbol import SymToken
        from database.symbol import db_session as symbol_session

        rec = (
            symbol_session.query(SymToken)
            .filter(SymToken.symbol == symbol, SymToken.exchange == exchange)
            .first()
        )
        if not rec or not rec.lotsize or rec.lotsize <= 0:
            return False, {"status": "error", "message": f"Unknown symbol: {symbol}"}, 400
        lotsize = rec.lotsize
        if quantity % lotsize != 0:
            return (
                False,
                {"status": "error", "message": f"quantity must be a whole number of lots ({lotsize})"},
                400,
            )

        # Whole-lot freeze cap: floor(freeze / lotsize) * lotsize (NIFTY 1800/65 =>
        # 27 lots = 1755). Unknown freeze (non-NFO default / cache empty) falls back
        # to a conservative MAX_LOTS-lot chunk so exits never exceed the real freeze.
        freeze = 0
        try:
            from database.qty_freeze_db import get_freeze_qty_for_option

            raw_freeze = get_freeze_qty_for_option(symbol, exchange) or 0
            freeze = (raw_freeze // lotsize) * lotsize if raw_freeze else 0
        except Exception as e:
            logger.warning(f"Scalping exit freeze lookup failed for {symbol}: {e}")
        split_chunk = freeze if freeze > 0 else MAX_LOTS * lotsize

    if split_chunk and quantity > split_chunk:
        from services.split_order_service import split_order

        split_data = {
            "strategy": SCALPING_STRATEGY,
            "symbol": symbol,
            "exchange": exchange,
            "action": action,
            "quantity": quantity,
            "splitsize": split_chunk,
            "pricetype": "MARKET",
            "product": product,
        }
        return split_order(
            split_data=split_data, api_key=api_key, auth_token=auth_token, broker=broker
        )

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
    return place_order(
        order_data=order_data, api_key=api_key, auth_token=auth_token, broker=broker
    )


@scalping_bp.route("/scalping/api/close_leg", methods=["POST"])
@check_session_validity
def close_leg():
    """Risk-reducing single-leg exit (used by the trailing-SL engine + per-row Close)."""
    data = request.get_json(silent=True) or {}
    symbol = (data.get("symbol") or "").strip()
    exchange = (data.get("exchange") or "").strip().upper()
    action = (data.get("action") or "").strip().upper()
    product = (data.get("product") or "NRML").strip().upper()

    try:
        quantity = int(data.get("quantity", 0))
    except (TypeError, ValueError):
        quantity = 0

    if not symbol:
        return jsonify({"status": "error", "message": "symbol is required"}), 400
    if exchange not in VALID_ORDER_EXCHANGES:
        return jsonify({"status": "error", "message": f"Invalid exchange: {exchange}"}), 400
    if action not in VALID_ACTIONS:
        return jsonify({"status": "error", "message": f"Invalid action: {action}"}), 400
    if product not in _allowed_products(exchange):
        return jsonify({"status": "error", "message": f"Invalid product for {exchange}: {product}"}), 400
    if quantity <= 0:
        return jsonify({"status": "error", "message": "quantity must be positive"}), 400
    if quantity > MAX_ORDER_QUANTITY:
        return jsonify({"status": "error", "message": "quantity exceeds the safety limit"}), 400

    auth_token, broker, api_key, err, code = _resolve_session_auth()
    if err:
        return jsonify(err), code

    success, response, status_code = _reducing_exit(
        symbol, exchange, product, action, quantity, auth_token, broker, api_key
    )
    return jsonify(response), status_code


@scalping_bp.route("/scalping/api/close_all", methods=["POST"])
@check_session_validity
def close_all():
    """Close only the SCALPING strategy's open positions (F6), each freeze-safe.

    Scoped to instruments the scalping terminal has traded (the scalping list),
    NOT the whole account — and routed through the freeze-safe exit so large
    positions are split, unlike the shared close_position square-off.
    """
    auth_token, broker, api_key, err, code = _resolve_session_auth()
    if err:
        return jsonify(err), code

    from database.scalping_db import get_tracked_symbols

    tracked = get_tracked_symbols(mode=_current_mode())
    if not tracked:
        return jsonify({"status": "success", "message": "No scalping positions to close", "results": []})

    from services.positionbook_service import get_positionbook

    ok, posresp, _pc = get_positionbook(api_key=api_key, auth_token=auth_token, broker=broker)
    if not ok or not isinstance(posresp, dict):
        # Do NOT report success when we can't read positions — they may still be open.
        msg = posresp.get("message") if isinstance(posresp, dict) else "positionbook unavailable"
        return jsonify(
            {"status": "error", "message": f"Could not fetch positions to close: {msg}"}
        ), 502
    positions = posresp.get("data") or []
    posmap = {}
    for p in positions:
        key = (p.get("symbol"), (p.get("exchange") or "").upper(), (p.get("product") or "").upper())
        try:
            posmap[key] = int(float(p.get("quantity") or 0))
        except (TypeError, ValueError):
            posmap[key] = 0

    results = []
    closed = 0
    for t in tracked:
        netqty = posmap.get((t["symbol"], t["exchange"].upper(), t["product"].upper()), 0)
        if netqty == 0:
            continue  # flat — nothing to close (kept in the list for realized P&L)
        exit_action = "SELL" if netqty > 0 else "BUY"
        ok2, resp2, _c = _reducing_exit(
            t["symbol"], t["exchange"], t["product"], exit_action, abs(netqty),
            auth_token, broker, api_key,
        )
        results.append(
            {
                "symbol": t["symbol"],
                "status": "success" if ok2 else "error",
                "message": resp2.get("message") if isinstance(resp2, dict) else None,
            }
        )
        if ok2:
            closed += 1

    return jsonify(
        {"status": "success", "message": f"Closed {closed} scalping position(s)", "results": results}
    )


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


@scalping_bp.route("/scalping/api/tracked", methods=["GET"])
@check_session_validity
def tracked():
    """Return the scalping list (instruments the terminal has traded) for scoping."""
    from database.scalping_db import get_tracked_symbols

    return jsonify({"status": "success", "data": get_tracked_symbols(mode=_current_mode())})


@scalping_bp.route("/scalping/api/tracked", methods=["DELETE"])
@check_session_validity
def reset_tracked():
    """Clear the scalping list (e.g. session/day reset)."""
    from database.scalping_db import clear_tracked_symbols

    return jsonify({"status": "success", "cleared": clear_tracked_symbols(mode=_current_mode())})


@scalping_bp.route("/scalping/api/sl", methods=["GET"])
@check_session_validity
def get_sl_states():
    """Return active stop-loss states to rehydrate the terminal on load."""
    from database.scalping_db import get_active_sl_states

    return jsonify({"status": "success", "data": get_active_sl_states(mode=_current_mode())})


@scalping_bp.route("/scalping/api/sl", methods=["POST"])
@check_session_validity
def upsert_sl():
    """Create or update the stop-loss config for a (symbol, exchange, product) leg."""
    from database.scalping_db import upsert_sl_state

    data = request.get_json(silent=True) or {}
    symbol = (data.get("symbol") or "").strip()
    exchange = (data.get("exchange") or "").strip().upper()
    product = (data.get("product") or "").strip().upper()

    # Product must be valid FOR THIS EXCHANGE (e.g. reject CNC on NFO/BFO/MCX/CDS) so
    # we never persist an SL leg the freeze-safe exit can't actually place.
    if not symbol or exchange not in VALID_LEG_EXCHANGES or product not in _allowed_products(exchange):
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
        "mode": _current_mode(),  # segregate sandbox vs live SLs
        "side": side,
        "quantity": quantity,
    }
    for field in ("entry_price", "initial_sl", "trailing_step", "highest_price",
                  "lowest_price", "current_sl", "target"):
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
    _notify_risk_monitor()
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

    deleted = delete_sl_state(symbol, exchange, product, mode=_current_mode())
    _notify_risk_monitor()
    return jsonify({"status": "success", "deleted": deleted})
