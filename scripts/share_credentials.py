
import os
import sys
import json
import logging
from datetime import datetime

# Add project root to path to allow imports from database/
# scripts/ is one level deep, so .. is root
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.auth_db import get_auth_token, Auth

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("share_credentials")

def load_env_file():
    """Manually load .env file without python-dotenv dependency"""
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
    try:
        if os.path.exists(env_path):
            with open(env_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    if '=' in line:
                        key, value = line.split('=', 1)
                        # Remove quotes if present
                        key = key.strip()
                        value = value.strip()
                        if value.startswith("'") and value.endswith("'"):
                            value = value[1:-1]
                        elif value.startswith('"') and value.endswith('"'):
                            value = value[1:-1]
                        
                        # Only set if not already set (respect existing env vars)
                        if key not in os.environ:
                            os.environ[key] = value
            logger.info(f"Loaded environment from {env_path}")
        else:
            logger.warning(f".env file not found at {env_path}")
    except Exception as e:
        logger.error(f"Error loading .env file: {e}")

def main():
    # Load environment variables manually
    load_env_file()
    
    # 1. Get configuration
    shared_file_path = os.getenv('SHARED_CREDENTIALS_FILE')
    user_id = os.getenv('BROKER_USER_ID')
    api_key = os.getenv('BROKER_API_KEY')
    
    if not shared_file_path:
        logger.error("Error: SHARED_CREDENTIALS_FILE environment variable is not set.")
        sys.exit(1)
        
    if not user_id:
        logger.error("Error: BROKER_USER_ID environment variable is not set.")
        sys.exit(1)
        
    if not api_key:
        logger.error("Error: BROKER_API_KEY environment variable is not set.")
        sys.exit(1)

    logger.info(f"Preparing to share credentials for user: {user_id}")
    
    # 2. Fetch Access Token
    try:
        # Note: get_auth_token returns the decrypted token string
        # It might return "api_key:access_token" or just "access_token"
        
        auth_token = get_auth_token(user_id)
        
        if not auth_token:
            logger.error(f"Error: No valid auth token found in database for user {user_id}. Please login first.")
            
            # DEBUG: List available users to help debugging
            try:
                logger.info("--- Available Users in Database ---")
                all_users = Auth.query.all()
                if not all_users:
                    logger.info("No users found in database.")
                for u in all_users:
                    logger.info(f"User: {u.name}, Broker: {u.broker}, User ID: {u.user_id}")
                logger.info("-----------------------------------")
            except Exception as db_e:
                logger.error(f"Failed to list users from DB: {db_e}")
                
            sys.exit(1)
            
        # Clean access token if it's in composite format
        real_access_token = auth_token
        if ':' in auth_token:
            parts = auth_token.split(':')
            if len(parts) >= 2:
                real_access_token = parts[1]
                logger.debug("Extracted access token from composite string.")
        
    except Exception as e:
        logger.error(f"Error fetching token from DB: {e}")
        sys.exit(1)

    # 3. Create JSON payload
    payload = {
        "api_key": api_key,
        "access_token": real_access_token,
        "updated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_user_id": user_id
    }
    
    # 4. Write to file
    try:
        # Ensure directory exists (if path includes directories)
        dir_name = os.path.dirname(shared_file_path)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)
        
        with open(shared_file_path, 'w') as f:
            json.dump(payload, f, indent=2)
            
        logger.info(f"Successfully updated shared credentials at: {shared_file_path}")
        
    except Exception as e:
        logger.error(f"Error writing to file: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
