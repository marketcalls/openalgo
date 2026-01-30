#!/usr/bin/env python3
"""
Script to update all database/*.py files to use StaticPool instead of NullPool
This prevents file descriptor exhaustion
"""

import os
import re
from pathlib import Path

# Database files to update
DB_FILES = [
    "database/traffic_db.py",
    "database/auth_db.py",
    "database/settings_db.py",
    "database/strategy_db.py",
    "database/strategy_state_db.py",
    "database/action_center_db.py",
    "database/analyzer_db.py",
    "database/apilog_db.py",
    "database/chart_prefs_db.py",
    "database/chartink_db.py",
    "database/flow_db.py",
    "database/latency_db.py",
    "database/market_calendar_db.py",
    "database/master_contract_status_db.py",
    "database/qty_freeze_db.py",
    "database/sandbox_db.py",
    "database/symbol.py",
    "database/telegram_db.py",
    "database/user_db.py",
]

def update_file(file_path):
    """Update a single database file"""
    print(f"Processing {file_path}...")
    
    try:
        with open(file_path, 'r') as f:
            content = f.read()
        
        original_content = content
        modified = False
        
        # 1. Replace NullPool import with StaticPool
        if 'from sqlalchemy.pool import NullPool' in content:
            content = content.replace(
                'from sqlalchemy.pool import NullPool',
                'from sqlalchemy.pool import StaticPool'
            )
            modified = True
        
        # 2. Update SQLite engine creation with NullPool -> StaticPool
        # Pattern: poolclass=NullPool, connect_args={"check_same_thread": False}
        nullpool_pattern = r'poolclass=NullPool,\s*connect_args=\{"check_same_thread":\s*False\}'
        
        if re.search(nullpool_pattern, content):
            replacement = '''poolclass=StaticPool,
        connect_args={
            "check_same_thread": False,
            "timeout": 20.0,
        },
        pool_pre_ping=True'''
            
            new_content = re.sub(nullpool_pattern, replacement, content)
            
            # Verify the replacement was successful
            if 'poolclass=StaticPool' in new_content and 'poolclass=NullPool' not in new_content:
                content = new_content
                modified = True
            else:
                print(f"  ⚠ Warning: SQLite pool replacement may have failed in {file_path}")
                print(f"    Pattern matched but verification failed. Manual review recommended.")
        
        # 3. Update PostgreSQL pool sizes (reduce from 50/100 to 10/20)
        pg_pattern = r'pool_size=50,\s*max_overflow=100,\s*pool_timeout=10'
        
        if re.search(pg_pattern, content):
            replacement = '''pool_size=10,
        max_overflow=20,
        pool_timeout=30,
        pool_recycle=3600,
        pool_pre_ping=True'''
            
            new_content = re.sub(pg_pattern, replacement, content)
            
            # Verify the replacement was successful
            if 'pool_size=10' in new_content and 'pool_size=50' not in new_content:
                content = new_content
                modified = True
            else:
                print(f"  ⚠ Warning: PostgreSQL pool replacement may have failed in {file_path}")
                print(f"    Pattern matched but verification failed. Manual review recommended.")
        
        # Write back if modified
        if modified:
            with open(file_path, 'w') as f:
                f.write(content)
            print(f"  ✓ Updated {file_path}")
            return True
        else:
            print(f"  - No changes needed for {file_path}")
            return False
            
    except Exception as e:
        print(f"  ✗ Error updating {file_path}: {e}")
        return False

def main():
    print("=" * 60)
    print("Database Connection Pool Fix - Batch Update")
    print("=" * 60)
    print()
    
    # Get workspace directory
    workspace = Path("/Users/gopinathshiva/Projects/Open-Algo-Container/openalgo1 Gopi")
    os.chdir(workspace)
    
    # Create backup directory
    import datetime
    backup_dir = workspace / f"backup_db_files_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
    backup_dir.mkdir(exist_ok=True)
    
    print(f"Backup directory: {backup_dir}")
    print()
    
    updated_count = 0
    skipped_count = 0
    failed_count = 0
    
    for db_file in DB_FILES:
        file_path = workspace / db_file
        
        if not file_path.exists():
            print(f"⚠ File not found: {db_file}")
            failed_count += 1
            continue
        
        # Backup original
        import shutil
        backup_path = backup_dir / Path(db_file).name
        try:
            shutil.copy2(file_path, backup_path)
        except Exception as e:
            print(f"  ✗ Failed to backup {db_file}: {e}")
            failed_count += 1
            continue
        
        # Update the file
        result = update_file(file_path)
        if result is True:
            updated_count += 1
        elif result is False:
            skipped_count += 1
        else:  # None or error
            failed_count += 1
    
    print()
    print("=" * 60)
    print(f"✓ Updated: {updated_count} files")
    print(f"- Skipped (no changes needed): {skipped_count} files")
    print(f"✗ Failed: {failed_count} files")
    print(f"Backups saved to: {backup_dir}")
    print("=" * 60)
    print()
    print("Next steps:")
    print("1. Review the changes: git diff database/")
    print("2. Test the application")
    print("3. Monitor file descriptors: ./tmp_rovodev_monitor_fds.sh")
    print()

if __name__ == "__main__":
    main()
