#!/usr/bin/env python3
"""
Test script to verify bot starts properly from web UI
"""
import time
from services.telegram_bot_service import init_bot_sync, start_bot_sync, stop_bot_sync, get_telegram_bot
from database.telegram_db import get_bot_config

# Get config
config = get_bot_config()

if not config.get('token'):
    print("[ERROR] No bot token configured")
    exit(1)

print(f"[INFO] Bot token found: {config['token'][:10]}...")

# Initialize bot
print("[INFO] Initializing bot...")
success, message = init_bot_sync(config['token'], None)

if not success:
    print(f"[ERROR] Failed to initialize: {message}")
    exit(1)

print(f"[OK] {message}")

# Start bot
print("[INFO] Starting bot in polling mode...")
success, message = start_bot_sync()

if not success:
    print(f"[ERROR] Failed to start: {message}")
    exit(1)

print(f"[OK] {message}")

# Check status
bot = get_telegram_bot()
print(f"[STATUS] Bot running: {bot.is_running}")

# Keep running for testing
print("[INFO] Bot is running. Press Ctrl+C to stop.")
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    print("\n[INFO] Stopping bot...")
    success, message = stop_bot_sync()
    print(f"[OK] {message}")