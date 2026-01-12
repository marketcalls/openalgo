"""
React Frontend Serving Blueprint
Serves the pre-built React app for migrated routes.
"""

from pathlib import Path
from flask import Blueprint, send_file, send_from_directory

react_bp = Blueprint('react', __name__)

# Path to the pre-built React frontend
FRONTEND_DIST = Path(__file__).parent.parent / 'frontend' / 'dist'


def is_react_frontend_available():
    """Check if the React frontend build exists."""
    index_html = FRONTEND_DIST / 'index.html'
    return FRONTEND_DIST.exists() and index_html.exists()


def serve_react_app():
    """Serve the React app's index.html."""
    if not is_react_frontend_available():
        return """
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
        """, 503

    index_path = FRONTEND_DIST / 'index.html'
    return send_file(index_path, mimetype='text/html')


# ============================================================
# Phase 2 Migrated Routes - These are served by React
# ============================================================

# Index/Home route
@react_bp.route('/')
def react_index():
    return serve_react_app()


# Login route
@react_bp.route('/login')
def react_login():
    return serve_react_app()


# Setup route (initial admin setup)
@react_bp.route('/setup')
def react_setup():
    return serve_react_app()


# Broker selection - serve React at /broker (alias for /auth/broker)
@react_bp.route('/broker')
def react_broker():
    return serve_react_app()


# Dashboard
@react_bp.route('/dashboard')
def react_dashboard():
    return serve_react_app()


# Trading pages
@react_bp.route('/positions')
def react_positions():
    return serve_react_app()


@react_bp.route('/orderbook')
def react_orderbook():
    return serve_react_app()


@react_bp.route('/tradebook')
def react_tradebook():
    return serve_react_app()


@react_bp.route('/holdings')
def react_holdings():
    return serve_react_app()


# Search pages
@react_bp.route('/search/token')
def react_search_token():
    return serve_react_app()


@react_bp.route('/search')
def react_search():
    return serve_react_app()


# API Key management
@react_bp.route('/apikey')
def react_apikey():
    return serve_react_app()


# Playground
@react_bp.route('/playground')
def react_playground():
    return serve_react_app()


# ============================================================
# Phase 4 Routes - Charts, WebSocket & Sandbox
# ============================================================

# Trading Platforms overview
@react_bp.route('/platforms')
def react_platforms():
    return serve_react_app()


# TradingView webhook configuration
@react_bp.route('/tradingview')
def react_tradingview():
    return serve_react_app()


# GoCharting webhook configuration
@react_bp.route('/gocharting')
def react_gocharting():
    return serve_react_app()


# P&L Tracker with real-time chart
@react_bp.route('/pnl-tracker')
def react_pnltracker():
    return serve_react_app()


# WebSocket market data test page
@react_bp.route('/websocket/test')
def react_websocket_test():
    return serve_react_app()


# Sandbox configuration
@react_bp.route('/sandbox')
def react_sandbox():
    return serve_react_app()


# Sandbox P&L history
@react_bp.route('/sandbox/mypnl')
def react_sandbox_mypnl():
    return serve_react_app()


# API Request Analyzer
@react_bp.route('/analyzer')
def react_analyzer():
    return serve_react_app()


# ============================================================
# Static Assets - Always served for React app
# ============================================================

@react_bp.route('/assets/<path:filename>')
def serve_assets(filename):
    """Serve static assets with long cache headers."""
    assets_dir = FRONTEND_DIST / 'assets'
    if not assets_dir.exists():
        return "Assets not found", 404

    response = send_from_directory(assets_dir, filename)
    # Cache assets for 1 year (they have content hashes in filenames)
    response.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
    return response


@react_bp.route('/favicon.ico')
def serve_favicon():
    """Serve favicon."""
    if not is_react_frontend_available():
        return "Not found", 404
    return send_from_directory(FRONTEND_DIST, 'favicon.ico')


@react_bp.route('/logo.png')
def serve_logo():
    """Serve logo."""
    if not is_react_frontend_available():
        return "Not found", 404
    return send_from_directory(FRONTEND_DIST, 'logo.png')
