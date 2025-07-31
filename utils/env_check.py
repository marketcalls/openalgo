import os
import sys
from dotenv import load_dotenv

def check_env_version_compatibility():
    """
    Check if .env file version matches .sample.env version
    Returns True if compatible, False if update needed
    """
    base_dir = os.path.dirname(__file__) + '/..'
    env_path = os.path.join(base_dir, '.env')
    sample_env_path = os.path.join(base_dir, '.sample.env')
    
    # Check if both files exist
    if not os.path.exists(env_path):
        print("\nError: .env file not found.")
        print("Solution: Copy .sample.env to .env and configure your settings")
        return False
        
    if not os.path.exists(sample_env_path):
        print("\nWarning: .sample.env file not found. Cannot check version compatibility.")
        return True  # Assume compatible if sample file is missing
    
    # Read version from .env file
    env_version = None
    try:
        with open(env_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line.startswith('ENV_CONFIG_VERSION'):
                    env_version = line.split('=')[1].strip().strip("'\"")
                    break
    except Exception as e:
        print(f"\nWarning: Could not read .env file: {e}")
        return True  # Assume compatible if can't read
    
    # Read version from .sample.env file
    sample_version = None
    try:
        with open(sample_env_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line.startswith('ENV_CONFIG_VERSION'):
                    sample_version = line.split('=')[1].strip().strip("'\"")
                    break
    except Exception as e:
        print(f"\nWarning: Could not read .sample.env file: {e}")
        return True  # Assume compatible if can't read
    
    # If either version is missing, warn but continue
    if not env_version:
        print("\n" + "="*70)
        print("⚠️  WARNING: No version found in your .env file")
        print("   Your .env file may be outdated and missing new configuration options.")
        print("   Consider updating it with new variables from .sample.env")
        print("="*70)
        return True
        
    if not sample_version:
        return True  # Can't compare without sample version
    
    # Compare versions using simple string comparison for semantic versions
    try:
        def version_tuple(v):
            """Convert version string to tuple of integers for comparison"""
            return tuple(map(int, v.split('.')))
        
        env_ver = version_tuple(env_version)
        sample_ver = version_tuple(sample_version)
        
        if env_ver < sample_ver:
            print("\n" + "🔴 " + "="*68)
            print("🔴  CONFIGURATION UPDATE REQUIRED")
            print("🔴 " + "="*68)
            print(f"   Your .env version: {env_version}")
            print(f"   Required version:  {sample_version}")
            print("")
            print("   ACTION NEEDED:")
            print("   1. Backup your current .env file")
            print("   2. Compare .env with .sample.env")
            print("   3. Add any missing configuration variables to your .env")
            print("   4. Update ENV_CONFIG_VERSION in your .env to match .sample.env")
            print("")
            print("   New features may not work properly with an outdated configuration!")
            print("🔴 " + "="*68)
            
            # Give user a chance to continue anyway
            try:
                response = input("\n⚠️  Continue anyway? (y/N): ").lower().strip()
                if response not in ['y', 'yes']:
                    print("\nApplication startup cancelled. Please update your .env file.")
                    return False
            except (KeyboardInterrupt, EOFError):
                print("\nApplication startup cancelled.")
                return False
                
        elif env_ver > sample_ver:
            print(f"\n✅ Your .env version ({env_version}) is newer than sample ({sample_version})")
            
        else:
            print(f"\n✅ Configuration version check passed ({env_version})")
            
    except Exception as e:
        print(f"\nWarning: Could not parse version numbers: {e}")
        print(f"   .env version: {env_version}")
        print(f"   .sample.env version: {sample_version}")
        return True  # Continue if version parsing fails
    
    return True

def load_and_check_env_variables():
    # First, check version compatibility
    if not check_env_version_compatibility():
        sys.exit(1)
    
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
        'ENV_CONFIG_VERSION',  # Version tracking for configuration compatibility
        'BROKER_API_KEY', 
        'BROKER_API_SECRET', 
        'REDIRECT_URL', 
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
        'ORDER_RATE_LIMIT',  # Rate limit for order placement, modification, and cancellation
        'SMART_ORDER_RATE_LIMIT',  # Rate limit for smart order placement
        'WEBHOOK_RATE_LIMIT',  # Rate limit for webhook endpoints
        'STRATEGY_RATE_LIMIT',  # Rate limit for strategy operations
        'SMART_ORDER_DELAY',
        'SESSION_EXPIRY_TIME',  # Added SESSION_EXPIRY_TIME as it's required for session management
        'WEBSOCKET_HOST',  # Host for the WebSocket server
        'WEBSOCKET_PORT',  # Port for the WebSocket server
        'WEBSOCKET_URL',   # Full WebSocket URL for clients
        'LOG_TO_FILE',     # Enable/disable file logging
        'LOG_LEVEL',       # Logging level
        'LOG_DIR',         # Directory for log files
        'LOG_FORMAT',      # Log message format
        'LOG_RETENTION'    # Days to retain log files
    ]

    # Check if each required environment variable is set
    missing_vars = [var for var in required_vars if os.getenv(var) is None]

    if missing_vars:
        missing_list = ', '.join(missing_vars)
        print(f"Error: The following environment variables are missing: {missing_list}")
        print("\nSolution: Check .sample.env for the latest configuration format")
        sys.exit(1)

    # Special validation for broker-specific API key formats
    broker_api_key = os.getenv('BROKER_API_KEY', '')
    broker_api_secret = os.getenv('BROKER_API_SECRET', '')
    redirect_url = os.getenv('REDIRECT_URL', '')
    
    # Extract broker name from redirect URL for validation
    broker_name = None
    try:
        import re
        match = re.search(r'/([^/]+)/callback$', redirect_url)
        if match:
            broker_name = match.group(1).lower()
    except:
        pass
    
    # Validate 5paisa API key format
    if broker_name == 'fivepaisa':
        if ':::' not in broker_api_key or broker_api_key.count(':::') != 2:
            print("\nError: Invalid 5paisa API key format detected!")
            print("The BROKER_API_KEY for 5paisa must be in the format:")
            print("  BROKER_API_KEY = 'User_Key:::User_ID:::client_id'")
            print("\nExample:")
            print("  BROKER_API_KEY = 'abc123xyz:::12345678:::5P12345678'")
            print("  BROKER_API_SECRET = 'your_encryption_key'")
            print("\nFor detailed instructions, please refer to:")
            print("  https://docs.openalgo.in/connect-brokers/brokers/5paisa")
            sys.exit(1)
            
    # Validate flattrade API key format
    elif broker_name == 'flattrade':
        if ':::' not in broker_api_key or broker_api_key.count(':::') != 1:
            print("\nError: Invalid Flattrade API key format detected!")
            print("The BROKER_API_KEY for Flattrade must be in the format:")
            print("  BROKER_API_KEY = 'client_id:::api_key'")
            print("\nExample:")
            print("  BROKER_API_KEY = 'FT123456:::your_api_key_here'")
            print("  BROKER_API_SECRET = 'your_api_secret'")
            print("\nFor detailed instructions, please refer to:")
            print("  https://docs.openalgo.in/connect-brokers/brokers/flattrade")
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
        
    # Validate WebSocket port
    try:
        ws_port = int(os.getenv('WEBSOCKET_PORT'))
        if ws_port < 0 or ws_port > 65535:
            raise ValueError
    except ValueError:
        print("\nError: WEBSOCKET_PORT must be a valid port number (0-65535)")
        print("Example: WEBSOCKET_PORT='8765'")
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
        print("\nSolution: Check the .sample.env file for the latest configuration")
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

    # Validate rate limits format
    rate_limit_vars = ['LOGIN_RATE_LIMIT_MIN', 'LOGIN_RATE_LIMIT_HOUR', 'API_RATE_LIMIT', 'ORDER_RATE_LIMIT', 'SMART_ORDER_RATE_LIMIT', 'WEBHOOK_RATE_LIMIT', 'STRATEGY_RATE_LIMIT']
    rate_limit_pattern = re.compile(r'^\d+\s+per\s+(second|minute|hour|day)$')
    
    for var in rate_limit_vars:
        value = os.getenv(var, '')
        if not rate_limit_pattern.match(value):
            print(f"\nError: Invalid {var} format.")
            print("Format should be: 'number per timeunit'")
            print("Example: '5 per minute', '10 per second'")
            sys.exit(1)

    # Validate SESSION_EXPIRY_TIME format (24-hour format)
    time_pattern = re.compile(r'^([01]?[0-9]|2[0-3]):[0-5][0-9]$')
    session_expiry = os.getenv('SESSION_EXPIRY_TIME', '')
    if not time_pattern.match(session_expiry):
        print("\nError: Invalid SESSION_EXPIRY_TIME format.")
        print("Format should be 24-hour time (HH:MM)")
        print("Example: '03:00', '15:30'")
        sys.exit(1)

    # Validate SMART_ORDER_DELAY is a valid float
    try:
        delay = float(os.getenv('SMART_ORDER_DELAY', '0'))
        if delay < 0:
            raise ValueError
    except ValueError:
        print("\nError: SMART_ORDER_DELAY must be a valid positive number")
        print("Example: SMART_ORDER_DELAY='0.5'")
        sys.exit(1)
        
    # Validate WEBSOCKET_URL format
    websocket_url = os.getenv('WEBSOCKET_URL', '')
    if not websocket_url.startswith('ws://') and not websocket_url.startswith('wss://'):
        print("\nError: WEBSOCKET_URL must start with 'ws://' or 'wss://'")
        print("Example: WEBSOCKET_URL='ws://localhost:8765'")
        sys.exit(1)
        
    # Validate logging configuration
    log_to_file = os.getenv('LOG_TO_FILE', '').lower()
    if log_to_file not in ['true', 'false']:
        print("\nError: LOG_TO_FILE must be 'True' or 'False'")
        print("Example: LOG_TO_FILE=False")
        sys.exit(1)
        
    log_level = os.getenv('LOG_LEVEL', '').upper()
    valid_log_levels = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
    if log_level not in valid_log_levels:
        print(f"\nError: LOG_LEVEL must be one of: {', '.join(valid_log_levels)}")
        print("Example: LOG_LEVEL=INFO")
        sys.exit(1)
        
    # Validate LOG_RETENTION is a positive integer
    try:
        retention = int(os.getenv('LOG_RETENTION', '0'))
        if retention < 1:
            raise ValueError
    except ValueError:
        print("\nError: LOG_RETENTION must be a positive integer (days)")
        print("Example: LOG_RETENTION=14")
        sys.exit(1)
        
    # Validate LOG_DIR is not empty
    log_dir = os.getenv('LOG_DIR', '').strip()
    if not log_dir:
        print("\nError: LOG_DIR cannot be empty")
        print("Example: LOG_DIR=log")
        sys.exit(1)
        
    # Validate LOG_FORMAT is not empty
    log_format = os.getenv('LOG_FORMAT', '').strip()
    if not log_format:
        print("\nError: LOG_FORMAT cannot be empty")
        print("Example: LOG_FORMAT=[%(asctime)s] %(levelname)s in %(module)s: %(message)s")
        sys.exit(1)
