"""
React Frontend Serving Blueprint
Serves the pre-built React app for migrated routes.
"""

from pathlib import Path

from flask import Blueprint, send_file, send_from_directory

react_bp = Blueprint("react", __name__)

# Path to the pre-built React frontend
FRONTEND_DIST = Path(__file__).parent.parent / "frontend" / "dist"


def is_react_frontend_available():
    """Check if the React frontend build exists."""
    index_html = FRONTEND_DIST / "index.html"
    return FRONTEND_DIST.exists() and index_html.exists()


def serve_react_app():
    """Serve the React app's index.html."""
    if not is_react_frontend_available():
        return (
            """
        <html>
        <head><title>OpenAlgo - Frontend Not Available</title></head>
        <body style="font-family: system-ui; padding: 40px; max-width: 600px; margin: 0 auto;">
            <h1>Frontend Not Built</h1>
            <p>The React frontend is not available. To build it:</p>
            <pre style="background: #f4f4f4; padding: 16px; border-radius: 8px;">
cd frontend
npm install
npm run build</pre>
            <p>Or use the pre-built version from the repository.</p>
        </body>
        </html>
        """,
            503,
        )

    index_path = FRONTEND_DIST / "index.html"
    return send_file(index_path, mimetype="text/html")


# ============================================================
# Phase 2 Migrated Routes - These are served by React
# ============================================================


# Index/Home route
@react_bp.route("/")
def react_index():
    return serve_react_app()


# Login route
@react_bp.route("/login")
def react_login():
    return serve_react_app()


# Setup route (initial admin setup)
@react_bp.route("/setup")
def react_setup():
    return serve_react_app()


# Password reset
@react_bp.route("/reset-password")
def react_reset_password():
    return serve_react_app()


# Download page
@react_bp.route("/download")
def react_download():
    return serve_react_app()


# FAQ page
@react_bp.route("/faq")
def react_faq():
    return serve_react_app()


# Error page
@react_bp.route("/error")
def react_error():
    return serve_react_app()


# Rate limited page
@react_bp.route("/rate-limited")
def react_rate_limited():
    return serve_react_app()


# Broker selection - serve React at /broker (alias for /auth/broker)
@react_bp.route("/broker")
def react_broker():
    return serve_react_app()


# Broker TOTP routes - serve React for broker authentication forms
@react_bp.route("/broker/<broker>/totp")
def react_broker_totp(broker):
    return serve_react_app()


# Dashboard
@react_bp.route("/dashboard")
def react_dashboard():
    return serve_react_app()


# Trading pages
@react_bp.route("/positions")
def react_positions():
    return serve_react_app()


@react_bp.route("/orderbook")
def react_orderbook():
    return serve_react_app()


@react_bp.route("/tradebook")
def react_tradebook():
    return serve_react_app()


@react_bp.route("/holdings")
def react_holdings():
    return serve_react_app()


# Search pages
@react_bp.route("/search/token")
def react_search_token():
    return serve_react_app()


@react_bp.route("/search")
def react_search():
    return serve_react_app()


# API Key management - handled by api_key_bp (supports both JSON and React)


# Playground
@react_bp.route("/playground")
def react_playground():
    return serve_react_app()


# ============================================================
# Phase 4 Routes - Charts, WebSocket & Sandbox
# ============================================================


# Trading Platforms overview
@react_bp.route("/platforms")
def react_platforms():
    return serve_react_app()


# TradingView webhook configuration
@react_bp.route("/tradingview")
def react_tradingview():
    return serve_react_app()


# GoCharting webhook configuration
@react_bp.route("/gocharting")
def react_gocharting():
    return serve_react_app()


# P&L Tracker with real-time chart
@react_bp.route("/pnl-tracker")
def react_pnltracker():
    return serve_react_app()


# Tools overview (Option Chain, IV Chart, etc.)
@react_bp.route("/tools")
def react_tools():
    return serve_react_app()


# IV Chart for options implied volatility
@react_bp.route("/ivchart")
def react_ivchart():
    return serve_react_app()


# OI Tracker for open interest analysis
@react_bp.route("/oitracker")
def react_oitracker():
    return serve_react_app()


# Max Pain analysis
@react_bp.route("/maxpain")
def react_maxpain():
    return serve_react_app()


# Straddle Chart - Dynamic ATM Straddle analysis
@react_bp.route("/straddle")
def react_straddle():
    return serve_react_app()


