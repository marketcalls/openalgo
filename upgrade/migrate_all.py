#!/usr/bin/env python3
"""
OpenAlgo Master Migration Script

This script runs ALL migrations in the correct order.
Each migration is idempotent - it skips if already applied.

Usage:
    cd upgrade
    uv run migrate_all.py

    # Or from project root:
    uv run upgrade/migrate_all.py

Works for:
- Fresh installations (runs all migrations)
- Existing users on any version (skips already applied migrations)
"""

import os
import sys
import subprocess
import time

# Set UTF-8 encoding for output to handle Unicode characters on Windows
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Get the upgrade directory path
UPGRADE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(UPGRADE_DIR)

# Migration scripts in order of execution
# Each migration is idempotent - safe to run multiple times
MIGRATIONS = [
    # Legacy migrations (for users upgrading from older versions)
    ('add_feed_token.py', 'Feed Token Support'),
    ('add_user_id.py', 'User ID Column'),

    # Core feature migrations
    ('migrate_telegram_bot.py', 'Telegram Bot Integration'),
    ('migrate_smtp_simple.py', 'SMTP Configuration'),
    ('migrate_security_columns.py', 'Security Columns'),
    ('migrate_sandbox.py', 'Sandbox Mode'),
    ('migrate_order_mode.py', 'Order Mode & Action Center'),

    # Performance migrations
    ('migrate_indexes.py', 'Database Performance Indexes'),
]

def run_migration(script_name, description):
    """Run a single migration script"""
    script_path = os.path.join(UPGRADE_DIR, script_name)

    # Check if script exists
    if not os.path.exists(script_path):
        print(f"  [SKIP] {script_name} - Script not found")
        return True  # Not an error, might be removed in future

    print(f"\n{'='*60}")
    print(f"Running: {description}")
    print(f"Script: {script_name}")
    print('='*60)

    try:
        # Run the migration script
        result = subprocess.run(
            [sys.executable, script_path],
            cwd=PROJECT_ROOT,
            capture_output=False,
            text=True
        )

        if result.returncode == 0:
            print(f"[OK] {description} - Completed")
            return True
        else:
            print(f"[!] {description} - Completed with warnings")
            return True  # Continue even with warnings

    except Exception as e:
        print(f"[X] {description} - Error: {e}")
        return False

def main():
    """Run all migrations"""
    print()
    print('#' * 60)
    print('#' + ' ' * 58 + '#')
    print('#' + '       OpenAlgo Master Migration Script'.center(58) + '#')
    print('#' + ' ' * 58 + '#')
    print('#' * 60)
    print()
    print("This script will run all migrations in order.")
    print("Already applied migrations will be automatically skipped.")
    print()

    start_time = time.time()
    success_count = 0
    fail_count = 0

    for script_name, description in MIGRATIONS:
        if run_migration(script_name, description):
            success_count += 1
        else:
            fail_count += 1

    elapsed = time.time() - start_time

    # Summary
    print()
    print('#' * 60)
    print('#' + ' ' * 58 + '#')
    print('#' + '              Migration Summary'.center(58) + '#')
    print('#' + ' ' * 58 + '#')
    print('#' * 60)
    print()
    print(f"  Total migrations: {len(MIGRATIONS)}")
    print(f"  Successful: {success_count}")
    print(f"  Failed: {fail_count}")
    print(f"  Time elapsed: {elapsed:.1f} seconds")
    print()

    if fail_count == 0:
        print("[OK] All migrations completed successfully!")
        print()
        print("Next steps:")
        print("  cd ..")
        print("  uv run app.py")
        print()
        return 0
    else:
        print("[!] Some migrations had issues. Check the output above.")
        print()
        return 1

if __name__ == "__main__":
    sys.exit(main())
