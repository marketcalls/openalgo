#!/usr/bin/env python3
"""
Simple rate limit test without external dependencies
Tests the rate limit configuration and implementation
"""

import os
import time
import re
from collections import defaultdict
from datetime import datetime, timedelta


class MockRateLimiter:
    """Simple rate limiter implementation for testing"""
    
    def __init__(self):
        self.requests = defaultdict(list)
        self.limits = {}
    
    def set_limit(self, endpoint, limit_str):
        """Set rate limit for an endpoint"""
        match = re.match(r'(\d+)\s+per\s+(second|minute|hour|day)', limit_str)
        if not match:
            raise ValueError(f"Invalid rate limit format: {limit_str}")
        
        count = int(match.group(1))
        period = match.group(2)
        
        # Convert to seconds
        period_seconds = {
            'second': 1,
            'minute': 60,
            'hour': 3600,
            'day': 86400
        }[period]
        
        self.limits[endpoint] = (count, period_seconds)
    
    def is_allowed(self, endpoint, client_id='default'):
        """Check if request is allowed"""
        if endpoint not in self.limits:
            return True
        
        limit_count, limit_seconds = self.limits[endpoint]
        now = datetime.now()
        cutoff = now - timedelta(seconds=limit_seconds)
        
        # Get recent requests for this endpoint and client
        key = (endpoint, client_id)
        recent_requests = [req for req in self.requests[key] if req > cutoff]
        
        # Update the list with only recent requests
        self.requests[key] = recent_requests
        
        # Check if under limit
        if len(recent_requests) < limit_count:
            self.requests[key].append(now)
            return True
        
        return False


