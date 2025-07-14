# migrations/migrate_env_to_db.py

import os
import sys

# Add current directory to Python path for imports
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.insert(0, parent_dir)

from database.broker_config_db import create_broker_config, get_broker_config, init_db
from database.user_db import find_user_by_username

try:
    from utils.logging import get_logger
    logger = get_logger(__name__)
except ImportError:
    import logging
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

def detect_env_configuration():
    """Detect if .env broker configuration exists"""
    required_vars = ['BROKER_API_KEY', 'BROKER_API_SECRET']
    env_values = {}
    
    for var in required_vars:
        value = os.getenv(var)
        if value and value != 'YOUR_BROKER_API_KEY' and value != 'YOUR_BROKER_API_SECRET':
            env_values[var] = value
        else:
            return None
    
    # Check for optional market data credentials
    market_key = os.getenv('BROKER_API_KEY_MARKET')
    market_secret = os.getenv('BROKER_API_SECRET_MARKET')
    
    if (market_key and market_key != 'YOUR_BROKER_MARKET_API_KEY' and 
        market_secret and market_secret != 'YOUR_BROKER_MARKET_API_SECRET'):
        env_values['BROKER_API_KEY_MARKET'] = market_key
        env_values['BROKER_API_SECRET_MARKET'] = market_secret
    
    # Get redirect URL
    redirect_url = os.getenv('REDIRECT_URL')
    if redirect_url:
        env_values['REDIRECT_URL'] = redirect_url
    
    return env_values

def detect_broker_from_env():
    """Detect broker name from redirect URL or ask user"""
    redirect_url = os.getenv('REDIRECT_URL', '')
    
    # Try to extract broker from redirect URL
    if '/callback' in redirect_url:
        parts = redirect_url.split('/')
        for i, part in enumerate(parts):
            if part == 'callback' and i > 0:
                return parts[i-1]
    
    return None

def migrate_env_to_database(force=False):
    """Migrate .env configuration to database"""
    
    # Initialize database
    init_db()
    
    # Detect existing configuration
    env_config = detect_env_configuration()
    if not env_config:
        logger.info("No valid .env broker configuration found")
        return False
    
    # Detect broker name
    broker_name = detect_broker_from_env()
    if not broker_name:
        print("\nCould not detect broker name from configuration.")
        print("Common broker names: dhan, angel, zerodha, upstox, kotak, etc.")
        broker_name = input("Enter broker name: ").strip().lower()
    
    if not broker_name:
        logger.error("Broker name is required")
        return False
    
    # Get admin user
    admin_user = find_user_by_username()
    if not admin_user:
        logger.error("No admin user found. Please create a user first.")
        return False
    
    user_id = admin_user.username
    
    # Check if configuration already exists
    existing_config = get_broker_config(user_id, broker_name)
    if existing_config and not force:
        print(f"\nBroker configuration for {broker_name} already exists in database.")
        response = input("Overwrite existing configuration? (y/n): ").lower()
        if response != 'y':
            logger.info("Migration cancelled by user")
            return False
    
    # Display configuration to be migrated
    print(f"\nDetected broker configuration:")
    print(f"Broker: {broker_name}")
    print(f"API Key: {env_config['BROKER_API_KEY'][:8]}..." if len(env_config['BROKER_API_KEY']) > 8 else "***")
    print(f"API Secret: {env_config['BROKER_API_SECRET'][:8]}..." if len(env_config['BROKER_API_SECRET']) > 8 else "***")
    
    if 'BROKER_API_KEY_MARKET' in env_config:
        print(f"Market API Key: {env_config['BROKER_API_KEY_MARKET'][:8]}..." if len(env_config['BROKER_API_KEY_MARKET']) > 8 else "***")
        print(f"Market API Secret: {env_config['BROKER_API_SECRET_MARKET'][:8]}..." if len(env_config['BROKER_API_SECRET_MARKET']) > 8 else "***")
    
    if 'REDIRECT_URL' in env_config:
        print(f"Redirect URL: {env_config['REDIRECT_URL']}")
    
    if not force:
        response = input("\nMigrate this configuration to database? (y/n): ").lower()
        if response != 'y':
            logger.info("Migration cancelled by user")
            return False
    
    try:
        # Create broker configuration
        config_id = create_broker_config(
            user_id=user_id,
            broker_name=broker_name,
            api_key=env_config['BROKER_API_KEY'],
            api_secret=env_config['BROKER_API_SECRET'],
            market_api_key=env_config.get('BROKER_API_KEY_MARKET'),
            market_api_secret=env_config.get('BROKER_API_SECRET_MARKET'),
            redirect_url=env_config.get('REDIRECT_URL'),
            is_default=True  # Set as default since it's the first/only config
        )
        
        logger.info(f"Successfully migrated configuration to database (ID: {config_id})")
        print(f"\n✅ Configuration migrated successfully!")
        print(f"Configuration ID: {config_id}")
        print(f"User: {user_id}")
        print(f"Broker: {broker_name}")
        
        return True
        
    except Exception as e:
        logger.error(f"Failed to migrate configuration: {e}")
        print(f"\n❌ Migration failed: {e}")
        return False

