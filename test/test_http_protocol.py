"""
Test script to check which HTTP protocol is being used by httpx client
"""
import httpx
import logging

# Set up detailed logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

def test_protocol_detection():
    """Test which HTTP protocol is used with different configurations"""
    
    print("=" * 60)
    print("HTTP Protocol Detection Test")
    print("=" * 60)
    
    # Test 1: Auto-negotiation (both HTTP/2 and HTTP/1.1 enabled)
    print("\n1. Testing with AUTO-NEGOTIATION (http2=True, http1=True):")
    print("-" * 40)
    client_auto = httpx.Client(
        http2=True,
        http1=True,
        timeout=30.0
    )
    
    # Test with a known HTTP/2 supporting site
    print("\nTesting with google.com (known HTTP/2 support):")
    try:
        response = client_auto.get("https://www.google.com")
        print(f"Protocol used: {response.http_version}")
        print(f"Status: {response.status_code}")
    except Exception as e:
        print(f"Error: {e}")
    
    # Test with httpbin (usually HTTP/1.1)
    print("\nTesting with httpbin.org (usually HTTP/1.1):")
    try:
        response = client_auto.get("https://httpbin.org/get")
        print(f"Protocol used: {response.http_version}")
        print(f"Status: {response.status_code}")
    except Exception as e:
        print(f"Error: {e}")
    
    client_auto.close()
    
    # Test 2: HTTP/2 only
    print("\n2. Testing with HTTP/2 ONLY (http2=True, http1=False):")
    print("-" * 40)
    client_http2 = httpx.Client(
        http2=True,
        http1=False,
        timeout=30.0
    )
    
    print("\nTesting with google.com:")
    try:
        response = client_http2.get("https://www.google.com")
        print(f"Protocol used: {response.http_version}")
        print(f"Status: {response.status_code}")
    except Exception as e:
        print(f"Error (expected if server doesn't support HTTP/2): {e}")
    
    client_http2.close()
    
    # Test 3: HTTP/1.1 only
    print("\n3. Testing with HTTP/1.1 ONLY (http2=False, http1=True):")
    print("-" * 40)
    client_http1 = httpx.Client(
        http2=False,
        http1=True,
        timeout=30.0
    )
    
    print("\nTesting with google.com:")
    try:
        response = client_http1.get("https://www.google.com")
        print(f"Protocol used: {response.http_version}")
        print(f"Status: {response.status_code}")
    except Exception as e:
        print(f"Error: {e}")
    
    client_http1.close()
    
    print("\n" + "=" * 60)
    print("TESTING WITH YOUR BROKER API")
    print("=" * 60)

def test_broker_protocol():
    """Test which protocol your broker API uses"""
    
    # Add parent directory to path to import utils
    import sys
    import os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    
    # Import your httpx_client
    from utils.httpx_client import get_httpx_client, request
    
    client = get_httpx_client()
    
    # Common broker API endpoints (these are public endpoints)
    broker_urls = {
        "Upstox": "https://api.upstox.com/v2/",
        "Zerodha (Kite)": "https://api.kite.trade/",
        "Angel One": "https://apiconnect.angelbroking.com/",
        "5Paisa": "https://openapi.5paisa.com/",
        "Fyers": "https://api.fyers.in/api/v2/",
    }
    
    print("\nTesting broker API endpoints:")
    print("-" * 40)
    
    for broker, url in broker_urls.items():
        try:
            print(f"\n{broker} ({url}):")
            response = client.head(url, follow_redirects=True)
            print(f"  Protocol: {response.http_version}")
            print(f"  Status: {response.status_code}")
        except Exception as e:
            print(f"  Could not connect: {str(e)[:50]}")
    
    # Test with the actual OpenAlgo client
    print("\n" + "=" * 60)
    print("Testing with your current httpx_client configuration:")
    print("-" * 40)
    
    # Make a test request to see protocol info
    try:
        # This will use your configured client
        test_url = "https://www.google.com"
        print(f"\nTest URL: {test_url}")
        response = client.get(test_url)
        print(f"Protocol used: {response.http_version}")
        print(f"Status code: {response.status_code}")
        
        # Check connection pool info
        print(f"\nConnection pool settings:")
        print(f"  Max connections: {client._transport._pool._max_connections}")
        print(f"  Max keepalive: {client._transport._pool._max_keepalive_connections}")
        print(f"  Keepalive expiry: {client._transport._pool._keepalive_expiry}")
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_protocol_detection()
    print("\n")
    test_broker_protocol()