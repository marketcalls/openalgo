import os
import sys
from dotenv import load_dotenv

def load_and_check_env_variables():
    # Define the path to the .env file in the main application path
    env_path = os.path.join(os.path.dirname(__file__), '..', '.env')

    # Check if the .env file exists
    if not os.path.exists(env_path):
        print("Error: .env file not found at the expected location.")
        sys.exit(1)

    # Load environment variables from the .env file
    load_dotenv(dotenv_path=env_path)

    # Define the required environment variables
    required_vars = [
        'BROKER_API_KEY', 'BROKER_API_SECRET', 'REDIRECT_URL', 'APP_KEY', 'DATABASE_URL',
        'NGROK_ALLOW', 'HOST_SERVER', 'FLASK_HOST_IP', 'FLASK_PORT', 'FLASK_DEBUG',
        'FLASK_APP_VERSION', 'LOGIN_RATE_LIMIT_MIN', 'LOGIN_RATE_LIMIT_HOUR',
        'API_RATE_LIMIT', 'SMART_ORDER_DELAY'
    ]

    # Check if each required environment variable is set
    missing_vars = [var for var in required_vars if os.getenv(var) is None]

    if missing_vars:
        missing_list = ', '.join(missing_vars)
        print(f"Error: The following environment variables are missing: {missing_list}")
        sys.exit(1)