# Vol Surface - 3D Implied Volatility surface
@react_bp.route("/volsurface")
def react_volsurface():
    return serve_react_app()


# GEX Dashboard - Gamma Exposure analysis
@react_bp.route("/gex")
def react_gex():
    return serve_react_app()


# IV Smile - Implied Volatility smile curve
@react_bp.route("/ivsmile")
def react_ivsmile():
    return serve_react_app()


# OI Profile - Open Interest Profile with futures candles
@react_bp.route("/oiprofile")
def react_oiprofile():
    return serve_react_app()


# WebSocket market data test page
@react_bp.route("/websocket/test")
def react_websocket_test():
    return serve_react_app()


# WebSocket depth test pages (broker dependent depth levels)
@react_bp.route("/websocket/test/20")
def react_websocket_test_20():
    return serve_react_app()


@react_bp.route("/websocket/test/30")
def react_websocket_test_30():
    return serve_react_app()


@react_bp.route("/websocket/test/50")
def react_websocket_test_50():
    return serve_react_app()


# Sandbox configuration
@react_bp.route("/sandbox")
def react_sandbox():
    return serve_react_app()


# Sandbox P&L history
@react_bp.route("/sandbox/mypnl")
def react_sandbox_mypnl():
    return serve_react_app()


# API Request Analyzer
@react_bp.route("/analyzer")
def react_analyzer():
    return serve_react_app()


# ============================================================
# Phase 6 Routes - Strategy & Automation
# ============================================================


# Webhook Strategies
# Note: Using strict_slashes=False to handle both /strategy and /strategy/
@react_bp.route("/strategy", strict_slashes=False)
def react_strategy_index():
    return serve_react_app()


@react_bp.route("/strategy/new", strict_slashes=False)
def react_strategy_new():
    return serve_react_app()


@react_bp.route("/strategy/<int:strategy_id>", strict_slashes=False)
def react_strategy_view(strategy_id):
    return serve_react_app()


@react_bp.route("/strategy/<int:strategy_id>/configure", strict_slashes=False)
def react_strategy_configure(strategy_id):
    return serve_react_app()


# Python Strategies
# Note: Using strict_slashes=False to handle both /python and /python/
@react_bp.route("/python", strict_slashes=False)
def react_python_index():
    return serve_react_app()


@react_bp.route("/python/new", strict_slashes=False)
def react_python_new():
    return serve_react_app()


@react_bp.route("/python/<strategy_id>/edit", strict_slashes=False)
def react_python_edit(strategy_id):
    return serve_react_app()


@react_bp.route("/python/<strategy_id>/logs", strict_slashes=False)
def react_python_logs(strategy_id):
    return serve_react_app()


# Chartink Strategies
# Note: Using strict_slashes=False to handle both /chartink and /chartink/
@react_bp.route("/chartink", strict_slashes=False)
def react_chartink_index():
    return serve_react_app()


@react_bp.route("/chartink/new", strict_slashes=False)
def react_chartink_new():
    return serve_react_app()


@react_bp.route("/chartink/<int:strategy_id>", strict_slashes=False)
def react_chartink_view(strategy_id):
    return serve_react_app()


@react_bp.route("/chartink/<int:strategy_id>/configure", strict_slashes=False)
def react_chartink_configure(strategy_id):
    return serve_react_app()


# ============================================================
# Phase 7 Routes - Admin & Settings
# ============================================================


# Admin Dashboard
@react_bp.route("/admin", strict_slashes=False)
def react_admin_index():
    return serve_react_app()


# Admin - Freeze Quantities
@react_bp.route("/admin/freeze", strict_slashes=False)
def react_admin_freeze():
    return serve_react_app()


# Admin - Market Holidays
@react_bp.route("/admin/holidays", strict_slashes=False)
def react_admin_holidays():
    return serve_react_app()


# Admin - Market Timings
@react_bp.route("/admin/timings", strict_slashes=False)
def react_admin_timings():
    return serve_react_app()


# Telegram - Dashboard
@react_bp.route("/telegram", strict_slashes=False)
def react_telegram_index():
    return serve_react_app()


# Telegram - Configuration
@react_bp.route("/telegram/config", strict_slashes=False)
def react_telegram_config():
    return serve_react_app()


# Telegram - Users
@react_bp.route("/telegram/users", strict_slashes=False)
def react_telegram_users():
    return serve_react_app()


