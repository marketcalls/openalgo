#!/usr/bin/env python
"""
Fix Script: Add accumulated_realized_pnl column to sandbox_positions table

This script adds the missing accumulated_realized_pnl column to existing
sandbox_positions tables that were created before this column was added.

Usage:
    python fix_accumulated_pnl_column.py

This script is safe to run multiple times - it will skip if column already exists.
"""

import sys
import os
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import create_engine, text
from dotenv import load_dotenv

# Load environment
load_dotenv('.env')

def get_sandbox_db_engine():
    """Get sandbox database engine"""
    sandbox_db_url = os.getenv('SANDBOX_DATABASE_URL', 'sqlite:///db/sandbox.db')

    # Extract path from URL and make absolute
    if sandbox_db_url.startswith('sqlite:///'):
        db_path = sandbox_db_url.replace('sqlite:///', '')

        if not os.path.isabs(db_path):
            db_path = os.path.join(os.path.dirname(__file__), db_path)

        # Create directory if it doesn't exist
        os.makedirs(os.path.dirname(db_path), exist_ok=True)

        sandbox_db_url = f"sqlite:///{db_path}"
        print(f"📂 Sandbox DB path: {db_path}")

    return create_engine(sandbox_db_url)

def fix_accumulated_pnl_column():
    """Add accumulated_realized_pnl column if missing"""
    try:
        print("\n" + "="*60)
        print("FIX: Adding accumulated_realized_pnl Column")
        print("="*60 + "\n")

        engine = get_sandbox_db_engine()

        with engine.connect() as conn:
            # Check if sandbox_positions table exists
            result = conn.execute(text("""
                SELECT name FROM sqlite_master
                WHERE type='table' AND name='sandbox_positions'
            """))

            if not result.fetchone():
                print("❌ Error: sandbox_positions table does not exist")
                print("   Please run the main migration first")
                return False

            # Check if column already exists
            result = conn.execute(text("PRAGMA table_info(sandbox_positions)"))
            columns = [row[1] for row in result]

            if 'accumulated_realized_pnl' in columns:
                print("✅ Column accumulated_realized_pnl already exists")
                print("   No action needed")
                return True

            # Add the missing column
            print("🔧 Adding accumulated_realized_pnl column...")
            conn.execute(text("""
                ALTER TABLE sandbox_positions
                ADD COLUMN accumulated_realized_pnl DECIMAL(10,2) DEFAULT 0.00
            """))
            conn.commit()

            print("✅ Successfully added accumulated_realized_pnl column")

            # Verify the column was added
            result = conn.execute(text("PRAGMA table_info(sandbox_positions)"))
            columns = [row[1] for row in result]

            if 'accumulated_realized_pnl' in columns:
                print("✅ Verification successful - column exists")

                # Show current positions
                result = conn.execute(text("""
                    SELECT COUNT(*) FROM sandbox_positions WHERE quantity != 0
                """))
                open_positions = result.fetchone()[0]
                print(f"📊 Current open positions: {open_positions}")

                return True
            else:
                print("❌ Verification failed - column not found after adding")
                return False

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == '__main__':
    print("\n🔧 OpenAlgo Sandbox Fix Script")
    print("=" * 60)

    success = fix_accumulated_pnl_column()

    print("\n" + "="*60)
    if success:
        print("✅ Fix completed successfully!")
        print("\nYou can now:")
        print("1. Restart your OpenAlgo application")
        print("2. Try placing orders in analyzer mode")
    else:
        print("❌ Fix failed - please check the errors above")
    print("="*60 + "\n")

    sys.exit(0 if success else 1)
