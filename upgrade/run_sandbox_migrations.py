#!/usr/bin/env python3
"""
Sandbox Migration Runner

Runs all sandbox-related migrations in the correct order.
Supports both upgrade and rollback operations.

Usage:
    python run_sandbox_migrations.py upgrade    # Apply all migrations
    python run_sandbox_migrations.py rollback   # Rollback all migrations
    python run_sandbox_migrations.py status     # Check migration status
"""

import sys
import os
import importlib.util
from pathlib import Path

# Configure logging
import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)


# List of migrations in order
MIGRATIONS = [
    {
        'id': '001',
        'name': 'create_sandbox_tables',
        'file': '001_create_sandbox_tables.py',
        'description': 'Initial sandbox database schema'
    },
    {
        'id': '002',
        'name': 'add_margin_blocked_field',
        'file': '002_add_margin_blocked_field.py',
        'description': 'Add margin_blocked field to track exact margin per order'
    },
    {
        'id': '003',
        'name': 'sandbox_complete_setup',
        'file': '003_sandbox_complete_setup.py',
        'description': 'Ensure complete sandbox setup with all tables and fields'
    }
]


def load_migration(migration_file):
    """Dynamically load a migration module"""
    file_path = Path(__file__).parent / migration_file

    if not file_path.exists():
        logger.warning(f"Migration file not found: {migration_file}")
        return None

    spec = importlib.util.spec_from_file_location(migration_file[:-3], file_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    return module


def run_upgrade():
    """Run all migrations in order"""
    logger.info("=" * 60)
    logger.info("RUNNING SANDBOX MIGRATIONS - UPGRADE")
    logger.info("=" * 60)

    success_count = 0
    failed_count = 0

    for migration in MIGRATIONS:
        logger.info(f"\n📦 Migration {migration['id']}: {migration['name']}")
        logger.info(f"   {migration['description']}")

        module = load_migration(migration['file'])

        if module is None:
            logger.error(f"   ❌ Could not load migration file")
            failed_count += 1
            continue

        # Check if migration has upgrade function
        if not hasattr(module, 'upgrade'):
            logger.warning(f"   ⚠️  No upgrade function found - skipping")
            continue

        try:
            # Check status first if available
            if hasattr(module, 'status'):
                if module.status():
                    logger.info(f"   ✅ Already applied - skipping")
                    success_count += 1
                    continue

            # Run upgrade
            result = module.upgrade()

            if result:
                logger.info(f"   ✅ Migration applied successfully")
                success_count += 1
            else:
                logger.error(f"   ❌ Migration failed")
                failed_count += 1

        except Exception as e:
            logger.error(f"   ❌ Error running migration: {e}")
            failed_count += 1

    logger.info("\n" + "=" * 60)
    logger.info(f"MIGRATION SUMMARY: {success_count} succeeded, {failed_count} failed")
    logger.info("=" * 60)

    return failed_count == 0


def run_rollback():
    """Run rollback for all migrations in reverse order"""
    logger.info("=" * 60)
    logger.info("RUNNING SANDBOX MIGRATIONS - ROLLBACK")
    logger.info("=" * 60)

    success_count = 0
    failed_count = 0

    # Process migrations in reverse order
    for migration in reversed(MIGRATIONS):
        logger.info(f"\n📦 Migration {migration['id']}: {migration['name']}")
        logger.info(f"   Rolling back: {migration['description']}")

        module = load_migration(migration['file'])

        if module is None:
            logger.error(f"   ❌ Could not load migration file")
            failed_count += 1
            continue

        # Check if migration has rollback function
        if not hasattr(module, 'rollback'):
            logger.warning(f"   ⚠️  No rollback function found - skipping")
            continue

        try:
            # Check status first if available
            if hasattr(module, 'status'):
                if not module.status():
                    logger.info(f"   ✅ Not applied - skipping rollback")
                    success_count += 1
                    continue

            # Run rollback
            result = module.rollback()

            if result:
                logger.info(f"   ✅ Rollback successful")
                success_count += 1
            else:
                logger.error(f"   ❌ Rollback failed")
                failed_count += 1

        except Exception as e:
            logger.error(f"   ❌ Error running rollback: {e}")
            failed_count += 1

    logger.info("\n" + "=" * 60)
    logger.info(f"ROLLBACK SUMMARY: {success_count} succeeded, {failed_count} failed")
    logger.info("=" * 60)

    return failed_count == 0


def check_status():
    """Check status of all migrations"""
    logger.info("=" * 60)
    logger.info("SANDBOX MIGRATION STATUS")
    logger.info("=" * 60)

    for migration in MIGRATIONS:
        module = load_migration(migration['file'])

        status = "❓ Unknown"

        if module is None:
            status = "❌ File not found"
        elif hasattr(module, 'status'):
            try:
                is_applied = module.status()
                status = "✅ Applied" if is_applied else "⚠️  Not applied"
            except Exception as e:
                status = f"❌ Error: {e}"
        else:
            status = "❓ No status check"

        logger.info(f"\nMigration {migration['id']}: {migration['name']}")
        logger.info(f"  Status: {status}")
        logger.info(f"  File: {migration['file']}")
        logger.info(f"  Description: {migration['description']}")

    logger.info("\n" + "=" * 60)


def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(
        description='Run sandbox database migrations',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_sandbox_migrations.py upgrade    # Apply all migrations
  python run_sandbox_migrations.py rollback   # Rollback all migrations
  python run_sandbox_migrations.py status     # Check migration status
        """
    )

    parser.add_argument(
        'command',
        choices=['upgrade', 'rollback', 'status'],
        help='Command to execute'
    )

    parser.add_argument(
        '--force',
        action='store_true',
        help='Force operation even if some migrations fail'
    )

    args = parser.parse_args()

    if args.command == 'upgrade':
        success = run_upgrade()
        sys.exit(0 if success or args.force else 1)

    elif args.command == 'rollback':
        success = run_rollback()
        sys.exit(0 if success or args.force else 1)

    elif args.command == 'status':
        check_status()
        sys.exit(0)


if __name__ == '__main__':
    main()