"""
Backend API for the standalone chart test page (DEV / TESTING ONLY).

The page itself is a React route (`/chart/test`, served by react_app.py / the
React SPA). This blueprint only exposes the one piece of data the React page
needs that no existing endpoint provides: 1-minute candles for the most recent
trading day.

The React page reuses existing infrastructure for everything else:
  - symbol search        -> /search/api/search
  - websocket streaming  -> useMarketData() hook (shared MarketDataManager),
                            which authenticates via /api/websocket/config and
                            /api/websocket/apikey.

The page is intentionally NOT linked from any menu, tools tile or navbar. It is
reachable only by typing the URL: http://127.0.0.1:5000/chart/test
Only the 1-minute interval is supported.
"""

import re
from datetime import datetime, timedelta

import pytz
from flask import Blueprint, jsonify, request, session

from database.auth_db import get_api_key_for_tradingview
from services.history_service import get_history
from utils.logging import get_logger
from utils.session import check_session_validity

logger = get_logger(__name__)

chart_test_bp = Blueprint("chart_test_bp", __name__)

IST = pytz.timezone("Asia/Kolkata")
# Seconds to add to a UTC epoch so that, when lightweight-charts renders the
# value as UTC, the displayed wall-clock equals IST. 5h30m = 19800s = a whole
# number of minutes, so minute-bucketing is identical before/after the shift.
# The React page applies the same offset to live ticks so history and live bars
# line up on the time axis.
IST_OFFSET_SECONDS = 19800

# Supported intervals (OpenAlgo format) -> trading days of history to load.
INTERVAL_TRADING_DAYS = {"1m": 1, "5m": 3, "15m": 9}


@chart_test_bp.route("/chart/test/api/history", methods=["GET"])
@check_session_validity
def chart_test_history():
    """Return candles for the most recent N trading days at the given interval.

    ``interval`` is an OpenAlgo interval (1m/5m/15m). The lookback scales with
    it: 1m -> 1 trading day, 5m -> 3, 15m -> 9. A generous calendar window is
    fetched and the latest N IST dates with data are kept, which transparently
    skips weekends/holidays without a market-calendar lookup. An optional
    ``date=YYYY-MM-DD`` restricts the fetch to a single day (used by the page's
    periodic reconcile).
    """
    username = session.get("user")
    if not username:
        return jsonify({"status": "error", "message": "Session not found"}), 401

    api_key = get_api_key_for_tradingview(username)
    if not api_key:
        return jsonify(
            {"status": "error", "message": "No API key found. Generate one at /apikey first."}
        ), 404

    symbol = (request.args.get("symbol", "") or "").strip().upper()[:50]
    exchange = (request.args.get("exchange", "") or "").strip().upper()[:20]
    if not symbol or not exchange:
        return jsonify({"status": "error", "message": "symbol and exchange are required"}), 400

    interval = (request.args.get("interval", "1m") or "1m").strip()
    if interval not in INTERVAL_TRADING_DAYS:
        interval = "1m"

    # Optional ?date=YYYY-MM-DD restricts the fetch to a single trading day. The
    # React page passes the date it learned on first load when it reconciles, so
    # the periodic refresh pulls one day instead of the full lookback window.
    date_param = (request.args.get("date", "") or "").strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}$", date_param):
        start_date = date_param
        end_date = date_param
        keep_days = 1
    else:
        keep_days = INTERVAL_TRADING_DAYS[interval]
        today = datetime.now(IST).date()
        # Fetch a generous calendar window, then keep the latest `keep_days`
        # trading dates (covers weekends/holidays without a calendar lookup).
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
        logger.exception(f"chart/test history error for {symbol}.{exchange}: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

    if not success:
        message = response.get("message") if isinstance(response, dict) else str(response)
        return jsonify(
            {"status": "error", "message": message or "History fetch failed"}
        ), status_code

    rows = response.get("data", []) if isinstance(response, dict) else []
    if not rows:
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

    # Group rows by IST date so we can keep the latest `keep_days` trading dates.
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
