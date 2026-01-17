# Load and check environment variables before anything else
from utils.env_check import load_and_check_env_variables  # Import the environment check function
load_and_check_env_variables()

import re
import sys

# Initialize logging EARLY to suppress verbose startup logs
from utils.logging import get_logger, log_startup_banner, highlight_url  # Import centralized logging

from flask import Flask, session
from flask_wtf.csrf import CSRFProtect  # Import CSRF protection
from extensions import socketio  # Import SocketIO
from limiter import limiter  # Import the Limiter instance
from cors import cors        # Import the CORS instance
from csp import apply_csp_middleware  # Import the CSP middleware
from utils.version import get_version  # Import version management
from utils.latency_monitor import init_latency_monitoring  # Import latency monitoring
from utils.traffic_logger import init_traffic_logging  # Import traffic logging
from utils.security_middleware import init_security_middleware  # Import security middleware
from utils.socketio_error_handler import init_socketio_error_handling  # Import Socket.IO error handler
# Import WebSocket proxy server - using relative import to avoid @ symbol issues
from websocket_proxy.app_integration import start_websocket_proxy

from blueprints.auth import auth_bp
from blueprints.dashboard import dashboard_bp
from blueprints.orders import orders_bp
from blueprints.search import search_bp
from blueprints.apikey import api_key_bp
from blueprints.log import log_bp
from blueprints.tv_json import tv_json_bp
from blueprints.gc_json import gc_json_bp
from blueprints.platforms import platforms_bp
from blueprints.brlogin import brlogin_bp
from blueprints.core import core_bp
from blueprints.analyzer import analyzer_bp  # Import the analyzer blueprint
from blueprints.settings import settings_bp  # Import the settings blueprint
from blueprints.chartink import chartink_bp  # Import the chartink blueprint
from blueprints.traffic import traffic_bp  # Import the traffic blueprint
from blueprints.latency import latency_bp  # Import the latency blueprint
from blueprints.strategy import strategy_bp  # Import the strategy blueprint
from blueprints.master_contract_status import master_contract_status_bp  # Import the master contract status blueprint
from blueprints.websocket_example import websocket_bp  # Import the websocket example blueprint
from blueprints.pnltracker import pnltracker_bp  # Import the pnl tracker blueprint
from blueprints.python_strategy import python_strategy_bp  # Import the python strategy blueprint
from blueprints.telegram import telegram_bp  # Import the telegram blueprint
from blueprints.security import security_bp  # Import the security blueprint
from blueprints.sandbox import sandbox_bp  # Import the sandbox blueprint
from blueprints.logging import logging_bp  # Import the logging blueprint
from blueprints.playground import playground_bp  # Import the API playground blueprint
from blueprints.admin import admin_bp  # Import the admin blueprint
from blueprints.react_app import react_bp, is_react_frontend_available, serve_react_app  # Import React frontend blueprint
from blueprints.historify import historify_bp  # Import the historify blueprint
from services.telegram_bot_service import telegram_bot_service
from database.telegram_db import get_bot_config

from restx_api import api_v1_bp, api

from database.auth_db import init_db as ensure_auth_tables_exists
from database.user_db import init_db as ensure_user_tables_exists
from database.symbol import init_db as ensure_master_contract_tables_exists
from database.apilog_db import init_db as ensure_api_log_tables_exists
from database.analyzer_db import init_db as ensure_analyzer_tables_exists
from database.settings_db import init_db as ensure_settings_tables_exists
from database.chartink_db import init_db as ensure_chartink_tables_exists
from database.traffic_db import init_logs_db as ensure_traffic_logs_exists
from database.latency_db import init_latency_db as ensure_latency_tables_exists
from database.strategy_db import init_db as ensure_strategy_tables_exists
from database.sandbox_db import init_db as ensure_sandbox_tables_exists
from database.action_center_db import init_db as ensure_action_center_tables_exists
from database.historify_db import init_database as ensure_historify_tables_exists

from utils.plugin_loader import load_broker_auth_functions

import os

# Initialize logger
logger = get_logger(__name__)

