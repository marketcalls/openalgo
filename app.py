# Load and check environment variables before anything else
from utils.env_check import load_and_check_env_variables  # Import the environment check function
load_and_check_env_variables()

from flask import Flask, render_template, session
from flask_wtf.csrf import CSRFProtect  # Import CSRF protection
from extensions import socketio  # Import SocketIO
from limiter import limiter  # Import the Limiter instance
from cors import cors        # Import the CORS instance
from csp import apply_csp_middleware  # Import the CSP middleware
from utils.version import get_version  # Import version management
from utils.latency_monitor import init_latency_monitoring  # Import latency monitoring
from utils.traffic_logger import init_traffic_logging  # Import traffic logging
from utils.security_middleware import init_security_middleware  # Import security middleware
from utils.logging import get_logger, log_startup_banner, highlight_url  # Import centralized logging
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


    # Exempt webhook endpoints from CSRF protection after app initialization
    with app.app_context():
        # Exempt webhook endpoints from CSRF protection
        csrf.exempt(app.view_functions['chartink_bp.webhook'])
        csrf.exempt(app.view_functions['strategy_bp.webhook'])
        
        # Exempt broker callback endpoints from CSRF protection (OAuth callbacks from external providers)
        csrf.exempt(app.view_functions['brlogin.broker_callback'])
        
        # Initialize latency monitoring (after registering API blueprint)
        init_latency_monitoring(app)

        # Auto-start Telegram bot if it was active
        try:
            import sys
            bot_config = get_bot_config()
            if bot_config.get('is_active') and bot_config.get('bot_token'):
                logger.info("Auto-starting Telegram bot...")

                # Check if we're in eventlet environment
                if 'eventlet' in sys.modules:
                    logger.info("Eventlet detected during auto-start - using synchronous initialization")
                    # Use synchronous initialization for eventlet
                    success, message = telegram_bot_service.initialize_bot_sync(token=bot_config['bot_token'])
                else:
                    # Initialize the bot in a separate thread for non-eventlet environments
                    logger.info("Standard environment during auto-start - using async initialization")
                    import asyncio
                    import threading

                    def init_bot():
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        try:
                            return loop.run_until_complete(
                                telegram_bot_service.initialize_bot(token=bot_config['bot_token'])
                            )
                        finally:
                            loop.close()

                    result = [None]
                    def run_init():
                        result[0] = init_bot()

                    thread = threading.Thread(target=run_init)
                    thread.start()
                    thread.join(timeout=10)

                    success, message = result[0] if result[0] else (False, "Initialization timeout")

                if success:
                    # Start the bot (now synchronous)
                    success, message = telegram_bot_service.start_bot()

                    if success:
                        logger.info(f"Telegram bot auto-started successfully: {message}")
                    else:
                        logger.error(f"Failed to auto-start Telegram bot: {message}")
                else:
                    logger.error(f"Failed to initialize Telegram bot: {message}")

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
            request.path in ['/', '/auth/login', '/auth/reset-password', '/setup', '/download', '/faq'] or
            request.path.startswith('/auth/broker/') or  # OAuth callbacks
            request.path.startswith('/_reload-ws')):  # WebSocket reload endpoint
            return
        
        # Check if user is logged in and session is expired
        if session.get('logged_in') and not is_session_valid():
            logger.info(f"Session expired for user: {session.get('user')} - revoking tokens")
            revoke_user_tokens()
            session.clear()
            # Don't redirect here, let individual routes handle it
    
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

        return render_template('404.html'), 404

    @app.errorhandler(500)
    def internal_server_error(e):
        """Custom handler for 500 Internal Server Error"""
        # Log the error (optional)
        logger.error(f"Server Error: {e}")

        # Provide a logout option
        return render_template("500.html"), 500
        
    @app.context_processor
    def inject_version():
        return dict(version=get_version())

    return app

