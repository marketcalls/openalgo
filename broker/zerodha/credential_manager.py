
import os
import json
import logging

logger = logging.getLogger(__name__)

def get_shared_credentials(default_api_key, default_access_token):
    """
    Resolve credentials to use: either local defaults or shared credentials from a file.

    Args:
        default_api_key (str): The local API key provided by env/db.
        default_access_token (str): The local access token provided by env/db.

    Returns:
        tuple: (api_key, access_token)

    Raises:
        ValueError: If shared credentials are enabled (via env var) but invalid/missing.
        IOError: If the shared credentials file cannot be read.
    """
    shared_credentials_file = os.getenv('SHARED_CREDENTIALS_FILE')

    if not shared_credentials_file:
        # Normal mode: use local credentials
        return default_api_key, default_access_token

    try:
        if not os.path.exists(shared_credentials_file):
            raise FileNotFoundError(f"Shared credentials file not found at: {shared_credentials_file}")

        with open(shared_credentials_file, 'r') as f:
            creds = json.load(f)

        api_key = creds.get('api_key')
        access_token = creds.get('access_token')

        if not api_key or not access_token:
            raise ValueError(f"Shared credentials file exists but contains empty keys. details: {creds}")

        if default_access_token == access_token:
            logger.info("TOKEN CHECK: SAME - Default access token matches shared access token")
        else:
            logger.critical(
                "\n" + "!"*50 + "\n"
                "NOT SAME - Default access token DOES NOT match shared access token!\n"
                f"Default: {default_access_token}\n"
                f"Shared : {access_token}\n"
                + "!"*50
            )

        return api_key, access_token

    except Exception as e:
        logger.error(f"CRITICAL: Failed to load shared credentials: {e}")
        # Fail fast - do not fallback to local creds if shared mode was explicitly requested
        raise

def get_shared_auth_token(default_auth_token):
    """
    Resolve credentials to use: either local defaults or shared credentials from a file.

    Args:
        default_auth_token (str): The local auth token provided by env/db.

    Returns:
        str: auth_token

    Raises:
        ValueError: If shared credentials are enabled (via env var) but invalid/missing.
        IOError: If the shared credentials file cannot be read.
    """
    shared_credentials_file = os.getenv('SHARED_CREDENTIALS_FILE')

    if not shared_credentials_file:
        # Normal mode: use local credentials
        return default_auth_token

    try:
        if not os.path.exists(shared_credentials_file):
            raise FileNotFoundError(f"Shared credentials file not found at: {shared_credentials_file}")

        with open(shared_credentials_file, 'r') as f:
            creds = json.load(f)

        api_key = creds.get('api_key')
        access_token = creds.get('access_token')

        if not api_key or not access_token:
            raise ValueError(f"Shared credentials file exists but contains empty keys. details: {creds}")

        shared_auth_token = f"{api_key}:{access_token}"

        # Check if they match. Note: default_auth_token usually comes as "api_key:access_token"
        if default_auth_token == shared_auth_token:
            logger.info("TOKEN CHECK: SAME - Default auth token matches shared auth token")
        else:
             logger.critical(
                "\n" + "!"*50 + "\n"
                "NOT SAME - Default auth token DOES NOT match shared auth token!\n"
                f"Default: {default_auth_token}\n"
                f"Shared : {shared_auth_token}\n"
                + "!"*50
            )

        return shared_auth_token

    except Exception as e:
        logger.error(f"CRITICAL: Failed to load shared credentials: {e}")
        # Fail fast - do not fallback to local creds if shared mode was explicitly requested
        raise