# Telegram - Analytics
@react_bp.route("/telegram/analytics", strict_slashes=False)
def react_telegram_analytics():
    return serve_react_app()


# ============================================================
# Phase 7 Routes - Monitoring Dashboards
# ============================================================


# Security Dashboard
@react_bp.route("/security", strict_slashes=False)
def react_security():
    return serve_react_app()


# Traffic Dashboard
@react_bp.route("/traffic", strict_slashes=False)
def react_traffic():
    return serve_react_app()


# Latency Dashboard
@react_bp.route("/latency", strict_slashes=False)
def react_latency():
    return serve_react_app()


# ============================================================
# Phase 7 Routes - Settings & Action Center
# ============================================================


# Logs Index
@react_bp.route("/logs", strict_slashes=False)
def react_logs():
    return serve_react_app()


# Live Logs
@react_bp.route("/logs/live", strict_slashes=False)
def react_logs_live():
    return serve_react_app()


# Sandbox Logs (Analyzer)
@react_bp.route("/logs/sandbox", strict_slashes=False)
def react_logs_sandbox():
    return serve_react_app()


# Security Logs
@react_bp.route("/logs/security", strict_slashes=False)
def react_logs_security():
    return serve_react_app()


# Traffic Monitor
@react_bp.route("/logs/traffic", strict_slashes=False)
def react_logs_traffic():
    return serve_react_app()


# Latency Monitor
@react_bp.route("/logs/latency", strict_slashes=False)
def react_logs_latency():
    return serve_react_app()


# Profile Settings
@react_bp.route("/profile", strict_slashes=False)
def react_profile():
    return serve_react_app()


# Action Center (Semi-automated trading)
@react_bp.route("/action-center", strict_slashes=False)
def react_action_center():
    return serve_react_app()


# Historify (Historical Data Management)
@react_bp.route("/historify", strict_slashes=False)
def react_historify():
    return serve_react_app()


# ============================================================
# Flow Routes - Visual Workflow Automation
# ============================================================


# Flow Dashboard (Workflow List)
@react_bp.route("/flow", strict_slashes=False)
def react_flow_index():
    return serve_react_app()


# Flow Editor (Visual Workflow Builder)
@react_bp.route("/flow/editor/<int:workflow_id>", strict_slashes=False)
def react_flow_editor(workflow_id):
    return serve_react_app()


# ============================================================
# Static Assets - Always served for React app
# ============================================================


@react_bp.route("/assets/<path:filename>")
def serve_assets(filename):
    """Serve static assets with long cache headers."""
    assets_dir = FRONTEND_DIST / "assets"
    if not assets_dir.exists():
        return "Assets not found", 404

    response = send_from_directory(assets_dir, filename)
    # Cache assets for 1 year (they have content hashes in filenames)
    response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return response


@react_bp.route("/favicon.ico")
def serve_favicon():
    """Serve favicon."""
    if not is_react_frontend_available():
        return "Not found", 404
    return send_from_directory(FRONTEND_DIST, "favicon.ico")


@react_bp.route("/logo.png")
def serve_logo():
    """Serve logo."""
    if not is_react_frontend_available():
        return "Not found", 404
    return send_from_directory(FRONTEND_DIST, "logo.png")


@react_bp.route("/apple-touch-icon.png")
def serve_apple_touch_icon():
    """Serve Apple touch icon."""
    if not is_react_frontend_available():
        return "Not found", 404
    return send_from_directory(FRONTEND_DIST, "apple-touch-icon.png")


@react_bp.route("/images/<path:filename>")
def serve_images(filename):
    """Serve images from React dist."""
    images_dir = FRONTEND_DIST / "images"
    if not images_dir.exists():
        return "Images not found", 404
    return send_from_directory(images_dir, filename)


@react_bp.route("/sounds/<path:filename>")
def serve_sounds(filename):
    """Serve sounds from React dist."""
    sounds_dir = FRONTEND_DIST / "sounds"
    if not sounds_dir.exists():
        return "Sounds not found", 404
    return send_from_directory(sounds_dir, filename)


@react_bp.route("/docs/<path:filename>")
def serve_docs(filename):
    """Serve docs from React dist."""
    docs_dir = FRONTEND_DIST / "docs"
    if not docs_dir.exists():
        return "Docs not found", 404
    return send_from_directory(docs_dir, filename)
