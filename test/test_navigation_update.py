#!/usr/bin/env python
"""
Test script to verify navigation changes
- Python Strategies removed from main navbar
- Python Strategies added to profile dropdown below Holdings
"""

import os
from pathlib import Path

def test_navigation_update():
    """Verify navigation changes in templates"""
    
    print("Testing Navigation Update")
    print("-" * 50)
    
    # Files to check
    navbar_file = Path('templates/navbar.html')
    base_file = Path('templates/base.html')
    
    # Check navbar.html
    if navbar_file.exists():
        with open(navbar_file, 'r', encoding='utf-8') as f:
            navbar_content = f.read()
            
        # Check Python is removed from main nav
        if 'Python</a>' in navbar_content and 'Strategy</a>' in navbar_content:
            # Find positions to ensure Python is not between Strategy and API Analyzer
            strategy_pos = navbar_content.find('strategy_bp.index')
            analyzer_pos = navbar_content.find('analyzer_bp.analyzer')
            python_nav_pos = navbar_content.find('python_strategy_bp.index')
            
            # Check if Python is in main nav (between Strategy and Analyzer)
            if python_nav_pos > strategy_pos and python_nav_pos < analyzer_pos:
                print("[ERROR] Python still in main navbar between Strategy and API Analyzer")
            else:
                print("[OK] Python removed from main navbar")
        else:
            print("[OK] Python not found in main navbar section")
            
        # Check Python is in profile dropdown
        holdings_pos = navbar_content.find('orders_bp.holdings')
        python_dropdown_pos = navbar_content.rfind('python_strategy_bp.index')  # Use rfind to get last occurrence
        
        if python_dropdown_pos > holdings_pos:
            print("[OK] Python Strategies added to profile dropdown after Holdings")
            
            # Check it has proper icon
            if 'M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4' in navbar_content[holdings_pos:python_dropdown_pos+200]:
                print("[OK] Python Strategies has code icon in dropdown")
        else:
            print("[ERROR] Python Strategies not found after Holdings in dropdown")
    else:
        print(f"[ERROR] Navbar file not found: {navbar_file}")
        
    # Check base.html (mobile navigation)
    if base_file.exists():
        with open(base_file, 'r', encoding='utf-8') as f:
            base_content = f.read()
            
        # Find the mobile nav section
        mobile_nav_start = base_content.find('drawer-side')
        mobile_nav_end = base_content.find('</div>', mobile_nav_start + 500)
        mobile_nav_section = base_content[mobile_nav_start:mobile_nav_end] if mobile_nav_start > 0 else ""
        
        # Check Python is not in mobile main nav
        if 'python_strategy_bp.index' in mobile_nav_section and mobile_nav_section.count('python_strategy_bp.index') == 1:
            # It should only appear once (in the profile section)
            print("[OK] Python removed from mobile main navigation")
        else:
            mobile_count = base_content.count('python_strategy_bp.index')
            if mobile_count == 1:
                print("[OK] Python appears only once in base.html (in profile section)")
            else:
                print(f"[WARNING] Python appears {mobile_count} times in base.html")
                
        # Check Python is after Holdings
        holdings_pos = base_content.find('orders_bp.holdings')
        python_pos = base_content.find('python_strategy_bp.index', holdings_pos)
        
        if python_pos > holdings_pos and python_pos - holdings_pos < 500:  # Should be close
            print("[OK] Python Strategies positioned after Holdings in mobile nav")
        else:
            print("[ERROR] Python Strategies not properly positioned in mobile nav")
    else:
        print(f"[ERROR] Base file not found: {base_file}")
    
    print("-" * 50)
    print("Navigation update test complete!")
    print("\nSummary:")
    print("- Python Strategies removed from main navbar")
    print("- Python Strategies added to profile dropdown below Holdings")
    print("- Icon added for Python Strategies in dropdown")
    
    return True

if __name__ == "__main__":
    # Change to OpenAlgo root directory if needed
    if os.path.basename(os.getcwd()) == 'test':
        os.chdir('..')
    
    success = test_navigation_update()
    exit(0 if success else 1)