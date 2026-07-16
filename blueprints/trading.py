"""
/trading — line-based chart trading powered by openalgo-charts.

A self-contained page (no React build required): a canvas charting engine with
on-chart order lines — drag to modify, ✕ to cancel, right-click to place —
plus live WebSocket candles and the real-time order-update stream.

The page is session-gated and bootstraps itself entirely from existing
endpoints, so this blueprint only serves the page and its static assets:

  - API key + WS URL     -> /api/websocket/apikey, /api/websocket/config
  - symbol search        -> POST /api/v1/search      (lotsize/tick_size/freeze_qty)
  - symbol metadata      -> POST /api/v1/symbol
  - intervals            -> POST /api/v1/intervals   (broker-supported)
  - candles              -> POST /api/v1/history
  - orders               -> POST /api/v1/placeorder / modifyorder / cancelorder
  - books                -> POST /api/v1/orderbook / positionbook
  - square-off           -> POST /api/v1/placesmartorder (position_size 0)
  - live LTP + orders    -> WebSocket proxy (LTP mode + subscribe_orders)

Works in both analyzer (sandbox) and live modes — the page surfaces the mode
returned by the API and asks for confirmation before live orders.

The vendored openalgo-charts bundles in trading_static/ are the published
npm build (see https://github.com/marketcalls/openalgo-charts).
"""

from pathlib import Path

from flask import Blueprint, jsonify, send_from_directory, session

from utils.session import check_session_validity

STATIC_DIR = Path(__file__).parent / "trading_static"

trading_bp = Blueprint("trading_bp", __name__, url_prefix="/trading")


@trading_bp.route("/", strict_slashes=False)
@check_session_validity
def trading_page():
    """Serve the chart-trading page (session required)."""
    return send_from_directory(STATIC_DIR, "index.html")


@trading_bp.route("/api/me")
@check_session_validity
def trading_me():
    """Logged-in user's name for the header avatar (matches the app header)."""
    return jsonify({"status": "success", "user": session.get("user", "")})


@trading_bp.route("/static/<path:filename>")
def trading_static(filename: str):
    """Serve the page's JS/assets (same-origin, so the strict CSP is satisfied)."""
    return send_from_directory(STATIC_DIR, filename)
