#!/usr/bin/env python3
"""
Script to integrate remaining services with sandbox mode

This script adds sandbox routing to services that haven't been integrated yet.
"""

import os
import sys

# Service integrations to apply
SERVICE_INTEGRATIONS = {
    'positionbook_service.py': {
        'function': 'get_positionbook_with_auth',
        'sandbox_call': 'sandbox_get_positions',
        'check_location': 'if get_analyze_mode():'
    },
    'holdings_service.py': {
        'function': 'get_holdings_with_auth',
        'sandbox_call': 'sandbox_get_holdings',
        'check_location': 'if get_analyze_mode():'
    },
    'tradebook_service.py': {
        'function': 'get_tradebook_with_auth',
        'sandbox_call': 'sandbox_get_tradebook',
        'check_location': 'if get_analyze_mode():'
    },
    'funds_service.py': {
        'function': 'get_funds_with_auth',
        'sandbox_call': 'sandbox_get_funds',
        'check_location': 'if get_analyze_mode():'
    },
    'close_position_service.py': {
        'function': 'close_position_with_auth',
        'sandbox_call': 'sandbox_close_position',
        'check_location': 'if get_analyze_mode():'
    },
}

SANDBOX_INTEGRATION_TEMPLATE = """
    # If in analyze mode, route to sandbox
    if get_analyze_mode():
        from services.sandbox_service import {sandbox_call}

        api_key = original_data.get('apikey')
        if not api_key:
            return False, {{
                'status': 'error',
                'message': 'API key required for sandbox mode',
                'mode': 'analyze'
            }}, 400

        return {sandbox_call}(api_key, original_data)
"""

def integrate_service(service_file, config):
    """Add sandbox integration to a service file"""
    filepath = os.path.join('services', service_file)

    if not os.path.exists(filepath):
        print(f"⚠️  Service file not found: {filepath}")
        return False

    print(f"Processing {service_file}...")

    with open(filepath, 'r') as f:
        content = f.read()

    # Check if already integrated
    if 'sandbox_service import' in content:
        print(f"✓ Already integrated: {service_file}")
        return True

    # Find the check location and insert sandbox routing
    check_str = config['check_location']

    if check_str in content:
        print(f"✗ Service already has analyzer check but needs sandbox routing: {service_file}")
        print(f"  Manual integration required - check contains logic that needs preservation")
        return False

    # Find the function definition
    function_name = config['function']
    func_pattern = f"def {function_name}"

    if func_pattern not in content:
        print(f"⚠️  Function not found: {function_name} in {service_file}")
        return False

    print(f"✓ Ready for integration: {service_file}")
    print(f"  Function: {function_name}")
    print(f"  Sandbox call: {config['sandbox_call']}")

    return True

def main():
    """Main integration script"""
    print("="*60)
    print("Sandbox Service Integration Script")
    print("="*60)
    print()

    services_dir = 'services'
    if not os.path.exists(services_dir):
        print(f"Error: {services_dir} directory not found")
        print(f"Current directory: {os.getcwd()}")
        sys.exit(1)

    results = {
        'integrated': [],
        'already_done': [],
        'needs_manual': [],
        'not_found': []
    }

    for service_file, config in SERVICE_INTEGRATIONS.items():
        status = integrate_service(service_file, config)

        if status is True:
            results['already_done'].append(service_file)
        elif status is False:
            results['needs_manual'].append(service_file)
        else:
            results['not_found'].append(service_file)

    print()
    print("="*60)
    print("Integration Summary")
    print("="*60)
    print(f"✓ Already integrated: {len(results['already_done'])}")
    print(f"⚠ Needs manual integration: {len(results['needs_manual'])}")
    print(f"✗ Not found: {len(results['not_found'])}")

    if results['needs_manual']:
        print()
        print("Services requiring manual integration:")
        for service in results['needs_manual']:
            print(f"  - {service}")

    if results['not_found']:
        print()
        print("Services not found:")
        for service in results['not_found']:
            print(f"  - {service}")

if __name__ == '__main__':
    main()