def validate_migration(user_id=None, broker_name=None):
    """Validate that migration was successful"""
    if not user_id or not broker_name:
        # Try to detect from env
        admin_user = find_user_by_username()
        if admin_user:
            user_id = admin_user.username
        
        broker_name = detect_broker_from_env()
        
        if not user_id or not broker_name:
            logger.error("Cannot validate migration - missing user_id or broker_name")
            return False
    
    try:
        config = get_broker_config(user_id, broker_name)
        if config:
            print(f"\n✅ Migration validation successful!")
            print(f"Found configuration for {user_id}/{broker_name}")
            print(f"API Key: {config['api_key'][:8]}..." if len(config['api_key']) > 8 else "***")
            print(f"Status: {config['connection_status']}")
            print(f"Default: {config['is_default']}")
            return True
        else:
            logger.error("Configuration not found in database")
            return False
            
    except Exception as e:
        logger.error(f"Migration validation failed: {e}")
        return False

def cleanup_env_file():
    """Optional: Comment out migrated environment variables"""
    env_file_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env')
    
    if not os.path.exists(env_file_path):
        logger.warning(".env file not found")
        return False
    
    response = input("\nComment out migrated variables in .env file? (y/n): ").lower()
    if response != 'y':
        return False
    
    try:
        with open(env_file_path, 'r') as f:
            lines = f.readlines()
        
        # Variables to comment out
        vars_to_comment = [
            'BROKER_API_KEY',
            'BROKER_API_SECRET', 
            'BROKER_API_KEY_MARKET',
            'BROKER_API_SECRET_MARKET'
        ]
        
        modified = False
        for i, line in enumerate(lines):
            for var in vars_to_comment:
                if line.strip().startswith(f'{var} =') and not line.strip().startswith('#'):
                    lines[i] = f'# MIGRATED TO DATABASE - {line}'
                    modified = True
                    break
        
        if modified:
            # Create backup
            backup_path = env_file_path + '.backup'
            with open(backup_path, 'w') as f:
                f.writelines(lines)
            
            # Write modified file
            with open(env_file_path, 'w') as f:
                f.writelines(lines)
            
            print(f"✅ .env file updated (backup saved as {backup_path})")
            return True
        else:
            print("No variables needed to be commented out")
            return True
            
    except Exception as e:
        logger.error(f"Failed to update .env file: {e}")
        return False

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Migrate broker configuration from .env to database')
    parser.add_argument('--force', action='store_true', help='Force migration without prompts')
    parser.add_argument('--validate-only', action='store_true', help='Only validate existing migration')
    parser.add_argument('--cleanup', action='store_true', help='Cleanup .env file after migration')
    
    args = parser.parse_args()
    
    if args.validate_only:
        print("Validating existing migration...")
        success = validate_migration()
        sys.exit(0 if success else 1)
    
    print("🔄 OpenAlgo Broker Configuration Migration")
    print("==========================================")
    print("This script will migrate your broker configuration from .env to the database.")
    print()
    
    # Run migration
    success = migrate_env_to_database(force=args.force)
    
    if success:
        print("\n🔍 Validating migration...")
        validate_migration()
        
        if args.cleanup:
            cleanup_env_file()
        
        print("\n🎉 Migration completed successfully!")
        print("\nNext steps:")
        print("1. Test your broker connection in the web interface")
        print("2. Configure additional brokers if needed")
        print("3. Remove old .env variables once you're confident everything works")
        
    else:
        print("\n❌ Migration failed!")
        sys.exit(1)