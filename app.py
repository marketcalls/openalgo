from flask import Flask
from blueprints.auth import auth_bp 
from blueprints.dashboard import dashboard_bp
from blueprints.orders import orders_bp
from blueprints.search import search_bp
from blueprints.api_v1 import api_v1_bp
from blueprints.apikey import api_key_bp
from blueprints.core import core_bp  # Import the core blueprint
from pyngrok import ngrok 

from database.db import db 

from database.auth_db import init_db as ensure_auth_tables_exists
from database.master_contract_db import init_db as ensure_master_contract_tables_exists
from database.token_db import init_db as ensure_token_tables_exists



from dotenv import load_dotenv
import os


# Initialize Flask application
app = Flask(__name__)
load_dotenv()


# Environment variables
app.secret_key = os.getenv('APP_KEY')
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL') # Adjust the environment variable name as necessary

# Initialize SQLAlchemy
db.init_app(app)

# Register the blueprints
app.register_blueprint(auth_bp)
app.register_blueprint(dashboard_bp)
app.register_blueprint(orders_bp)
app.register_blueprint(search_bp)
app.register_blueprint(api_v1_bp)
app.register_blueprint(api_key_bp)
app.register_blueprint(core_bp)  # Register the core blueprint



if __name__ == '__main__':
    
    # Setup ngrok
       
    #public_url = ngrok.connect(name='flask').public_url 
    #print(" * ngrok URL: " + public_url + " *")

    with app.app_context():
        # Ensure all the tables exist
        
        ensure_auth_tables_exists()
        ensure_master_contract_tables_exists()
        ensure_token_tables_exists()


    app.run()
