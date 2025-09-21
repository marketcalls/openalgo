#!/usr/bin/env python
"""
Test script to verify log location change
"""

import os
from pathlib import Path

def test_log_location():
    """Verify log folder structure is correct"""
    
    print("Testing Log Location Configuration")
    print("-" * 40)
    
    # Check log folder exists
    log_dir = Path('log')
    if log_dir.exists():
        print(f"[OK] Log directory exists: {log_dir.absolute()}")
    else:
        print(f"[ERROR] Log directory missing: {log_dir.absolute()}")
        return False
    
    # Check strategies subfolder
    strategies_log_dir = log_dir / 'strategies'
    if strategies_log_dir.exists():
        print(f"[OK] Strategies log directory exists: {strategies_log_dir.absolute()}")
    else:
        print(f"[ERROR] Strategies log directory missing: {strategies_log_dir.absolute()}")
        return False
    
    # Check gitignore file
    gitignore_file = strategies_log_dir / '.gitignore'
    if gitignore_file.exists():
        print(f"[OK] .gitignore file exists: {gitignore_file.absolute()}")
        
        # Check gitignore content
        with open(gitignore_file, 'r') as f:
            content = f.read()
            if '*.log' in content:
                print("[OK] .gitignore correctly ignores log files")
            else:
                print("[ERROR] .gitignore missing *.log pattern")
    else:
        print(f"[ERROR] .gitignore file missing: {gitignore_file.absolute()}")
        return False
    
    # Check old logs folder is removed
    old_logs_dir = Path('logs')
    if not old_logs_dir.exists():
        print(f"[OK] Old logs directory removed")
    else:
        print(f"[WARNING] Old logs directory still exists: {old_logs_dir.absolute()}")
        print("  Please remove it manually")
    
    print("-" * 40)
    print("[SUCCESS] Log location configuration is correct!")
    print("\nLog files will be saved to: log/strategies/")
    print("Example: log/strategies/strategy_id_20240101_120000_IST.log")
    
    return True

if __name__ == "__main__":
    # Change to OpenAlgo root directory if needed
    if os.path.basename(os.getcwd()) == 'test':
        os.chdir('..')
    
    success = test_log_location()
    exit(0 if success else 1)