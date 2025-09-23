#!/usr/bin/env python3
"""
Test script to verify Telegram bot functionality
"""
import asyncio
import logging
import sys
import os
# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.telegram_db import get_bot_config
from services.telegram_bot_service import TelegramBotService

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

async def test_bot():
    """Test the bot initialization and start"""
    bot_service = TelegramBotService()

    # Get bot config from database
    config = get_bot_config()

    if not config.get('token'):
        print("[ERROR] No bot token configured. Please configure the bot token first.")
        return

    print(f"[OK] Bot token found: {config['token'][:10] if config.get('token') else 'None'}...")

    # Initialize bot
    success, message = await bot_service.initialize_bot(config['token'])
    if success:
        print(f"[OK] Bot initialized: {message}")

        # Try to get bot info
        if bot_service.bot:
            bot_info = await bot_service.bot.get_me()
            print(f"[OK] Bot username: @{bot_info.username}")
            print(f"[OK] Bot name: {bot_info.first_name}")
    else:
        print(f"[ERROR] Failed to initialize bot: {message}")
        return

    # Start polling
    print("Starting bot polling...")
    success, message = await bot_service.start_polling()
    if success:
        print(f"[OK] {message}")
        print("Bot is now running. Press Ctrl+C to stop.")

        # Keep the bot running
        try:
            while bot_service.is_running:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            print("\nStopping bot...")
            await bot_service.stop_bot()
            print("Bot stopped.")
    else:
        print(f"[ERROR] Failed to start polling: {message}")

if __name__ == "__main__":
    asyncio.run(test_bot())