"""
Test script to verify Telegram bot configuration saving and loading
"""
import sys
import os
# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.telegram_db import get_bot_config, update_bot_config

def test_config():
    """Test configuration save and load"""
    print("Testing Telegram Bot Configuration")
    print("=" * 50)

    # Get current config
    print("\n1. Current Configuration:")
    config = get_bot_config()
    for key, value in config.items():
        if key in ['bot_token', 'token']:
            if value:
                print(f"   {key}: {value[:10]}..." if value else f"   {key}: None")
            else:
                print(f"   {key}: None")
        else:
            print(f"   {key}: {value}")

    # Test saving configuration
    print("\n2. Testing Save Configuration:")
    test_config = {
        'bot_token': 'test_token_123456789',
        'broadcast_enabled': True,
        'rate_limit_per_minute': 60
    }

    success = update_bot_config(test_config)
    print(f"   Save result: {'Success' if success else 'Failed'}")

    # Verify saved configuration
    print("\n3. Configuration After Save:")
    config = get_bot_config()
    for key, value in config.items():
        if key in ['bot_token', 'token']:
            if value:
                print(f"   {key}: {value[:10]}..." if value else f"   {key}: None")
            else:
                print(f"   {key}: None")
        else:
            print(f"   {key}: {value}")

    # Check specific fields
    print("\n4. Verification:")
    print(f"   Token saved correctly: {config.get('bot_token', '').startswith('test_token')}")
    print(f"   Broadcast enabled: {config.get('broadcast_enabled')}")
    print(f"   Rate limit: {config.get('rate_limit_per_minute')}")

if __name__ == "__main__":
    test_config()