def setup_environment(app):
    with app.app_context():
        #load broker plugins
        app.broker_auth_functions = load_broker_auth_functions()
        # Ensure all the tables exist
        ensure_auth_tables_exists()
        ensure_user_tables_exists()
        ensure_master_contract_tables_exists()
        ensure_api_log_tables_exists()
        ensure_analyzer_tables_exists()
        ensure_settings_tables_exists()
        ensure_chartink_tables_exists()
        ensure_traffic_logs_exists()
        ensure_latency_tables_exists()
        ensure_strategy_tables_exists()
        ensure_sandbox_tables_exists()

    # Conditionally setup ngrok in development environment
    if os.getenv('NGROK_ALLOW') == 'TRUE':
        from pyngrok import ngrok
        public_url = ngrok.connect(name='flask').public_url  # Assuming Flask runs on the default port 5000
        logger.info(f"ngrok URL: {public_url}")

app = create_app()

# Explicitly call the setup environment function
setup_environment(app)

# Auto-start execution engine and squareoff scheduler if in analyzer mode
with app.app_context():
    try:
        from database.settings_db import get_analyze_mode
        from sandbox.execution_thread import start_execution_engine
        from sandbox.squareoff_thread import start_squareoff_scheduler

        if get_analyze_mode():
            # Start execution engine for order processing
            success, message = start_execution_engine()
            if success:
                logger.info("Execution engine auto-started (Analyzer mode is ON)")
            else:
                logger.warning(f"Failed to auto-start execution engine: {message}")

            # Start squareoff scheduler for MIS auto-squareoff
            success, message = start_squareoff_scheduler()
            if success:
                logger.info("Square-off scheduler auto-started (Analyzer mode is ON)")
            else:
                logger.warning(f"Failed to auto-start square-off scheduler: {message}")

            # Run catch-up settlement for any CNC positions that should have been settled while app was stopped
            from sandbox.position_manager import catchup_missed_settlements
            try:
                catchup_missed_settlements()
                logger.info("Catch-up settlement check completed on startup")
            except Exception as e:
                logger.error(f"Error in startup catch-up settlement: {e}")
    except Exception as e:
        logger.error(f"Error checking analyzer mode on startup: {e}")

# Integrate the WebSocket proxy server with the Flask app
# Check if running in Docker (standalone mode) or local (integrated mode)
# Docker is detected by checking for /.dockerenv file or APP_MODE override
is_docker = os.path.exists('/.dockerenv') or os.environ.get('APP_MODE', '').strip().strip("'\"") == 'standalone'

if is_docker:
    logger.info("Running in Docker/standalone mode - WebSocket server started separately by start.sh")
else:
    logger.info("Running in local/integrated mode - Starting WebSocket proxy in Flask")
    start_websocket_proxy(app)

# Start Flask development server with SocketIO support if directly executed
if __name__ == '__main__':
    # Get environment variables
    host_ip = os.getenv('FLASK_HOST_IP', '127.0.0.1')  # Default to '127.0.0.1' if not set
    port = int(os.getenv('FLASK_PORT', 5000))  # Default to 5000 if not set
    debug = os.getenv('FLASK_DEBUG', 'False').lower() in ('true', '1', 't')  # Default to False if not set

    # Log the OpenAlgo access URL with enhanced styling
    import socket

    # If binding to all interfaces (0.0.0.0), show all available IPs
    if host_ip == '0.0.0.0':
        urls = []
        urls.append(f"http://localhost:{port}")
        urls.append(f"http://127.0.0.1:{port}")

        # Get local network IP
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
            urls.append(f"http://{local_ip}:{port}")
        except:
            local_ip = "127.0.0.1"

        # Show accessible URLs (excluding localhost) with blue highlighting
        logger.info("=" * 60)
        logger.info("OpenAlgo is running!")
        logger.info(f"Access the application at:")
        for url in urls:
            # Skip localhost URL
            if "localhost" not in url:
                highlighted = highlight_url(url)
                logger.info(f"  → {highlighted}")
        logger.info("=" * 60)
    else:
        # Single IP binding
        url = f"http://{host_ip}:{port}"
        log_startup_banner(logger, "OpenAlgo is running!", url)

    socketio.run(app, host=host_ip, port=port, debug=debug)
