#!/usr/bin/env python3
"""
Script to convert print statements to centralized logging in broker files.
Focuses on security and proper logging practices.
"""

import os
import re
import glob
from pathlib import Path

# Patterns for sensitive data that should be masked or removed
SENSITIVE_PATTERNS = [
    r'token',
    r'auth',
    r'key',
    r'secret',
    r'password',
    r'credential',
    r'api_key',
    r'access_token',
    r'refresh_token',
    r'session',
    r'login'
]

# Common print patterns and their replacements
PRINT_REPLACEMENTS = [
    # Error messages
    (r'print\(f?"Error ([^"]*): \{([^}]+)\}"\)', r'logger.error(f"Error \1: {\2}")'),
    (r'print\(f?"Error: ([^"]*)"\)', r'logger.error(f"Error: \1")'),
    
    # Debug/info messages
    (r'print\(f?"([^"]*) successful[ly]*[^"]*"\)', r'logger.info(f"\1 successful")'),
    (r'print\(f?"Processing ([^"]*)"\)', r'logger.info(f"Processing \1")'),
    (r'print\(f?"Downloading ([^"]*)"\)', r'logger.info(f"Downloading \1")'),
    (r'print\(f?"Initializing ([^"]*)"\)', r'logger.info(f"Initializing \1")'),
    (r'print\(f?"Deleting ([^"]*)"\)', r'logger.info(f"Deleting \1")'),
    (r'print\(f?"Performing ([^"]*)"\)', r'logger.info(f"Performing \1")'),
    
    # Warning messages
    (r'print\(f?"Warning: ([^"]*)"\)', r'logger.warning(f"\1")'),
    (r'print\(f?"No ([^"]*) available[^"]*"\)', r'logger.warning(f"No \1 available")'),
    (r'print\(f?"([^"]*) not found[^"]*"\)', r'logger.warning(f"\1 not found")'),
    
    # Debug level for detailed data
    (r'print\(f?"Net Quantity ([^"]*)"\)', r'logger.debug(f"Net Quantity \1")'),
    (r'print\(f?"position_size[^"]*"\)', r'logger.debug(f"Position size information")'),
    (r'print\(f?"Open Position[^"]*"\)', r'logger.debug(f"Open position information")'),
    
    # Generic conversions
    (r'print\(([^)]+)\)', r'logger.info(\1)'),
]

def has_sensitive_data(content):
    """Check if content contains potentially sensitive data"""
    content_lower = content.lower()
    return any(pattern in content_lower for pattern in SENSITIVE_PATTERNS)

def add_logger_import(file_path):
    """Add logger import to file if not present"""
    with open(file_path, 'r') as f:
        content = f.read()
    
    if 'from utils.openalgo_logger import get_logger' in content:
        return content  # Already has import
    
    # Find the best place to insert the import
    lines = content.split('\n')
    insert_index = 0
    
    # Find last import statement
    for i, line in enumerate(lines):
        if line.startswith('import ') or line.startswith('from '):
            insert_index = i + 1
    
    # Insert the import and logger setup
    logger_import = [
        'from utils.openalgo_logger import get_logger',
        '',
        '# Set up logger',
        'logger = get_logger(__name__)',
        ''
    ]
    
    lines[insert_index:insert_index] = logger_import
    return '\n'.join(lines)

def convert_print_statements(content):
    """Convert print statements to appropriate logging calls"""
    modified_content = content
    conversion_log = []
    
    # Find all print statements
    print_pattern = r'print\([^)]*\)'
    print_matches = re.findall(print_pattern, content)
    
    for match in print_matches:
        original = match
        converted = None
        
        # Check if it contains sensitive data
        if has_sensitive_data(match):
            # For sensitive data, either remove or use debug level
            if any(keyword in match.lower() for keyword in ['payload', 'response', 'data']):
                # Replace with debug level logging without the actual data
                converted = 'logger.debug("API operation completed")'
                conversion_log.append(f"SENSITIVE: {original} -> {converted}")
            else:
                # Remove entirely
                modified_content = modified_content.replace(original, '# Removed sensitive data logging')
                conversion_log.append(f"REMOVED: {original}")
                continue
        else:
            # Apply pattern replacements
            for pattern, replacement in PRINT_REPLACEMENTS:
                new_match = re.sub(pattern, replacement, match)
                if new_match != match:
                    converted = new_match
                    break
            
            if not converted:
                # Default conversion
                converted = match.replace('print(', 'logger.info(')
        
        if converted:
            modified_content = modified_content.replace(original, converted)
            conversion_log.append(f"CONVERT: {original} -> {converted}")
    
    return modified_content, conversion_log

def process_file(file_path):
    """Process a single Python file"""
    try:
        with open(file_path, 'r') as f:
            content = f.read()
        
        # Check if file has print statements
        if 'print(' not in content:
            return None
        
        print(f"Processing: {file_path}")
        
        # Add logger import if needed
        content = add_logger_import(file_path)
        
        # Convert print statements
        modified_content, conversion_log = convert_print_statements(content)
        
        # Write back the modified content
        with open(file_path, 'w') as f:
            f.write(modified_content)
        
        return {
            'file': file_path,
            'conversions': len(conversion_log),
            'log': conversion_log
        }
        
    except Exception as e:
        print(f"Error processing {file_path}: {e}")
        return None

def main():
    """Main function to process all broker files"""
    broker_dir = '/Users/openalgo/openalgo-websockets/openalgo/broker'
    
    # Find all Python files in broker directory
    python_files = []
    for root, dirs, files in os.walk(broker_dir):
        for file in files:
            if file.endswith('.py'):
                python_files.append(os.path.join(root, file))
    
    print(f"Found {len(python_files)} Python files in broker directory")
    
    total_conversions = 0
    processed_files = []
    
    # Process each file
    for file_path in python_files:
        result = process_file(file_path)
        if result:
            total_conversions += result['conversions']
            processed_files.append(result)
    
    # Generate summary report
    print(f"\n=== CONVERSION SUMMARY ===")
    print(f"Files processed: {len(processed_files)}")
    print(f"Total conversions: {total_conversions}")
    
    # Print detailed log for sensitive data handling
    print(f"\n=== SENSITIVE DATA HANDLING ===")
    for result in processed_files:
        sensitive_logs = [log for log in result['log'] if log.startswith('SENSITIVE') or log.startswith('REMOVED')]
        if sensitive_logs:
            print(f"\n{result['file']}:")
            for log in sensitive_logs:
                print(f"  {log}")

if __name__ == "__main__":
    main()