#!/usr/bin/env python3
"""
Simple Cross-Platform SMTP Migration for OpenAlgo

This script adds SMTP configuration to the OpenAlgo database.
Works on Windows, Linux, and macOS with any database type.

Usage:
    python upgrade/migrate_smtp_simple.py
    python upgrade/migrate_smtp_simple.py --check-only
    python upgrade/migrate_smtp_simple.py --verbose
"""

import os
import sys
import argparse
import logging
import traceback
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Set up logging
def setup_logging(verbose=False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )
    return logging.getLogger(__name__)

def load_environment():
    """Load environment variables from .env file if it exists"""
    env_file = project_root / '.env'
    if env_file.exists():
        print(f"📋 Loading environment from: {env_file}")
        try:
            with open(env_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        # Clean up value - remove comments and quotes
                        value = value.split('#')[0].strip()  # Remove inline comments
                        value = value.strip('"\'')  # Remove quotes
                        os.environ[key] = value
            print("✅ Environment variables loaded")
        except Exception as e:
            print(f"⚠️  Warning: Could not load .env file: {e}")
    else:
        print("ℹ️  No .env file found")

def check_dependencies():
    """Check if required dependencies are available"""
    try:
        from database.settings_db import Settings, db_session, init_db
        return True
    except ImportError as e:
        print(f"❌ Missing dependencies: {e}")
        print("Please ensure you're running this from the OpenAlgo directory")
        return False

def add_smtp_columns():
    """Add SMTP columns to the settings table"""
    try:
        from database.settings_db import Settings, db_session, init_db
        from sqlalchemy import inspect, text
        
        print("🔧 Initializing database connection...")
        init_db()
        
        # Get database inspector
        inspector = inspect(db_session.bind)
        
        # Check if settings table exists
        if 'settings' not in inspector.get_table_names():
            print("❌ Settings table does not exist")
            return False
        
        # Get existing columns
        existing_columns = [col['name'] for col in inspector.get_columns('settings')]
        print(f"📋 Existing columns: {existing_columns}")
        
        # Define SMTP columns to add
        smtp_columns = {
            'smtp_server': 'VARCHAR(255)',
            'smtp_port': 'INTEGER', 
            'smtp_username': 'VARCHAR(255)',
            'smtp_password_encrypted': 'TEXT',
            'smtp_use_tls': 'BOOLEAN DEFAULT TRUE',
            'smtp_from_email': 'VARCHAR(255)',
            'smtp_helo_hostname': 'VARCHAR(255)'
        }
        
        # Find missing columns
        missing_columns = {name: dtype for name, dtype in smtp_columns.items() 
                          if name not in existing_columns}
        
        if not missing_columns:
            print("✅ All SMTP columns already exist - no migration needed")
            return True
        
        print(f"🔄 Adding {len(missing_columns)} missing columns...")
        
        # Add missing columns
        added = 0
        for column_name, column_type in missing_columns.items():
            try:
                # Use raw SQL for maximum compatibility
                sql = f"ALTER TABLE settings ADD COLUMN {column_name} {column_type}"
                print(f"  ➕ Adding: {column_name}")
                db_session.execute(text(sql))
                added += 1
            except Exception as e:
                print(f"  ⚠️  Warning adding {column_name}: {e}")
                # Continue with other columns
        
        if added > 0:
            db_session.commit()
            print(f"✅ Successfully added {added} SMTP columns")
        
        return True
        
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        if 'db_session' in locals():
            try:
                db_session.rollback()
            except:
                pass
        return False
    finally:
        if 'db_session' in locals():
            try:
                db_session.close()
            except:
                pass

def verify_smtp_columns():
    """Verify that SMTP columns exist"""
    try:
        from database.settings_db import Settings, db_session
        from sqlalchemy import inspect
        
        inspector = inspect(db_session.bind)
        existing_columns = [col['name'] for col in inspector.get_columns('settings')]
        
        expected_columns = [
            'smtp_server', 'smtp_port', 'smtp_username', 
            'smtp_password_encrypted', 'smtp_use_tls', 
            'smtp_from_email', 'smtp_helo_hostname'
        ]
        
        missing = [col for col in expected_columns if col not in existing_columns]
        
        if missing:
            print(f"❌ Missing columns: {missing}")
            return False
        else:
            print("✅ All SMTP columns verified successfully")
            return True
            
    except Exception as e:
        print(f"❌ Verification failed: {e}")
        return False

def main():
    parser = argparse.ArgumentParser(
        description='Simple cross-platform SMTP migration for OpenAlgo',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python upgrade/migrate_smtp_simple.py              # Run migration
  python upgrade/migrate_smtp_simple.py --check-only # Only check status
  python upgrade/migrate_smtp_simple.py --verbose    # Detailed output
        """
    )
    
    parser.add_argument('--check-only', action='store_true',
                       help='Only check if migration is needed, do not make changes')
    parser.add_argument('--verbose', '-v', action='store_true',
                       help='Enable verbose output')
    
    args = parser.parse_args()
    
    # Setup
    logger = setup_logging(args.verbose)
    
    print("🚀 OpenAlgo SMTP Migration")
    print("=" * 50)
    print(f"Python: {sys.version}")
    print(f"Platform: {sys.platform}")
    print(f"Working Directory: {os.getcwd()}")
    print(f"Project Root: {project_root}")
    print("")
    
    # Load environment
    load_environment()
    print("")
    
    # Check dependencies
    if not check_dependencies():
        return 1
    
    print("🔍 Checking database status...")
    
    # Verify current state
    if args.check_only:
        success = verify_smtp_columns()
        if success:
            print("ℹ️  Migration not needed - all columns exist")
            return 0
        else:
            print("⚠️  Migration needed - some columns missing")
            return 1
    
    # Run migration
    print("🔄 Running SMTP migration...")
    try:
        success = add_smtp_columns()
        
        if success:
            print("\n🔍 Verifying migration...")
            if verify_smtp_columns():
                print("\n🎉 SMTP migration completed successfully!")
                print("\nNext steps:")
                print("1. Restart your OpenAlgo application")
                print("2. Go to Profile → SMTP Configuration") 
                print("3. Configure your email settings")
                print("4. Test your configuration")
                print("\n📖 See docs/SMTP_SETUP.md for configuration instructions")
                return 0
            else:
                print("\n⚠️  Migration completed but verification failed")
                return 1
        else:
            print("\n❌ Migration failed!")
            return 1
            
    except KeyboardInterrupt:
        print("\n\n⏹️  Migration interrupted by user")
        return 1
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        if args.verbose:
            traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(main())