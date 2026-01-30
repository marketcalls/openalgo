
import os
import json
import logging
import threading

logger = logging.getLogger(__name__)

# Cache for shared credentials (application lifetime)
_credentials_cache = None
_cache_lock = threading.Lock()

def _load_shared_credentials_from_file(shared_credentials_file):
    """
    Internal function to load credentials from file.

    Args:
        shared_credentials_file (str): Path to the shared credentials JSON file.

    Returns:
        dict: Dictionary with 'api_key' and 'access_token' keys.

    Raises:
        FileNotFoundError: If the file doesn't exist.
        ValueError: If the file contains invalid/empty credentials.
        IOError: If the file cannot be read.
    """
    if not os.path.exists(shared_credentials_file):
        raise FileNotFoundError(f"Shared credentials file not found at: {shared_credentials_file}")

    with open(shared_credentials_file, 'r') as f:
        creds = json.load(f)

    api_key = creds.get('api_key')
    access_token = creds.get('access_token')

    if not api_key or not access_token:
        raise ValueError(f"Shared credentials file exists but contains empty keys. details: {creds}")

    logger.info(f"Loaded shared credentials from: {shared_credentials_file}")
    return {'api_key': api_key, 'access_token': access_token}


def get_shared_credentials(default_api_key, default_access_token):
    """
    Resolve credentials to use: either local defaults or shared credentials from a file.
    Credentials are cached in memory for application lifetime after first load.

    Args:
        default_api_key (str): The local API key provided by env/db.
        default_access_token (str): The local access token provided by env/db.

    Returns:
        tuple: (api_key, access_token)

    Raises:
        ValueError: If shared credentials are enabled (via env var) but invalid/missing.
        IOError: If the shared credentials file cannot be read.
    """
    global _credentials_cache

    shared_credentials_file = os.getenv('SHARED_CREDENTIALS_FILE')

    if not shared_credentials_file:
        # Normal mode: use local credentials
        return default_api_key, default_access_token

    # Check cache first (fast path - no lock needed for read)
    if _credentials_cache is not None:
        api_key = _credentials_cache['api_key']
        access_token = _credentials_cache['access_token']
        return api_key, access_token

    # Cache miss - acquire lock and load credentials
    with _cache_lock:
        # Double-check cache after acquiring lock (another thread might have loaded it)
        if _credentials_cache is not None:
            api_key = _credentials_cache['api_key']
            access_token = _credentials_cache['access_token']
            return api_key, access_token

        try:
            # Load from file and cache
            _credentials_cache = _load_shared_credentials_from_file(shared_credentials_file)
            api_key = _credentials_cache['api_key']
            access_token = _credentials_cache['access_token']

            # Log comparison for debugging
            # if default_access_token == access_token:
            #     logger.info("TOKEN CHECK: SAME - Default access token matches shared access token")
            # else:
            #     logger.critical(
            #         "\n" + "!"*50 + "\n"
            #         "NOT SAME - Default access token DOES NOT match shared access token!\n"
            #         f"Default: {default_access_token}\n"
            #         f"Shared : {access_token}\n"
            #         + "!"*50
            #     )

            return api_key, access_token

        except Exception as e:
            logger.error(f"CRITICAL: Failed to load shared credentials: {e}")
            # Fail fast - do not fallback to local creds if shared mode was explicitly requested
            raise

def get_shared_auth_token(default_auth_token):
    """
    Resolve credentials to use: either local defaults or shared credentials from a file.
    Credentials are cached in memory for application lifetime after first load.

    Args:
        default_auth_token (str): The local auth token provided by env/db.

    Returns:
        str: auth_token

    Raises:
        ValueError: If shared credentials are enabled (via env var) but invalid/missing.
        IOError: If the shared credentials file cannot be read.
    """
    global _credentials_cache

    shared_credentials_file = os.getenv('SHARED_CREDENTIALS_FILE')

    if not shared_credentials_file:
        # Normal mode: use local credentials
        return default_auth_token

    # Check cache first (fast path - no lock needed for read)
    if _credentials_cache is not None:
        api_key = _credentials_cache['api_key']
        access_token = _credentials_cache['access_token']
        return f"{api_key}:{access_token}"

    # Cache miss - acquire lock and load credentials
    with _cache_lock:
        # Double-check cache after acquiring lock (another thread might have loaded it)
        if _credentials_cache is not None:
            api_key = _credentials_cache['api_key']
            access_token = _credentials_cache['access_token']
            return f"{api_key}:{access_token}"

        try:
            # Load from file and cache
            _credentials_cache = _load_shared_credentials_from_file(shared_credentials_file)
            api_key = _credentials_cache['api_key']
            access_token = _credentials_cache['access_token']
            shared_auth_token = f"{api_key}:{access_token}"

            # Check if they match. Note: default_auth_token usually comes as "api_key:access_token"
            # if default_auth_token == shared_auth_token:
            #     logger.info("TOKEN CHECK: SAME - Default auth token matches shared auth token")
            # else:
            #      logger.critical(
            #         "\n" + "!"*50 + "\n"
            #         "NOT SAME - Default auth token DOES NOT match shared auth token!\n"
            #         f"Default: {default_auth_token}\n"
            #         f"Shared : {shared_auth_token}\n"
            #         + "!"*50
            #     )

            return shared_auth_token

        except Exception as e:
            logger.error(f"CRITICAL: Failed to load shared credentials: {e}")
            # Fail fast - do not fallback to local creds if shared mode was explicitly requested
            raise
