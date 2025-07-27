#!/usr/bin/env python3
"""
Mock test for rate limiting - simulates API calls without requiring a running server
"""

import time
import os
import sys
from datetime import datetime
from collections import defaultdict, deque


class MockAPI:
    """Mock API server with rate limiting"""
    
    def __init__(self):
        self.rate_limits = {}
        self.request_history = defaultdict(lambda: deque())
        self.load_rate_limits()
    
    def load_rate_limits(self):
        """Load rate limits from environment or .env file"""
        # Load from .env file
        env_values = {}
        base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        env_path = os.path.join(base_path, '.env')
        
        if os.path.exists(env_path):
            with open(env_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        key = key.strip()
                        value = value.strip().strip("'\"")
                        env_values[key] = value
        
        # Set rate limits for different endpoints
        self.rate_limits = {
            '/api/v1/placeorder': env_values.get('ORDER_RATE_LIMIT', '10 per second'),
            '/api/v1/modifyorder': env_values.get('ORDER_RATE_LIMIT', '10 per second'),
            '/api/v1/cancelorder': env_values.get('ORDER_RATE_LIMIT', '10 per second'),
            '/api/v1/placesmartorder': env_values.get('SMART_ORDER_RATE_LIMIT', '2 per second'),
            '/api/v1/quotes': env_values.get('API_RATE_LIMIT', '50 per second'),
            '/api/v1/depth': env_values.get('API_RATE_LIMIT', '50 per second'),
            '/api/v1/history': env_values.get('API_RATE_LIMIT', '50 per second'),
            '/strategy/webhook/test': env_values.get('WEBHOOK_RATE_LIMIT', '100 per minute'),
            '/chartink/webhook/test': env_values.get('WEBHOOK_RATE_LIMIT', '100 per minute'),
            '/strategy/new': env_values.get('STRATEGY_RATE_LIMIT', '200 per minute'),
            '/strategy/delete': env_values.get('STRATEGY_RATE_LIMIT', '200 per minute'),
            '/strategy/configure': env_values.get('STRATEGY_RATE_LIMIT', '200 per minute'),
        }
    
    def parse_rate_limit(self, limit_str):
        """Parse rate limit string to count and seconds"""
        parts = limit_str.split()
        count = int(parts[0])
        if 'second' in limit_str:
            seconds = 1
        elif 'minute' in limit_str:
            seconds = 60
        elif 'hour' in limit_str:
            seconds = 3600
        else:
            seconds = 1
        return count, seconds
    
    def make_request(self, endpoint, client_ip='127.0.0.1'):
        """Simulate an API request"""
        if endpoint not in self.rate_limits:
            return 404, {'error': 'Endpoint not found'}
        
        # Get rate limit for endpoint
        limit_count, limit_seconds = self.parse_rate_limit(self.rate_limits[endpoint])
        
        # Get request history for this endpoint and client
        key = (endpoint, client_ip)
        now = time.time()
        
        # Remove old requests outside the time window
        while self.request_history[key] and self.request_history[key][0] < now - limit_seconds:
            self.request_history[key].popleft()
        
        # Check if rate limit exceeded
        if len(self.request_history[key]) >= limit_count:
            return 429, {'error': 'Rate limit exceeded'}
        
        # Add this request to history
        self.request_history[key].append(now)
        
        # Return success
        return 200, {'status': 'success', 'message': 'Request processed'}


def test_endpoint(api, endpoint, expected_limit, description):
    """Test rate limiting for a specific endpoint"""
    print(f"\n{description}")
    print(f"Testing: {endpoint}")
    print(f"Expected limit: {expected_limit}")
    print("-" * 50)
    
    success_count = 0
    rate_limited_count = 0
    
    # Make requests up to 20% more than limit
    total_requests = int(expected_limit * 1.2)
    
    for i in range(total_requests):
        status, response = api.make_request(endpoint)
        
        if status == 200:
            success_count += 1
            print("✓", end="", flush=True)
        elif status == 429:
            rate_limited_count += 1
            print("⚠", end="", flush=True)
        else:
            print("✗", end="", flush=True)
        
        # Small delay between requests
        if i < expected_limit - 1:
            time.sleep(0.01)
    
    print(f"\n\nResults:")
    print(f"  Successful: {success_count}/{total_requests}")
    print(f"  Rate limited: {rate_limited_count}/{total_requests}")
    
    # Verify rate limit was enforced
    if success_count == expected_limit and rate_limited_count == total_requests - expected_limit:
        print(f"  ✅ Rate limit correctly enforced at {expected_limit} requests")
        return True
    else:
        print(f"  ❌ Rate limit not properly enforced")
        return False


def test_rate_limit_reset(api, endpoint, limit):
    """Test that rate limits reset after time window"""
    print(f"\nTesting rate limit reset for {endpoint}")
    print("-" * 50)
    
    # Fill up the rate limit
    for i in range(limit):
        api.make_request(endpoint)
    
    # This should be rate limited
    status, _ = api.make_request(endpoint)
    if status == 429:
        print("✓ Rate limit enforced after reaching limit")
    else:
        print("✗ Rate limit not enforced")
        return False
    
    # Wait for rate limit to reset (1.1 seconds for per-second limits)
    print("Waiting 1.1 seconds for rate limit reset...")
    time.sleep(1.1)
    
    # This should succeed now
    status, _ = api.make_request(endpoint)
    if status == 200:
        print("✅ Rate limit reset successfully")
        return True
    else:
        print("❌ Rate limit did not reset")
        return False


def test_multiple_clients(api, endpoint, limit):
    """Test that different clients have separate rate limits"""
    print(f"\nTesting separate rate limits for different clients")
    print("-" * 50)
    
    # Client 1 uses up their limit
    for i in range(limit):
        api.make_request(endpoint, client_ip='192.168.1.1')
    
    # Client 1 should be rate limited
    status1, _ = api.make_request(endpoint, client_ip='192.168.1.1')
    
    # Client 2 should still be able to make requests
    status2, _ = api.make_request(endpoint, client_ip='192.168.1.2')
    
    if status1 == 429 and status2 == 200:
        print("✅ Different clients have separate rate limits")
        return True
    else:
        print("❌ Rate limits not properly separated by client")
        return False


def main():
    """Run all mock tests"""
    print("\nOpenAlgo Rate Limit Mock Tests")
    print("=" * 60)
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    # Create mock API
    api = MockAPI()
    
    # Display loaded rate limits
    print("\nLoaded Rate Limits:")
    for endpoint, limit in api.rate_limits.items():
        print(f"  {endpoint}: {limit}")
    
    # Run tests
    all_passed = True
    
    # Test order endpoints
    tests = [
        ('/api/v1/placeorder', 10, "Order Placement API"),
        ('/api/v1/modifyorder', 10, "Order Modification API"),
        ('/api/v1/cancelorder', 10, "Order Cancellation API"),
        ('/api/v1/placesmartorder', 2, "Smart Order API"),
        ('/api/v1/quotes', 50, "Quotes API (General)"),
        ('/strategy/webhook/test', 100, "Strategy Webhook API"),
        ('/chartink/webhook/test', 100, "ChartInk Webhook API"),
        ('/strategy/new', 200, "Strategy Creation API"),
    ]
    
    for endpoint, limit, description in tests:
        if not test_endpoint(api, endpoint, limit, description):
            all_passed = False
    
    # Test rate limit reset
    if not test_rate_limit_reset(api, '/api/v1/placeorder', 10):
        all_passed = False
    
    # Test multiple clients
    if not test_multiple_clients(api, '/api/v1/placesmartorder', 2):
        all_passed = False
    
    # Summary
    print("\n" + "=" * 60)
    if all_passed:
        print("✅ All mock tests PASSED!")
        print("\nRate limiting is correctly configured:")
        print("- Order APIs: 10 requests/second")
        print("- Smart Order API: 2 requests/second")
        print("- General APIs: 50 requests/second")
        print("- Webhook APIs: 100 requests/minute")
        print("- Strategy APIs: 200 requests/minute")
    else:
        print("❌ Some tests FAILED!")
    print("=" * 60)
    
    return 0 if all_passed else 1


if __name__ == '__main__':
    sys.exit(main())