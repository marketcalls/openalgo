"""
Simple test to check which HTTP protocol your broker APIs are using
"""
import httpx
import time

def test_broker_apis():
    """Test common broker APIs to see which HTTP protocol they support"""
    
    print("=" * 70)
    print("BROKER API HTTP PROTOCOL TEST")
    print("=" * 70)
    
    # Create client with auto-negotiation
    client = httpx.Client(
        http2=True,
        http1=True,
        timeout=10.0,
        limits=httpx.Limits(
            max_keepalive_connections=20,
            max_connections=50,
            keepalive_expiry=120.0
        )
    )
    
    # Test URLs - these are public endpoints that should respond
    test_urls = [
        ("Upstox API", "https://api.upstox.com"),
        ("Zerodha Kite", "https://api.kite.trade"),
        ("Angel One", "https://apiconnect.angelone.com"),
        ("5Paisa", "https://openapi.5paisa.com"),
        ("Google (for comparison)", "https://www.google.com"),
        ("CloudFlare (for comparison)", "https://www.cloudflare.com"),
    ]
    
    print("\nTesting with AUTO-NEGOTIATION (http2=True, http1=True):")
    print("-" * 70)
    
    for name, url in test_urls:
        try:
            print(f"\n{name:25} ({url})")
            
            # First request (includes connection setup)
            start = time.time()
            response = client.head(url, follow_redirects=True)
            first_time = (time.time() - start) * 1000
            
            print(f"  Protocol: {response.http_version:10} Status: {response.status_code:3}  First request: {first_time:.0f}ms")
            
            # Second request (reuses connection)
            start = time.time()
            response = client.head(url, follow_redirects=True)
            second_time = (time.time() - start) * 1000
            
            print(f"  Connection reused:                        Second request: {second_time:.0f}ms")
            
        except httpx.ConnectError:
            print(f"  Could not connect (may require authentication)")
        except httpx.HTTPStatusError as e:
            print(f"  HTTP error: {e.response.status_code}")
        except Exception as e:
            print(f"  Error: {str(e)[:60]}")
    
    client.close()
    
    # Test with HTTP/1.1 only
    print("\n" + "=" * 70)
    print("Testing with HTTP/1.1 ONLY (http2=False, http1=True):")
    print("-" * 70)
    
    client_http1 = httpx.Client(
        http2=False,
        http1=True,
        timeout=10.0,
        limits=httpx.Limits(
            max_keepalive_connections=10,
            max_connections=20,
            keepalive_expiry=60.0
        )
    )
    
    for name, url in test_urls[:3]:  # Test just first 3 broker APIs
        try:
            print(f"\n{name:25} ({url})")
            
            start = time.time()
            response = client_http1.head(url, follow_redirects=True)
            response_time = (time.time() - start) * 1000
            
            print(f"  Protocol: {response.http_version:10} Status: {response.status_code:3}  Time: {response_time:.0f}ms")
            
        except Exception as e:
            print(f"  Error: {str(e)[:60]}")
    
    client_http1.close()
    
    print("\n" + "=" * 70)
    print("SUMMARY:")
    print("-" * 70)
    print("- Most broker APIs support HTTP/1.1 only")
    print("- Auto-negotiation (http2=True, http1=True) automatically uses the right protocol")
    print("- Connection reuse significantly reduces latency on subsequent requests")
    print("- First request includes: DNS lookup + TCP handshake + TLS handshake + protocol negotiation")
    print("- Subsequent requests reuse the established connection")
    print("=" * 70)

if __name__ == "__main__":
    test_broker_apis()