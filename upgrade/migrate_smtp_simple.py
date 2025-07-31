#!/usr/bin/env python3
"""
Universal SMTP Migration for OpenAlgo - With Automatic Path Resolution

This script adds SMTP configuration columns to the OpenAlgo database.
Automatically resolves database paths regardless of where it's run from.

Usage (run from anywhere):
    python upgrade/migrate_smtp_universal_path.py
    python ./migrate_smtp_universal_path.py
    uv run migrate_smtp_universal_path.py
"""

import os
import sys
import argparse
import logging
import traceback
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(project_root))

# Universal UTF-8 encoding setup
def setup_unicode_output():
    """Configure proper Unicode output for all platforms"""
    if sys.platform == 'win32':
        # Windows-specific UTF-8 setup
        import io
        if hasattr(sys.stdout, 'buffer'):
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
            sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
    else:
        # Unix-like systems (Linux, macOS)
        import locale
        if locale.getpreferredencoding().upper() != 'UTF-8':
            os.environ['PYTHONIOENCODING'] = 'utf-8'

# Apply Unicode setup
setup_unicode_output()

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

def safe_print(message, use_emoji=True):
    """Print with fallback for systems that don't support emojis"""
    if use_emoji:
        try:
            print(message)
        except (UnicodeEncodeError, UnicodeDecodeError):
            # Fallback: print without emojis
            message_no_emoji = message
            emoji_map = {
                '🚀': '[START]',
                '📋': '[INFO]',
                '✅': '[OK]',
                '❌': '[ERROR]',
                '⚠️': '[WARN]',
                'ℹ️': '[INFO]',
                '🔍': '[CHECK]',
                '🔄': '[RUN]',
                '🔧': '[SETUP]',
                '➕': '+',
                '🎉': '[SUCCESS]',
                '📖': '[DOCS]',
                '⏹️': '[STOP]',
                '📁': '[DIR]'
            }
            for emoji, text in emoji_map.items():
                message_no_emoji = message_no_emoji.replace(emoji, text)
            print(message_no_emoji)
    else:
        print(message)

def resolve_database_path(db_url):
    """Resolve relative SQLite database paths to absolute paths"""
    if db_url.startswith('sqlite:///'):
        # Extract the relative path
        rel_path = db_url[10:]  # Remove 'sqlite:///'
        
        # Convert to absolute path relative to project root
        abs_path = project_root / rel_path
        
        # Ensure parent directory exists
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Return the absolute SQLite URL
        return f'sqlite:///{abs_path.as_posix()}'
    
    return db_url

