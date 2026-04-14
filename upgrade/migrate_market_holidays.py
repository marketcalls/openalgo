#!/usr/bin/env python3
"""
Migration: Update 2026 Market Holiday Calendar

Resets and re-seeds market holiday data with corrected 2026 dates
based on official NSE and MCX circulars.

Fixes:
- Holi: 2026-03-10 → 2026-03-03
- Ram Navami: 2026-04-02 → 2026-03-26
- Mahavir Jayanti: 2026-04-06 → 2026-03-31
- Bakri Id: 2026-05-27 → 2026-05-28
- Muharram: 2026-06-25 → 2026-06-26
- Dussehra: added 2026-10-20
- Diwali Balipratipada: 2026-10-21 → 2026-11-10
- Diwali Muhurat: 2026-10-20 → 2026-11-09
- Guru Nanak Dev: 2026-11-08 → 2026-11-24
- Added: Jan 15 (Municipal Corp Election), Sep 14 (Ganesh Chaturthi)
- Removed: incorrect entries (Id-Ul-Fitr, Holi Dhuleti, Milad-un-Nabi, etc.)
- Fixed MCX epoch timestamps (evening session 17:00-23:55 IST)

Usage:
    cd upgrade
    uv run migrate_market_holidays.py
"""

import os
import sys

# Add project root to path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

# Load environment
from dotenv import load_dotenv

load_dotenv(os.path.join(PROJECT_ROOT, ".env"))


def main():
    print("=" * 60)
    print("Migration: Update 2026 Market Holiday Calendar")
    print("=" * 60)

    try:
        from database.market_calendar_db import reset_holiday_data

        print("Resetting and re-seeding market holiday data...")
        result = reset_holiday_data()

        if result:
            print("[OK] 2026 market holidays updated successfully")
            print("     Holiday data now matches official NSE/MCX circulars")
        else:
            print("[!] Failed to reset holiday data - check logs")
            return 1

    except Exception as e:
        print(f"[X] Error during migration: {e}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
