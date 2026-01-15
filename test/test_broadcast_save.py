import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.telegram_db import update_bot_config, get_bot_config

# Test saving with broadcast disabled
print("Testing broadcast_enabled field:")
print("1. Setting broadcast_enabled to False")
update_bot_config({'broadcast_enabled': False})

config = get_bot_config()
print(f"2. After save - broadcast_enabled: {config.get('broadcast_enabled')}")
print(f"   Type: {type(config.get('broadcast_enabled'))}")

# Try again with True
print("\n3. Setting broadcast_enabled to True")
update_bot_config({'broadcast_enabled': True})

config = get_bot_config()
print(f"4. After save - broadcast_enabled: {config.get('broadcast_enabled')}")
print(f"   Type: {type(config.get('broadcast_enabled'))}")