"""
Test script to verify Telegram bot chart generation
"""
import asyncio
import sys
import os
# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.telegram_bot_service import telegram_bot_service
from database.telegram_db import get_telegram_user, create_or_update_telegram_user
from datetime import datetime

async def test_chart_generation():
    """Test chart generation directly"""
    # Mock telegram user ID
    telegram_id = 123456789

    # First ensure we have a test user linked
    test_user = get_telegram_user(telegram_id)
    if not test_user:
        # Add a test user with API key
        create_or_update_telegram_user(
            telegram_id=telegram_id,
            username="test_user",
            # Use the API key from environment or a test key
            api_key=os.getenv('TEST_API_KEY', '56c3dc6ba7d9c9df478e4f19ffc5d3e15e1dd91b5aa11e91c910f202c91eff9d')
        )

    print("Testing chart generation...")

    # Test intraday chart
    print("\n1. Testing intraday chart (5m interval, 5 days)...")
    intraday_chart = await telegram_bot_service._generate_intraday_chart(
        symbol="RELIANCE",
        exchange="NSE",
        interval="5m",
        days=5,
        telegram_id=telegram_id
    )

    if intraday_chart:
        print(f"   [OK] Intraday chart generated successfully ({len(intraday_chart)} bytes)")
        # Save to file for inspection
        with open("test_intraday_chart.png", "wb") as f:
            f.write(intraday_chart)
        print("   [OK] Saved to test_intraday_chart.png")
    else:
        print("   [FAIL] Failed to generate intraday chart")

    # Test daily chart
    print("\n2. Testing daily chart (D interval, 30 days)...")
    daily_chart = await telegram_bot_service._generate_daily_chart(
        symbol="RELIANCE",
        exchange="NSE",
        interval="D",
        days=30,
        telegram_id=telegram_id
    )

    if daily_chart:
        print(f"   [OK] Daily chart generated successfully ({len(daily_chart)} bytes)")
        # Save to file for inspection
        with open("test_daily_chart.png", "wb") as f:
            f.write(daily_chart)
        print("   [OK] Saved to test_daily_chart.png")
    else:
        print("   [FAIL] Failed to generate daily chart")

    print("\n[OK] Chart generation test completed!")

if __name__ == "__main__":
    asyncio.run(test_chart_generation())