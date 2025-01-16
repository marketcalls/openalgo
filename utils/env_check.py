import os
import sys
from dotenv import load_dotenv
import re
from datetime import datetime, timedelta
import pytz

def load_and_check_env_variables():
    # Define the path to the .env file in the main application path
    env_path = os.path.join(os.path.dirname(__file__), '..', '.env')

    # Check if the .env file exists
    if not os.path.exists(env_path):
        print("Error: .env file not found at the expected location.")
        print("\nSolution: Copy .sample.env to .env and configure your settings")
        sys.exit(1)

    # Load environment variables from the .env file with override=True to ensure values are updated
    load_dotenv(dotenv_path=env_path, override=True)

    # Define the required environment variables
    required_vars = [
        'APP_KEY', 
        'API_KEY_PEPPER',  # Added API_KEY_PEPPER as it's required for security
        'DATABASE_URL',
        'NGROK_ALLOW', 
        'HOST_SERVER', 
        'FLASK_HOST_IP', 
        'FLASK_PORT', 
        'FLASK_DEBUG',
        'FLASK_ENV',  # Added FLASK_ENV as it's important for app configuration
        'LOGIN_RATE_LIMIT_MIN', 
        'LOGIN_RATE_LIMIT_HOUR',
        'API_RATE_LIMIT', 
        'SMART_ORDER_DELAY',
        'SESSION_EXPIRY_TIME'  # Added SESSION_EXPIRY_TIME as it's required for session management
    ]

    # Check if each required environment variable is set
    missing_vars = [var for var in required_vars if os.getenv(var) is None]

    if missing_vars:
        missing_list = ', '.join(missing_vars)
        print(f"Error: The following environment variables are missing: {missing_list}")
        print("\nSolution: Check .sample.env for the latest configuration format")
        sys.exit(1)

    # Validate environment variable values
    flask_debug = os.getenv('FLASK_DEBUG', '').lower()
    if flask_debug not in ['true', 'false', '1', '0', 't', 'f']:
        print("\nError: FLASK_DEBUG must be 'True' or 'False'")
        print("Example: FLASK_DEBUG='False'")
        sys.exit(1)

    flask_env = os.getenv('FLASK_ENV', '').lower()
    if flask_env not in ['development', 'production']:
        print("\nError: FLASK_ENV must be 'development' or 'production'")
        print("Example: FLASK_ENV='production'")
        sys.exit(1)

    try:
        port = int(os.getenv('FLASK_PORT'))
        if port < 0 or port > 65535:
            raise ValueError
    except ValueError:
        print("\nError: FLASK_PORT must be a valid port number (0-65535)")
        print("Example: FLASK_PORT='5000'")
        sys.exit(1)

    # Validate rate limits format
    login_rate_limit_min = os.getenv('LOGIN_RATE_LIMIT_MIN', '')
    login_rate_limit_hour = os.getenv('LOGIN_RATE_LIMIT_HOUR', '')
    api_rate_limit = os.getenv('API_RATE_LIMIT', '')

    rate_limits = [
        ('LOGIN_RATE_LIMIT_MIN', login_rate_limit_min),
        ('LOGIN_RATE_LIMIT_HOUR', login_rate_limit_hour),
        ('API_RATE_LIMIT', api_rate_limit)
    ]

    for limit_name, limit_value in rate_limits:
        if not limit_value or 'per' not in limit_value.lower():
            print(f"\nError: Invalid {limit_name} format")
            print(f"Current value: '{limit_value}'")
            print("Required format: '<number> per <interval>'")
            print("Example: '5 per minute' or '100 per hour'")
            sys.exit(1)

    # Check smart order delay format
    try:
        smart_order_delay = float(os.getenv('SMART_ORDER_DELAY', '0'))
        if smart_order_delay < 0:
            raise ValueError
    except ValueError:
        print("\nError: SMART_ORDER_DELAY must be a non-negative number")
        print("Example: SMART_ORDER_DELAY='0.5'")
        sys.exit(1)

    # Check session expiry time format (24-hour format)
    time_pattern = re.compile(r'^([01]?[0-9]|2[0-3]):[0-5][0-9]$')
    session_expiry = os.getenv('SESSION_EXPIRY_TIME', '')
    
    if not time_pattern.match(session_expiry):
        print("\nError: Invalid SESSION_EXPIRY_TIME format")
        print("Format should be 24-hour time (HH:MM)")
        print("Example: '03:00', '15:30'")
        sys.exit(1)

    # All checks passed
    return True