def create_app():
    # Initialize Flask application
    app = Flask(__name__)

    # Initialize SocketIO
    socketio.init_app(app)  # Link SocketIO to the Flask app

    # Initialize CSRF protection
    csrf = CSRFProtect(app)
    
    # Store csrf instance in app config for use in other modules
    app.csrf = csrf

    # Initialize Flask-Limiter with the app object
    limiter.init_app(app)

    # Initialize Flask-CORS with the app object using configuration from environment variables
    from cors import get_cors_config
    cors.init_app(app, **get_cors_config())

    # Apply Content Security Policy middleware
    apply_csp_middleware(app)
    
    # Initialize Socket.IO error handling
    init_socketio_error_handling(socketio)

    # Register custom Jinja2 filters
    from utils.number_formatter import format_indian_number
    app.jinja_env.filters['indian_number'] = format_indian_number

    # Environment variables
    app.secret_key = os.getenv('APP_KEY')
    app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
    
    # Dynamic cookie security configuration based on HOST_SERVER
    HOST_SERVER = os.getenv('HOST_SERVER', 'http://127.0.0.1:5000')
    USE_HTTPS = HOST_SERVER.startswith('https://')
    
    # Configure session cookie security
    session_cookie_name = os.getenv('SESSION_COOKIE_NAME', 'session')
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',
        SESSION_COOKIE_SECURE=USE_HTTPS,
        SESSION_COOKIE_NAME=session_cookie_name
        # PERMANENT_SESSION_LIFETIME is dynamically set at login to expire at 3:30 AM IST
    )
    
    # Add cookie prefix for HTTPS environments
    if USE_HTTPS:
        app.config['SESSION_COOKIE_NAME'] = f'__Secure-{session_cookie_name}'
    
    # CSRF configuration from environment variables
    csrf_enabled = os.getenv('CSRF_ENABLED', 'TRUE').upper() == 'TRUE'
    app.config['WTF_CSRF_ENABLED'] = csrf_enabled
    
    # Configure CSRF cookie security to match session cookie
    csrf_cookie_name = os.getenv('CSRF_COOKIE_NAME', 'csrf_token')
    app.config.update(
        WTF_CSRF_COOKIE_HTTPONLY=True,
        WTF_CSRF_COOKIE_SAMESITE='Lax',
        WTF_CSRF_COOKIE_SECURE=USE_HTTPS,
        WTF_CSRF_COOKIE_NAME=csrf_cookie_name
    )
    
    # Add cookie prefix for CSRF token in HTTPS environments
    if USE_HTTPS:
        app.config['WTF_CSRF_COOKIE_NAME'] = f'__Secure-{csrf_cookie_name}'
    
    # Parse CSRF time limit from environment
    csrf_time_limit = os.getenv('CSRF_TIME_LIMIT', '').strip()
    if csrf_time_limit:
        try:
            app.config['WTF_CSRF_TIME_LIMIT'] = int(csrf_time_limit)
        except ValueError:
            app.config['WTF_CSRF_TIME_LIMIT'] = None  # Default to no limit if invalid
    else:
        app.config['WTF_CSRF_TIME_LIMIT'] = None  # No time limit if empty

    # Register RESTx API blueprint first
    # Register React frontend blueprint FIRST for migrated routes
    # Register React frontend routes
    if is_react_frontend_available():
        app.register_blueprint(react_bp)
        logger.debug("React frontend enabled (frontend/dist found)")
    else:
        logger.warning("React frontend not available - run 'npm run build' in frontend/")

    app.register_blueprint(api_v1_bp)
    
    # Exempt API endpoints from CSRF protection (they use API key authentication)
    csrf.exempt(api_v1_bp)

    # Initialize security middleware before traffic logging
    init_security_middleware(app)

    # Initialize traffic logging middleware after security
    init_traffic_logging(app)

    # Register other blueprints
    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(orders_bp)
    app.register_blueprint(search_bp)
    app.register_blueprint(api_key_bp)
    app.register_blueprint(log_bp)
    app.register_blueprint(tv_json_bp)
    app.register_blueprint(gc_json_bp)
    app.register_blueprint(platforms_bp)
    app.register_blueprint(brlogin_bp)
    app.register_blueprint(core_bp)
    app.register_blueprint(analyzer_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(chartink_bp)
    app.register_blueprint(traffic_bp)
    app.register_blueprint(latency_bp)
    app.register_blueprint(strategy_bp)
    app.register_blueprint(master_contract_status_bp)
    app.register_blueprint(websocket_bp)  # Register WebSocket example blueprint
    app.register_blueprint(pnltracker_bp)  # Register PnL tracker blueprint
    app.register_blueprint(python_strategy_bp)  # Register Python strategy blueprint
    app.register_blueprint(telegram_bp)  # Register Telegram blueprint
    app.register_blueprint(security_bp)  # Register Security blueprint
    app.register_blueprint(sandbox_bp)  # Register Sandbox blueprint
    app.register_blueprint(playground_bp)  # Register API playground blueprint
    app.register_blueprint(logging_bp)  # Register Logging blueprint
    app.register_blueprint(admin_bp)  # Register Admin blueprint
    app.register_blueprint(historify_bp)  # Register Historify blueprint


    # Exempt webhook endpoints from CSRF protection after app initialization
    with app.app_context():
        # Exempt webhook endpoints from CSRF protection
        csrf.exempt(app.view_functions['chartink_bp.webhook'])
        csrf.exempt(app.view_functions['strategy_bp.webhook'])
        
        # Exempt broker callback endpoints from CSRF protection (OAuth callbacks from external providers)
        csrf.exempt(app.view_functions['brlogin.broker_callback'])

        # Exempt logout endpoint from CSRF protection (safe - only destroys session)
        csrf.exempt(app.view_functions['auth.logout'])

        # Initialize latency monitoring (after registering API blueprint)
        init_latency_monitoring(app)

        # Auto-start Telegram bot if it was active (non-blocking)
        try:
            import sys
            bot_config = get_bot_config()
            if bot_config.get('is_active') and bot_config.get('bot_token'):
                logger.debug("Auto-starting Telegram bot (background)...")

                # Check if we're in eventlet environment
                if 'eventlet' in sys.modules:
                    logger.debug("Eventlet detected during auto-start - using synchronous initialization")
                    # Use synchronous initialization for eventlet
                    success, message = telegram_bot_service.initialize_bot_sync(token=bot_config['bot_token'])
                    if success:
                        success, message = telegram_bot_service.start_bot()
                        if success:
                            logger.debug(f"Telegram bot auto-started successfully: {message}")
                        else:
                            logger.error(f"Failed to auto-start Telegram bot: {message}")
                    else:
                        logger.error(f"Failed to initialize Telegram bot: {message}")
                else:
                    # Initialize and start bot in background thread (non-blocking)
                    import asyncio
                    import threading

                    def init_and_start_bot():
                        try:
                            loop = asyncio.new_event_loop()
                            asyncio.set_event_loop(loop)
                            try:
                                success, message = loop.run_until_complete(
                                    telegram_bot_service.initialize_bot(token=bot_config['bot_token'])
                                )
                            finally:
                                loop.close()

                            if success:
                                success, message = telegram_bot_service.start_bot()
                                if success:
                                    logger.debug(f"Telegram bot auto-started successfully: {message}")
                                else:
                                    logger.error(f"Failed to auto-start Telegram bot: {message}")
                            else:
                                logger.error(f"Failed to initialize Telegram bot: {message}")
                        except Exception as e:
                            logger.error(f"Error in Telegram bot background startup: {e}")

                    # Start in background - don't wait for completion
                    thread = threading.Thread(target=init_and_start_bot, daemon=True)
                    thread.start()
                    logger.debug("Telegram bot initialization started in background")

        except Exception as e:
            logger.error(f"Error auto-starting Telegram bot: {str(e)}")

    @app.before_request
    def check_session_expiry():
        """Check session validity before each request"""
        from flask import request
        from utils.session import is_session_valid, revoke_user_tokens
        
        # Skip session check for static files, API endpoints, and public routes
        if (request.path.startswith('/static/') or
            request.path.startswith('/api/') or
            request.path in ['/', '/auth/login', '/auth/reset-password', '/auth/csrf-token', '/auth/broker-config', '/setup', '/download', '/faq'] or
            request.path.startswith('/auth/broker/') or  # OAuth callbacks
            request.path.startswith('/_reload-ws')):  # WebSocket reload endpoint
            return
        
        # Check if user is logged in and session is expired
        if session.get('logged_in') and not is_session_valid():
            logger.info(f"Session expired for user: {session.get('user')} - revoking tokens")
            revoke_user_tokens()
            session.clear()
            # Don't redirect here, let individual routes handle it
    
    @app.errorhandler(400)
    def csrf_error(error):
        """Custom handler for CSRF errors (400 Bad Request)"""
        from flask import request, jsonify, flash, redirect, url_for
        error_description = str(error)

        logger.warning(f"CSRF Error on {request.path}: {error_description}")

        # Check if it's a CSRF error
        if 'CSRF' in error_description or 'csrf' in error_description.lower():
            if request.is_json or request.path.startswith('/api'):
                return jsonify({
                    'error': 'CSRF validation failed',
                    'message': 'Security token expired or invalid. Please refresh the page and try again.'
                }), 400
            else:
                flash('Security token expired. Please try again.', 'error')
                return redirect(request.referrer or url_for('auth.login'))

        # For other 400 errors
        return str(error), 400

    @app.errorhandler(404)
    def not_found_error(error):
        from flask import request
        from database.traffic_db import Error404Tracker
        from utils.ip_helper import get_real_ip

        # Track the 404 error
        client_ip = get_real_ip()
        path = request.path

        # Track 404 error for security monitoring
        Error404Tracker.track_404(client_ip, path)

        # Serve React app (React Router handles 404)
        return serve_react_app()

    @app.errorhandler(500)
    def internal_server_error(e):
        """Custom handler for 500 Internal Server Error"""
        from flask import redirect

        # Log the error
        logger.error(f"Server Error: {e}")

        # Redirect to React error page
        return redirect('/error')

    @app.errorhandler(429)
    def rate_limit_exceeded(e):
        """Custom handler for 429 Too Many Requests"""
        from flask import redirect, request

        # Log rate limit hit
        logger.warning(f"Rate limit exceeded for {request.remote_addr}: {request.path}")

        # For API requests, return JSON response
        if request.path.startswith('/api/'):
            return {
                'status': 'error',
                'message': 'Rate limit exceeded. Please slow down your requests.',
                'retry_after': 60
            }, 429

        # For web requests, redirect to React rate-limited page
        return redirect('/rate-limited')

    @app.context_processor
    def inject_version():
        return dict(version=get_version())

    @app.route('/api/config/host')
    def get_host_config():
        """Return the HOST_SERVER configuration for frontend webhook URL generation"""
        from flask import jsonify
        host_server = os.getenv('HOST_SERVER', 'http://127.0.0.1:5000')

        # Determine if webhook URL is externally accessible
        is_localhost = any(local in host_server.lower() for local in ['localhost', '127.0.0.1', '0.0.0.0'])

        return jsonify({
            'host_server': host_server,
            'is_localhost': is_localhost
        })

    return app

def setup_environment(app):
    with app.app_context():
        #load broker plugins
        app.broker_auth_functions = load_broker_auth_functions()

        # Initialize all databases in parallel for faster startup
        from concurrent.futures import ThreadPoolExecutor, as_completed
        import time

        from database.chart_prefs_db import ensure_chart_prefs_tables_exists
        from database.market_calendar_db import ensure_market_calendar_tables_exists
        from database.qty_freeze_db import ensure_qty_freeze_tables_exists

        db_init_functions = [
            ('Auth DB', ensure_auth_tables_exists),
            ('User DB', ensure_user_tables_exists),
            ('Master Contract DB', ensure_master_contract_tables_exists),
            ('API Log DB', ensure_api_log_tables_exists),
            ('Analyzer DB', ensure_analyzer_tables_exists),
            ('Settings DB', ensure_settings_tables_exists),
            ('Chartink DB', ensure_chartink_tables_exists),
            ('Traffic Logs DB', ensure_traffic_logs_exists),
            ('Latency DB', ensure_latency_tables_exists),
            ('Strategy DB', ensure_strategy_tables_exists),
            ('Sandbox DB', ensure_sandbox_tables_exists),
            ('Action Center DB', ensure_action_center_tables_exists),
            ('Chart Prefs DB', ensure_chart_prefs_tables_exists),
            ('Market Calendar DB', ensure_market_calendar_tables_exists),
            ('Qty Freeze DB', ensure_qty_freeze_tables_exists),
            ('Historify DB', ensure_historify_tables_exists),
        ]

        db_init_start = time.time()
        with ThreadPoolExecutor(max_workers=15) as executor:
            # Submit all database initialization tasks
            futures = {executor.submit(func): name for name, func in db_init_functions}

            # Wait for all to complete
            for future in as_completed(futures):
                db_name = futures[future]
                try:
                    future.result()
                except Exception as e:
                    logger.error(f"Failed to initialize {db_name}: {e}")

        db_init_time = (time.time() - db_init_start) * 1000
        logger.debug(f"All databases initialized in parallel ({db_init_time:.0f}ms)")

    # Setup ngrok cleanup handlers if ngrok is enabled
    # Note: The actual tunnel creation happens in the __main__ block below
    if os.getenv('NGROK_ALLOW') == 'TRUE':
        from utils.ngrok_manager import setup_ngrok_handlers
        setup_ngrok_handlers()

app = create_app()

# Explicitly call the setup environment function
setup_environment(app)

# Restore caches from database on startup (enables restart without re-login)
with app.app_context():
    try:
        from database.cache_restoration import restore_all_caches
        cache_result = restore_all_caches()

        if cache_result['success']:
            symbol_count = cache_result['symbol_cache'].get('symbols_loaded', 0)
            auth_count = cache_result['auth_cache'].get('tokens_loaded', 0)
            if symbol_count > 0 or auth_count > 0:
                logger.debug(f"Cache restoration: {symbol_count} symbols, {auth_count} auth tokens")
    except Exception as e:
        logger.debug(f"Cache restoration skipped: {e}")

# Auto-start execution engine and squareoff scheduler if in analyzer mode (parallel startup)
with app.app_context():
    try:
        from database.settings_db import get_analyze_mode
        from sandbox.execution_thread import start_execution_engine
        from sandbox.squareoff_thread import start_squareoff_scheduler
        from concurrent.futures import ThreadPoolExecutor, as_completed
        import time

        if get_analyze_mode():
            # Define service startup functions for parallel execution
            def start_engine():
                success, message = start_execution_engine()
                return ('execution_engine', success, message)

            def start_scheduler():
                success, message = start_squareoff_scheduler()
                return ('squareoff_scheduler', success, message)

            def run_catchup():
                from sandbox.position_manager import catchup_missed_settlements
                catchup_missed_settlements()
                return ('catchup_settlement', True, 'Completed')

            # Start all services in parallel
            startup_start = time.time()
            with ThreadPoolExecutor(max_workers=3) as executor:
                # Submit all tasks
                futures = [
                    executor.submit(start_engine),
                    executor.submit(start_scheduler),
                    executor.submit(run_catchup)
                ]

                # Collect results as they complete
                for future in as_completed(futures):
                    try:
                        service_name, success, message = future.result()
                        if service_name == 'execution_engine':
                            if success:
                                logger.debug("Execution engine auto-started (Analyzer mode is ON)")
                            else:
                                logger.warning(f"Failed to auto-start execution engine: {message}")
                        elif service_name == 'squareoff_scheduler':
                            if success:
                                logger.debug("Square-off scheduler auto-started (Analyzer mode is ON)")
                            else:
                                logger.warning(f"Failed to auto-start square-off scheduler: {message}")
                        elif service_name == 'catchup_settlement':
                            logger.debug("Catch-up settlement check completed on startup")
                    except Exception as e:
                        logger.error(f"Error starting service: {e}")

            startup_time = (time.time() - startup_start) * 1000
            logger.debug(f"Services started in parallel ({startup_time:.0f}ms)")
    except Exception as e:
        logger.error(f"Error checking analyzer mode on startup: {e}")

# Integrate the WebSocket proxy server with the Flask app
# Check if running in Docker (standalone mode) or local (integrated mode)
# Docker is detected by checking for /.dockerenv file or APP_MODE override
is_docker = os.path.exists('/.dockerenv') or os.environ.get('APP_MODE', '').strip().strip("'\"") == 'standalone'

if is_docker:
    logger.debug("Running in Docker/standalone mode - WebSocket server started separately by start.sh")
else:
    logger.debug("Running in local/integrated mode - Starting WebSocket proxy in Flask")
    start_websocket_proxy(app)

# Start Flask development server with SocketIO support if directly executed
if __name__ == '__main__':
    # Get environment variables
    host_ip = os.getenv('FLASK_HOST_IP', '127.0.0.1')  # Default to '127.0.0.1' if not set
    port = int(os.getenv('FLASK_PORT', 5000))  # Default to 5000 if not set
    ws_port = int(os.getenv('WEBSOCKET_PORT', 8765))  # WebSocket port
    debug = os.getenv('FLASK_DEBUG', 'False').lower() in ('true', '1', 't')  # Default to False if not set

    # Start ngrok tunnel if enabled
    ngrok_url = None
    if os.getenv('NGROK_ALLOW', 'FALSE').upper() == 'TRUE':
        from utils.ngrok_manager import start_ngrok_tunnel
        ngrok_url = start_ngrok_tunnel(port)

    # Clean startup banner
    import socket

    # Determine display IP for banner
    display_ip = host_ip
    if host_ip == '0.0.0.0':
        # Get local network IP for display
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            display_ip = s.getsockname()[0]
            s.close()
        except:
            display_ip = "127.0.0.1"

    # Print startup banner
    version = get_version()
    web_url = f"http://{display_ip}:{port}"
    ws_url = f"ws://{display_ip}:{ws_port}"
    docs_url = "https://docs.openalgo.in"

    # Use ngrok URL if tunnel was established
    host_server = ngrok_url if ngrok_url else ''

    # ANSI color codes
    GREEN = "\033[92m"
    CYAN = "\033[96m"
    MAGENTA = "\033[95m"
    WHITE = "\033[97m"
    YELLOW = "\033[93m"
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"

    # Border color
    B = CYAN

    slogan = "Your Personal Algo Trading Platform"

    MIN_WIDTH = 54
    ansi_escape = re.compile(r"\x1B\[[0-9;]*m")

    def visible_len(text: str) -> int:
        return len(ansi_escape.sub("", text))

    title = f" OpenAlgo v{version} "

    content_samples = [
        "",
        slogan,
        f"{WHITE}{BOLD}Endpoints{RESET}",
        f"{WHITE}Web App{RESET}    {CYAN}{web_url}{RESET}",
        f"{WHITE}WebSocket{RESET}  {MAGENTA}{ws_url}{RESET}",
        f"{WHITE}Docs{RESET}       {YELLOW}{docs_url}{RESET}",
        f"{WHITE}Status{RESET}     {GREEN}{BOLD}Ready{RESET}",
    ]
    # Add Host URL to samples if ngrok is enabled (for width calculation)
    if host_server:
        content_samples.insert(5, f"{WHITE}Host URL{RESET}   {GREEN}{host_server}{RESET}")

    inner_target = max(MIN_WIDTH - 4, max((visible_len(text) for text in content_samples), default=0))
    W = max(inner_target + 4, len(title) + 5)

    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        "╭╮╰╯│─".encode(encoding)
        TL, TR, BL, BR = "╭", "╮", "╰", "╯"
        H, V = "─", "│"
    except Exception:
        TL, TR, BL, BR = "+", "+", "+", "+"
        H, V = "-", "|"

    # Helper to create a padded line
    def mkline(text=""):
        inner = W - 4  # subtract 2 borders + 2 spaces
        text_len = visible_len(text)
        padding = max(inner - text_len, 0)
        return f"{B}{V}{RESET} {text}{' ' * padding} {B}{V}{RESET}"

    # Build banner
    top_dashes = max(0, W - 5 - len(title))  # ensures non-negative padding around the title

    print()
    print(f"{B}{TL}{H * 3}{GREEN}{BOLD}{title}{RESET}{B}{H * top_dashes}{TR}{RESET}")
    print(mkline())

    # Centered slogan
    inner_w = W - 4
    text_len = visible_len(slogan)
    sl = max((inner_w - text_len) // 2, 0)
    sr = max(inner_w - text_len - sl, 0)
    print(f"{B}{V}{RESET} {' ' * sl}{DIM}{slogan}{RESET}{' ' * sr} {B}{V}{RESET}")

    print(mkline())
    print(mkline(f"{WHITE}{BOLD}Endpoints{RESET}"))
    print(mkline(f"{WHITE}Web App{RESET}    {CYAN}{web_url}{RESET}"))
    print(mkline(f"{WHITE}WebSocket{RESET}  {MAGENTA}{ws_url}{RESET}"))
    if host_server:
        print(mkline(f"{WHITE}Host URL{RESET}   {GREEN}{host_server}{RESET}"))
    print(mkline(f"{WHITE}Docs{RESET}       {YELLOW}{docs_url}{RESET}"))
    print(mkline())
    print(mkline(f"{WHITE}Status{RESET}     {GREEN}{BOLD}Ready{RESET}"))
    print(mkline())
    print(f"{B}{BL}{H * (W - 2)}{BR}{RESET}")
    print()

    # Exclude strategies and logs directories from reloader to prevent crashes when editing strategy files
    reloader_options = {
        'exclude_patterns': [
            '*/strategies/*',
            '*/log/*',
            '*.log',
            '*.bak',
        ]
    }
    socketio.run(app, host=host_ip, port=port, debug=debug, reloader_options=reloader_options)