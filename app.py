from flask import Flask, render_template
from extensions import socketio  # Import SocketIO
from limiter import limiter  # Import the Limiter instance
from blueprints.auth import auth_bp
from blueprints.dashboard import dashboard_bp
from blueprints.orders import orders_bp
from blueprints.search import search_bp
from blueprints.api_v1 import api_v1_bp
from blueprints.apikey import api_key_bp
from blueprints.log import log_bp
from blueprints.tv_json import tv_json_bp
from blueprints.brlogin import brlogin_bp
from blueprints.core import core_bp  # Import the core blueprint

#from database.db import db

from database.auth_db import init_db as ensure_auth_tables_exists
from database.user_db import init_db as ensure_user_tables_exists
from database.master_contract_db import init_db as ensure_master_contract_tables_exists
from database.apilog_db import init_db as ensure_api_log_tables_exists

from utils.plugin_loader import load_broker_auth_functions

from dotenv import load_dotenv
import os


def create_app():
    # Initialize Flask application
    app = Flask(__name__)

    # Initialize SocketIO
    socketio.init_app(app)  # Link SocketIO to the Flask app

    # Initialize Flask-Limiter with the app object
    limiter.init_app(app)

    load_dotenv()

    # Environment variables
    app.secret_key = os.getenv('APP_KEY')
    app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')  # Adjust the environment variable name as necessary

    # Initialize SQLAlchemy
 #   db.init_app(app)

    # Register the blueprints
    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(orders_bp)
    app.register_blueprint(search_bp)
    app.register_blueprint(api_v1_bp)
    app.register_blueprint(api_key_bp)
    app.register_blueprint(log_bp)
    app.register_blueprint(tv_json_bp)
    app.register_blueprint(brlogin_bp)
    app.register_blueprint(core_bp)  # Register the core blueprint

    @app.errorhandler(404)
    def not_found_error(error):
        return render_template('404.html'), 404

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

    # Conditionally setup ngrok in development environment
    if os.getenv('NGROK_ALLOW') == 'TRUE':
        from pyngrok import ngrok
        public_url = ngrok.connect().public_url
        print(" * ngrok URL: " + public_url + " *")


app = create_app()

# Explicitly call the setup environment function
setup_environment(app)

# Start Flask development server with SocketIO support if directly executed
if __name__ == '__main__':
    socketio.run(app, debug=True)
