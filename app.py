from flask import Flask
from blueprints.auth import auth_bp 
from blueprints.dashboard import dashboard_bp
from blueprints.orders import orders_bp
from blueprints.search import search_bp
from blueprints.api_v1 import api_v1_bp
from blueprints.core import core_bp  # Import the core blueprint

from dotenv import load_dotenv
import os

app = Flask(__name__)
load_dotenv()

# Register the blueprints
app.register_blueprint(auth_bp)
app.register_blueprint(dashboard_bp)
app.register_blueprint(orders_bp)
app.register_blueprint(search_bp)
app.register_blueprint(api_v1_bp)
app.register_blueprint(core_bp)  # Register the core blueprint

# Environment variables
app.secret_key = os.getenv('APP_KEY')

if __name__ == '__main__':
    app.run()
