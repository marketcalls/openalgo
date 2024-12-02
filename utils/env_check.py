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

    # Check REDIRECT_URL configuration
    redirect_url = os.getenv('REDIRECT_URL')
    default_value = 'http://127.0.0.1:5000/<broker>/callback'
    
    if redirect_url == default_value:
        print("\nError: Default REDIRECT_URL detected in .env file.")
        print("The application cannot start with the default configuration.")
        print("\nPlease:")
        print("1. Open your .env file")
        print("2. Change the REDIRECT_URL to use your specific broker")
        print("3. Save the file")
        print("\nExample: If using Zerodha, change:")
        print(f"  REDIRECT_URL = '{default_value}'")
        print("to:")
        print("  REDIRECT_URL = 'http://127.0.0.1:5000/zerodha/callback'")
        sys.exit(1)

    if '<broker>' in redirect_url:
        print("\nError: Invalid REDIRECT_URL configuration detected.")
        print("The application cannot start with '<broker>' in REDIRECT_URL.")
        print("\nPlease update your .env file to use your specific broker name.")
        print("Example: http://127.0.0.1:5000/zerodha/callback")
        sys.exit(1)

    # Validate broker name
    valid_brokers_str = os.getenv('VALID_BROKERS', '')
    if not valid_brokers_str:
        print("\nError: VALID_BROKERS not configured in .env file.")
        print("\nSoluton: Check the .sample.env file latest configuration file")
        print("The application cannot start without valid broker configuration.")
        sys.exit(1)

    valid_brokers = set(broker.strip().lower() for broker in valid_brokers_str.split(','))
    
    try:
        import re
        match = re.search(r'/([^/]+)/callback$', redirect_url)
        if not match:
            print("\nError: Invalid REDIRECT_URL format.")
            print("The URL must end with '/broker_name/callback'")
            print("Example: http://127.0.0.1:5000/zerodha/callback")
            sys.exit(1)
            
        broker_name = match.group(1).lower()
        if broker_name not in valid_brokers:
            print("\nError: Invalid broker name in REDIRECT_URL.")
            print(f"Broker '{broker_name}' is not in the list of valid brokers.")
            print(f"\nValid brokers are: {', '.join(sorted(valid_brokers))}")
            print("\nPlease update your REDIRECT_URL with a valid broker name.")
            sys.exit(1)
            
    except Exception as e:
        print("\nError: Could not validate REDIRECT_URL format.")
        print(f"Details: {str(e)}")
        print("\nThe URL must follow the format: http://domain/broker_name/callback")
        print("Example: http://127.0.0.1:5000/zerodha/callback")
        sys.exit(1)