def test_rate_limit_configuration():
    """Test rate limit configuration"""
    print("Testing Rate Limit Configuration")
    print("=" * 50)
    
    # Load environment variables from .env file
    base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env_path = os.path.join(base_path, '.env')
    
    env_values = {}
    if os.path.exists(env_path):
        with open(env_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    key = key.strip()
                    value = value.strip().strip("'\"")
                    env_values[key] = value
    
    # Check environment variables
    expected_vars = {
        'API_RATE_LIMIT': '50 per second',
        'ORDER_RATE_LIMIT': '10 per second',
        'SMART_ORDER_RATE_LIMIT': '2 per second',
        'WEBHOOK_RATE_LIMIT': '100 per minute',
        'STRATEGY_RATE_LIMIT': '200 per minute',
        'LOGIN_RATE_LIMIT_MIN': '5 per minute',
        'LOGIN_RATE_LIMIT_HOUR': '25 per hour'
    }
    
    all_correct = True
    
    for var, expected in expected_vars.items():
        actual = env_values.get(var) or os.getenv(var)
        if actual == expected:
            print(f"✓ {var}: {actual}")
        else:
            print(f"✗ {var}: Expected '{expected}', got '{actual}'")
            all_correct = False
    
    return all_correct


def test_rate_limiter_logic():
    """Test rate limiter logic"""
    print("\nTesting Rate Limiter Logic")
    print("=" * 50)
    
    limiter = MockRateLimiter()
    
    # Test 1: Order endpoint (10 per second)
    print("\nTest 1: Order endpoint (10 per second)")
    limiter.set_limit('/placeorder', '10 per second')
    
    # Should allow 10 requests
    success_count = 0
    for i in range(12):
        if limiter.is_allowed('/placeorder'):
            success_count += 1
    
    print(f"  Allowed {success_count} requests out of 12")
    test1_passed = success_count == 10
    print(f"  {'✓ PASSED' if test1_passed else '✗ FAILED'}")
    
    # Test 2: Smart order endpoint (2 per second)
    print("\nTest 2: Smart order endpoint (2 per second)")
    limiter.set_limit('/placesmartorder', '2 per second')
    
    success_count = 0
    for i in range(5):
        if limiter.is_allowed('/placesmartorder'):
            success_count += 1
    
    print(f"  Allowed {success_count} requests out of 5")
    test2_passed = success_count == 2
    print(f"  {'✓ PASSED' if test2_passed else '✗ FAILED'}")
    
    # Test 3: Rate limit reset
    print("\nTest 3: Rate limit reset after time window")
    time.sleep(1.1)  # Wait for rate limit to reset
    
    if limiter.is_allowed('/placeorder'):
        print(f"  ✓ PASSED - Request allowed after rate limit reset")
        test3_passed = True
    else:
        print(f"  ✗ FAILED - Request not allowed after rate limit reset")
        test3_passed = False
    
    # Test 4: Different clients have separate limits
    print("\nTest 4: Different clients have separate rate limits")
    limiter = MockRateLimiter()
    limiter.set_limit('/api/endpoint', '5 per second')
    
    # Client 1 makes 5 requests
    client1_count = 0
    for i in range(5):
        if limiter.is_allowed('/api/endpoint', 'client1'):
            client1_count += 1
    
    # Client 2 should still be able to make requests
    client2_allowed = limiter.is_allowed('/api/endpoint', 'client2')
    
    test4_passed = client1_count == 5 and client2_allowed
    print(f"  Client 1: {client1_count}/5 requests")
    print(f"  Client 2: {'Allowed' if client2_allowed else 'Blocked'}")
    print(f"  {'✓ PASSED' if test4_passed else '✗ FAILED'}")
    
    return all([test1_passed, test2_passed, test3_passed, test4_passed])


def test_file_modifications():
    """Test that files have been properly modified"""
    print("\nTesting File Modifications")
    print("=" * 50)
    
    files_to_check = [
        ('restx_api/place_order.py', 'ORDER_RATE_LIMIT'),
        ('restx_api/modify_order.py', 'ORDER_RATE_LIMIT'),
        ('restx_api/cancel_order.py', 'ORDER_RATE_LIMIT'),
        ('restx_api/place_smart_order.py', 'SMART_ORDER_RATE_LIMIT'),
        ('blueprints/strategy.py', ['WEBHOOK_RATE_LIMIT', 'STRATEGY_RATE_LIMIT']),
        ('blueprints/chartink.py', ['WEBHOOK_RATE_LIMIT', 'STRATEGY_RATE_LIMIT']),
        ('utils/env_check.py', ['ORDER_RATE_LIMIT', 'SMART_ORDER_RATE_LIMIT', 'WEBHOOK_RATE_LIMIT', 'STRATEGY_RATE_LIMIT'])
    ]
    
    all_correct = True
    base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    for file_path, expected_content in files_to_check:
        full_path = os.path.join(base_path, file_path)
        
        if os.path.exists(full_path):
            with open(full_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            if isinstance(expected_content, list):
                # Check for multiple strings
                all_found = all(item in content for item in expected_content)
                if all_found:
                    print(f"✓ {file_path}: Contains all required rate limit variables")
                else:
                    print(f"✗ {file_path}: Missing some rate limit variables")
                    all_correct = False
            else:
                # Check for single string
                if expected_content in content:
                    print(f"✓ {file_path}: Uses {expected_content}")
                else:
                    print(f"✗ {file_path}: Does not use {expected_content}")
                    all_correct = False
        else:
            print(f"✗ {file_path}: File not found")
            all_correct = False
    
    return all_correct


def main():
    """Run all tests"""
    print("\nOpenAlgo Rate Limit Tests (Simple)")
    print("=" * 70)
    print(f"Test Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)
    
    # Run tests
    config_passed = test_rate_limit_configuration()
    logic_passed = test_rate_limiter_logic()
    files_passed = test_file_modifications()
    
    # Summary
    print("\n" + "=" * 70)
    print("Test Summary:")
    print(f"  Configuration Test: {'✓ PASSED' if config_passed else '✗ FAILED'}")
    print(f"  Rate Limiter Logic: {'✓ PASSED' if logic_passed else '✗ FAILED'}")
    print(f"  File Modifications: {'✓ PASSED' if files_passed else '✗ FAILED'}")
    
    all_passed = all([config_passed, logic_passed, files_passed])
    
    print("\nOverall Result:")
    if all_passed:
        print("✅ All tests PASSED!")
    else:
        print("❌ Some tests FAILED!")
    
    print("=" * 70)
    
    return 0 if all_passed else 1


if __name__ == '__main__':
    exit(main())