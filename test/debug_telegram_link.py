"""
Debug script to check Telegram user linkage
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.telegram_db import get_all_telegram_users, get_telegram_user_by_username, get_bot_config
from database.auth_db import get_username_by_apikey, verify_api_key
from utils.logging import get_logger

logger = get_logger(__name__)

def debug_telegram_users():
    """Check telegram user configuration"""

    print("\n" + "="*60)
    print("TELEGRAM USER DEBUGGING")
    print("="*60)

    # Check bot configuration
    print("\n1. Bot Configuration:")
    print("-" * 40)
    bot_config = get_bot_config()
    print(f"   Bot Token Configured: {bool(bot_config.get('bot_token'))}")
    print(f"   Bot Username: {bot_config.get('bot_username', 'Not set')}")
    print(f"   Broadcast Enabled: {bot_config.get('broadcast_enabled', False)}")
    print(f"   Bot Active: {bot_config.get('is_active', False)}")

    # List all telegram users
    print("\n2. Linked Telegram Users:")
    print("-" * 40)
    users = get_all_telegram_users()
    if users:
        for user in users:
            print(f"\n   User #{user.get('id')}:")
            print(f"   - OpenAlgo Username: {user.get('openalgo_username', 'N/A')}")
            print(f"   - Telegram ID: {user.get('telegram_id', 'N/A')}")
            print(f"   - Telegram Username: @{user.get('telegram_username', 'N/A')}")
            print(f"   - Name: {user.get('first_name', '')} {user.get('last_name', '')}")
            print(f"   - Notifications Enabled: {user.get('notifications_enabled', False)}")
            print(f"   - Created: {user.get('created_at', 'N/A')}")
    else:
        print("   No users linked to Telegram bot")

    # Test API key to username resolution
    print("\n3. Test Username Matching:")
    print("-" * 40)

    # Check for username format issues
    print("   Checking for username format mismatches...")

    # Get all auth users (this would require access to auth database)
    from database.auth_db import Auth, db_session

    try:
        # Get all auth usernames
        auth_users = db_session.query(Auth.name).all()
        auth_usernames = [u[0] for u in auth_users if u[0]]

        print(f"   Auth system users: {auth_usernames}")

        # Check if telegram users match
        for tg_user in users:
            tg_username = tg_user.get('openalgo_username', '')
            # Remove @ if present for comparison
            clean_tg_username = tg_username.replace('@', '')

            # Check various formats
            matches = []
            for auth_user in auth_usernames:
                if auth_user == tg_username or auth_user == clean_tg_username:
                    matches.append(auth_user)

            if matches:
                print(f"   [OK] Telegram user '{tg_username}' matches auth user: {matches}")
            else:
                print(f"   [ERROR] Telegram user '{tg_username}' has NO matching auth user!")
                print(f"      This user won't receive alerts!")

    except Exception as e:
        print(f"   Error checking auth users: {e}")

    # Skip interactive input in automated run
    test_api_key = ""

    if test_api_key:
        # Test verification
        user_id = verify_api_key(test_api_key)
        if user_id:
            print(f"   [OK] API key valid for user: {user_id}")

            # Test getting username
            username = get_username_by_apikey(test_api_key)
            print(f"   [OK] Username resolved: {username}")

            # Check if this user has telegram linked
            telegram_user = get_telegram_user_by_username(username)
            if telegram_user:
                print(f"   [OK] Telegram linked:")
                print(f"     - Telegram ID: {telegram_user['telegram_id']}")
                print(f"     - Notifications: {telegram_user.get('notifications_enabled', False)}")
            else:
                print(f"   [X] No Telegram account linked for user: {username}")
        else:
            print("   [X] Invalid API key")

    # Check for common issues
    print("\n4. Common Issues Check:")
    print("-" * 40)

    issues = []

    if not bot_config.get('bot_token'):
        issues.append("Bot token not configured")

    if not bot_config.get('is_active'):
        issues.append("Bot is not active")

    if not users:
        issues.append("No users linked to Telegram")
    else:
        # Check for users without notifications
        disabled_users = [u for u in users if not u.get('notifications_enabled')]
        if disabled_users:
            issues.append(f"{len(disabled_users)} users have notifications disabled")

    if issues:
        print("   Issues found:")
        for issue in issues:
            print(f"   [X] {issue}")
    else:
        print("   [OK] No issues found - system should be working")

    print("\n5. Troubleshooting Steps:")
    print("-" * 40)
    print("   1. Ensure Telegram bot is running: /telegram/bot/start")
    print("   2. Users must link account in Telegram: /link <api_key> <host>")
    print("   3. Check notifications are enabled in user preferences")
    print("   4. Verify bot token is correct in /telegram/config")
    print("   5. Check logs for 'Telegram alert' messages")

    print("\n" + "="*60)

if __name__ == "__main__":
    debug_telegram_users()