def load_environment():
    """Load environment variables from .env file if it exists"""
    env_file = project_root / '.env'
    if env_file.exists():
        safe_print(f"📋 Loading environment from: {env_file}")
        try:
            with open(env_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        # Find the first equals sign
                        eq_index = line.find('=')
                        if eq_index > 0:
                            key = line[:eq_index].strip()
                            value = line[eq_index + 1:].strip()
                            
                            # Remove inline comments (but preserve # in URLs)
                            if '#' in value and not ('http' in value or 'https' in value):
                                comment_index = value.find('#')
                                value = value[:comment_index].strip()
                            
                            # Remove surrounding quotes
                            if (value.startswith('"') and value.endswith('"')) or \
                               (value.startswith("'") and value.endswith("'")):
                                value = value[1:-1]
                            
                            # Resolve database paths
                            if key == 'DATABASE_URL' and value.startswith('sqlite:///'):
                                original_value = value
                                value = resolve_database_path(value)
                                safe_print(f"📁 Resolved database path: {original_value} → {value}")
                            
                            os.environ[key] = value
                                
            safe_print("✅ Environment variables loaded")
        except Exception as e:
            safe_print(f"⚠️  Warning: Could not load .env file: {e}")
    else:
        safe_print("ℹ️  No .env file found")

def check_dependencies():
    """Check if required dependencies are available"""
    try:
        # Only import what we need for raw database operations
        from sqlalchemy import create_engine, inspect, text
        return True
    except ImportError as e:
        safe_print(f"❌ Missing dependencies: {e}")
        safe_print("Please ensure SQLAlchemy is installed")
        return False

def add_smtp_columns():
    """Add SMTP columns to the settings table using raw SQL"""
    try:
        from sqlalchemy import create_engine, inspect, text, MetaData
        
        # Get database URL from environment
        database_url = os.getenv('DATABASE_URL')
        if not database_url:
            safe_print("❌ DATABASE_URL not found in environment")
            safe_print("Current environment variables:")
            for key in sorted(os.environ.keys()):
                if 'DATABASE' in key or 'DB' in key:
                    safe_print(f"  {key}: {os.environ[key]}")
            return False
        
        safe_print(f"🔧 Creating database connection...")
        safe_print(f"📁 Database URL: {database_url}")
        
        # Check if database file exists (for SQLite)
        if database_url.startswith('sqlite:///'):
            db_path = database_url[10:]
            if not Path(db_path).exists():
                safe_print(f"📁 Database file doesn't exist, will be created: {db_path}")
        
        engine = create_engine(database_url)
        
        # Get database inspector
        inspector = inspect(engine)
        
        # Check if settings table exists
        if 'settings' not in inspector.get_table_names():
            safe_print("❌ Settings table does not exist. Creating it...")
            # Create minimal settings table
            with engine.connect() as conn:
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS settings (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        analyze_mode BOOLEAN DEFAULT 0
                    )
                """))
                conn.commit()
                safe_print("✅ Created settings table")
        
        # Get existing columns
        existing_columns = [col['name'] for col in inspector.get_columns('settings')]
        safe_print(f"📋 Existing columns: {existing_columns}")
        
        # Define SMTP columns to add
        smtp_columns = {
            'smtp_server': 'VARCHAR(255)',
            'smtp_port': 'INTEGER', 
            'smtp_username': 'VARCHAR(255)',
            'smtp_password_encrypted': 'TEXT',
            'smtp_use_tls': 'BOOLEAN DEFAULT 1',  # SQLite uses 1 for TRUE
            'smtp_from_email': 'VARCHAR(255)',
            'smtp_helo_hostname': 'VARCHAR(255)'
        }
        
        # Find missing columns
        missing_columns = {name: dtype for name, dtype in smtp_columns.items() 
                          if name not in existing_columns}
        
        if not missing_columns:
            safe_print("✅ All SMTP columns already exist - no migration needed")
            return True
        
        safe_print(f"🔄 Adding {len(missing_columns)} missing columns...")
        
        # Add missing columns
        added = 0
        with engine.connect() as conn:
            for column_name, column_type in missing_columns.items():
                try:
                    # Use raw SQL for maximum compatibility
                    sql = f"ALTER TABLE settings ADD COLUMN {column_name} {column_type}"
                    safe_print(f"  ➕ Adding: {column_name}")
                    conn.execute(text(sql))
                    added += 1
                except Exception as e:
                    safe_print(f"  ⚠️  Warning adding {column_name}: {e}")
                    # Continue with other columns
            
            if added > 0:
                conn.commit()
                safe_print(f"✅ Successfully added {added} SMTP columns")
        
        # Ensure at least one settings row exists
        with engine.connect() as conn:
            result = conn.execute(text("SELECT COUNT(*) FROM settings"))
            count = result.scalar()
            if count == 0:
                safe_print("📋 Creating default settings row...")
                conn.execute(text("INSERT INTO settings (analyze_mode) VALUES (0)"))
                conn.commit()
                safe_print("✅ Created default settings row")
        
        return True
        
    except Exception as e:
        safe_print(f"❌ Migration failed: {e}")
        if hasattr(e, '__traceback__'):
            traceback.print_exc()
        return False

def verify_smtp_columns():
    """Verify that SMTP columns exist using raw SQL"""
    try:
        from sqlalchemy import create_engine, inspect
        
        # Get database URL from environment
        database_url = os.getenv('DATABASE_URL')
        if not database_url:
            safe_print("❌ DATABASE_URL not found in environment")
            return False
        
        engine = create_engine(database_url)
        inspector = inspect(engine)
        
        if 'settings' not in inspector.get_table_names():
            safe_print("❌ Settings table does not exist")
            return False
        
        existing_columns = [col['name'] for col in inspector.get_columns('settings')]
        
        expected_columns = [
            'smtp_server', 'smtp_port', 'smtp_username', 
            'smtp_password_encrypted', 'smtp_use_tls', 
            'smtp_from_email', 'smtp_helo_hostname'
        ]
        
        missing = [col for col in expected_columns if col not in existing_columns]
        
        if missing:
            safe_print(f"❌ Missing columns: {missing}")
            return False
        else:
            safe_print("✅ All SMTP columns verified successfully")
            return True
            
    except Exception as e:
        safe_print(f"❌ Verification failed: {e}")
        return False

def main():
    parser = argparse.ArgumentParser(
        description='Universal SMTP migration with automatic path resolution',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python upgrade/migrate_smtp_universal_path.py     # Run from project root
  python ./migrate_smtp_universal_path.py           # Run from upgrade directory
  uv run migrate_smtp_universal_path.py --verbose   # Run with uv from anywhere
        """
    )
    
    parser.add_argument('--check-only', action='store_true',
                       help='Only check if migration is needed, do not make changes')
    parser.add_argument('--verbose', '-v', action='store_true',
                       help='Enable verbose output')
    parser.add_argument('--no-emoji', action='store_true',
                       help='Disable emoji output (useful for older terminals)')
    
    args = parser.parse_args()
    
    # Setup
    logger = setup_logging(args.verbose)
    use_emoji = not args.no_emoji
    
    safe_print("🚀 OpenAlgo SMTP Migration (Universal Path Version)", use_emoji)
    safe_print("=" * 50, False)
    safe_print(f"Python: {sys.version}", False)
    safe_print(f"Platform: {sys.platform}", False)
    safe_print(f"Working Directory: {os.getcwd()}", False)
    safe_print(f"Project Root: {project_root}", False)
    safe_print("", False)
    
    # Load environment
    load_environment()
    safe_print("", False)
    
    # Check dependencies
    if not check_dependencies():
        return 1
    
    safe_print("🔍 Checking database status...", use_emoji)
    
    # Verify current state
    if args.check_only:
        success = verify_smtp_columns()
        if success:
            safe_print("ℹ️  Migration not needed - all columns exist", use_emoji)
            return 0
        else:
            safe_print("⚠️  Migration needed - some columns missing", use_emoji)
            return 1
    
    # Run migration
    safe_print("🔄 Running SMTP migration...", use_emoji)
    try:
        success = add_smtp_columns()
        
        if success:
            safe_print("\n🔍 Verifying migration...", use_emoji)
            if verify_smtp_columns():
                safe_print("\n🎉 SMTP migration completed successfully!", use_emoji)
                safe_print("\nNext steps:", False)
                safe_print("1. Restart your OpenAlgo application", False)
                safe_print("2. Go to Profile → SMTP Configuration", False) 
                safe_print("3. Configure your email settings", False)
                safe_print("4. Test your configuration", False)
                safe_print("\n📖 See docs/SMTP_SETUP.md for configuration instructions", use_emoji)
                return 0
            else:
                safe_print("\n⚠️  Migration completed but verification failed", use_emoji)
                return 1
        else:
            safe_print("\n❌ Migration failed!", use_emoji)
            return 1
            
    except KeyboardInterrupt:
        safe_print("\n\n⏹️  Migration interrupted by user", use_emoji)
        return 1
    except Exception as e:
        safe_print(f"\n❌ Unexpected error: {e}", use_emoji)
        if args.verbose:
            traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(main())