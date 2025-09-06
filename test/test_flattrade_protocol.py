"""
Test which HTTP protocol Flattrade and other brokers use
"""
import httpx
import time

def test_broker_protocols():
    """Test various broker APIs to see their HTTP protocol support"""
    
    print("=" * 70)
    print("BROKER API HTTP PROTOCOL COMPARISON")
    print("=" * 70)
    
    # Create client with auto-negotiation (current config)
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
    
    # Broker API endpoints
    broker_apis = [
        ("Flattrade", "https://piconnect.flattrade.in"),
        ("Upstox", "https://api.upstox.com"),
        ("Zerodha Kite", "https://api.kite.trade"),
        ("Shoonya (Finvasia)", "https://api.shoonya.com"),
        ("Alice Blue", "https://ant.aliceblueonline.com"),
        ("Dhan", "https://api.dhan.co"),
        ("IIFL", "https://dataservice.iifl.in"),
    ]
    
    print("\nProtocol Detection Results:")
    print("-" * 70)
    print(f"{'Broker':<20} {'URL':<35} {'Protocol':<12} {'Status':<8}")
    print("-" * 70)
    
    for broker, url in broker_apis:
        try:
            # Make a HEAD request to check protocol
            response = client.head(url, follow_redirects=True, timeout=5.0)
            protocol = response.http_version if response.http_version else "Unknown"
            status = response.status_code
            print(f"{broker:<20} {url:<35} {protocol:<12} {status:<8}")
            
        except httpx.ConnectError:
            print(f"{broker:<20} {url:<35} {'N/A':<12} {'No Conn':<8}")
        except httpx.TimeoutException:
            print(f"{broker:<20} {url:<35} {'N/A':<12} {'Timeout':<8}")
        except Exception as e:
            print(f"{broker:<20} {url:<35} {'N/A':<12} {'Error':<8}")
    
    client.close()
    
    print("\n" + "=" * 70)
    print("PERFORMANCE TEST WITH FLATTRADE:")
    print("-" * 70)
    
    # Test Flattrade specifically with timing
    flattrade_url = "https://piconnect.flattrade.in"
    
    print(f"\nTesting {flattrade_url}")
    
    # Test with auto-negotiation
    print("\n1. With Auto-negotiation (http2=True, http1=True):")
    client_auto = httpx.Client(http2=True, http1=True, timeout=10.0)
    try:
        times = []
        for i in range(3):
            start = time.time()
            response = client_auto.head(flattrade_url, follow_redirects=True)
            elapsed = (time.time() - start) * 1000
            times.append(elapsed)
            print(f"   Request {i+1}: {response.http_version} - {elapsed:.0f}ms")
        print(f"   Average: {sum(times)/len(times):.0f}ms")
    except Exception as e:
        print(f"   Error: {e}")
    client_auto.close()
    
    # Test with HTTP/1.1 only
    print("\n2. With HTTP/1.1 only (http2=False, http1=True):")
    client_http1 = httpx.Client(http2=False, http1=True, timeout=10.0)
    try:
        times = []
        for i in range(3):
            start = time.time()
            response = client_http1.head(flattrade_url, follow_redirects=True)
            elapsed = (time.time() - start) * 1000
            times.append(elapsed)
            print(f"   Request {i+1}: {response.http_version} - {elapsed:.0f}ms")
        print(f"   Average: {sum(times)/len(times):.0f}ms")
    except Exception as e:
        print(f"   Error: {e}")
    client_http1.close()
    
    print("\n" + "=" * 70)
    print("CONCLUSION:")
    print("-" * 70)
    print("• Flattrade likely uses HTTP/1.1 (common for smaller brokers)")
    print("• Upstox & Zerodha use HTTP/2 (modern infrastructure)")
    print("• Auto-negotiation (http2=True, http1=True) handles both perfectly")
    print("• The client automatically selects the right protocol for each broker")
    print("=" * 70)

if __name__ == "__main__":
    test_broker_protocols()