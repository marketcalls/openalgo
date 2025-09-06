# HTTPX Client Documentation

## Overview

The OpenAlgo HTTPX client module provides optimized HTTP connection pooling for all broker API communications. It features automatic protocol negotiation between HTTP/2 and HTTP/1.1, ensuring optimal performance across different broker infrastructures.

## Architecture

### Core Components

1. **Single Shared Client**: One global HTTPX client instance handles all HTTP requests
2. **Automatic Protocol Negotiation**: Supports both HTTP/2 and HTTP/1.1 with automatic selection
3. **Connection Pooling**: Reuses connections to minimize latency
4. **Graceful Cleanup**: Proper resource management on shutdown

## Configuration

### Environment-Aware Settings

The client automatically detects the runtime environment and adjusts protocol settings:

#### Native/Local Environment (Default)
```python
httpx.Client(
    http2=True,           # Enable HTTP/2 support (2-3x faster)
    http1=True,           # Enable HTTP/1.1 fallback
    timeout=30.0,         # 30 second timeout
    limits=httpx.Limits(
        max_keepalive_connections=20,  # Persistent connections
        max_connections=50,             # Total connection limit
        keepalive_expiry=120.0         # 2 minute keepalive
    )
)
```

#### Docker Environment
```python
httpx.Client(
    http2=False,          # HTTP/2 disabled for compatibility
    http1=True,           # HTTP/1.1 only mode
    timeout=30.0,         # 30 second timeout
    limits=httpx.Limits(
        max_keepalive_connections=20,  # Still maintains connection pooling
        max_connections=50,             # Total connection limit
        keepalive_expiry=120.0         # 2 minute keepalive
    ),
    verify=True           # SSL/TLS verification enabled
)
```

### Why Different Settings?

#### Native Environment (HTTP/2 Enabled)
- **Performance**: HTTP/2 provides 2-3x faster performance through multiplexing and header compression
- **Connection Pooling**: Maintains optimal connection reuse
- **Protocol Negotiation**: Automatically selects best available protocol

#### Docker Environment (HTTP/1.1 Only)
- **Compatibility**: Avoids "illegal request line" errors with certain broker APIs
- **Network Bridge**: Docker's NAT/proxy layer can interfere with HTTP/2 ALPN negotiation
- **Stability**: HTTP/1.1 with Keep-Alive provides reliable connection pooling
- **Performance**: Still maintains connection pooling for reduced latency (50-70ms after initial connection)

## Protocol Support by Broker

Based on testing (see `test/test_broker_protocol.py`):

| Broker | Protocol | Initial Latency | Reused Connection |
|--------|----------|-----------------|-------------------|
| Upstox | HTTP/2 | ~150ms | ~55ms |
| Zerodha | HTTP/2 | ~95ms | ~45ms |
| Flattrade | HTTP/2 | ~75ms | ~15ms |
| Shoonya | HTTP/2 | ~80ms | ~20ms |
| Alice Blue | HTTP/2 | ~85ms | ~25ms |
| Dhan | HTTP/2 | ~90ms | ~30ms |
| 5Paisa | HTTP/2 | ~200ms | ~30ms |

**Note**: Most brokers use CloudFlare or similar CDNs that provide HTTP/2 at the edge, even if their backends use HTTP/1.1.

## Performance Characteristics

### Connection Lifecycle

#### Native Environment (HTTP/2)
1. **First Request** (~80-150ms):
   - DNS resolution
   - TCP handshake
   - TLS handshake with ALPN
   - HTTP/2 connection setup
   - Request/Response

2. **Subsequent Requests** (~15-45ms):
   - Multiplexed over existing HTTP/2 connection
   - No handshakes needed
   - Header compression (HPACK)

#### Docker Environment (HTTP/1.1)
1. **First Request** (~100-200ms):
   - DNS resolution
   - TCP handshake
   - TLS handshake
   - HTTP/1.1 connection
   - Request/Response

2. **Subsequent Requests** (~50-70ms):
   - Reuses existing connection (Keep-Alive)
   - No handshakes needed
   - Direct request/response

### Latency Comparison

```
Native (HTTP/2):
  First Request:  DNS (10ms) + TCP (20ms) + TLS (40ms) + H2 (5ms) + Request (25ms) = ~100ms
  Reused Request: Request (20ms) = ~20ms

Docker (HTTP/1.1):
  First Request:  DNS (10ms) + TCP (20ms) + TLS (40ms) + HTTP/1.1 (10ms) + Request (50ms) = ~130ms
  Reused Request: Request (50ms) = ~50ms
```

**Performance Impact**: HTTP/2 is 2-3x faster for API calls, but HTTP/1.1 with connection pooling still provides good performance.

## API Usage

### Basic Methods

```python
from utils.httpx_client import get, post, put, delete

# GET request
response = get("https://api.broker.com/positions")

# POST request with JSON body
response = post(
    "https://api.broker.com/orders",
    json={"symbol": "RELIANCE", "qty": 1}
)

# PUT request
response = put(
    "https://api.broker.com/orders/123",
    json={"price": 2500}
)

# DELETE request
response = delete("https://api.broker.com/orders/123")
```

### Direct Client Access

```python
from utils.httpx_client import get_httpx_client

client = get_httpx_client()
response = client.request("GET", url, headers=headers)
```

### Cleanup

```python
from utils.httpx_client import cleanup_httpx_client

# On application shutdown
cleanup_httpx_client()
```

## Logging

The client logs important events:

```python
INFO: Created HTTP client with automatic protocol negotiation
INFO: Request used HTTP/2 - URL: https://api.upstox.com/...
INFO: Closed HTTP client
```

To see which protocol is being used, check your application logs.

## Testing

Three test scripts are provided in the `test/` directory:

### 1. `test_http_protocol.py`
Tests HTTP protocol detection with various configurations.

```bash
cd openalgo
python test/test_http_protocol.py
```

### 2. `test_broker_protocol.py`
Tests major broker APIs to identify their HTTP protocol support.

```bash
cd openalgo
python test/test_broker_protocol.py
```

### 3. `test_flattrade_protocol.py`
Comprehensive test of all broker APIs with performance measurements.

```bash
cd openalgo
python test/test_flattrade_protocol.py
```

## Docker Deployment

### Automatic Environment Detection

The client automatically detects Docker environments by checking:
1. Presence of `/.dockerenv` file
2. `DOCKER_CONTAINER=true` environment variable (set in Dockerfile)

### Docker Configuration

The Dockerfile sets the required environment variable:
```dockerfile
ENV DOCKER_CONTAINER=true
```

This ensures HTTP/1.1 mode is automatically enabled in Docker containers.

### Running in Docker

```bash
# Build the image
docker-compose build

# Run with default settings (HTTP/1.1 in Docker)
docker-compose up
```

## Troubleshooting

### "Illegal Request Line" Error in Docker

**Cause**: HTTP/2 protocol negotiation issues with broker APIs through Docker's network layer.

**Solution**: The client automatically uses HTTP/1.1 in Docker environments. Ensure:
1. `DOCKER_CONTAINER=true` is set in Dockerfile
2. Rebuild the Docker image after updates

### High Latency on First Request

**Expected behavior**. First request includes connection setup. Subsequent requests will be faster.

### Consistent High Latency

Check if:
1. Connection pooling is working (logs should show reuse)
2. Network issues exist
3. Broker API is slow

### HTTP/2 Not Working in Native Environment

The client automatically falls back to HTTP/1.1. No action needed.

### Memory Usage

Connection pools use memory. If concerned:
- Reduce `max_keepalive_connections`
- Reduce `keepalive_expiry`

## Migration Guide

### From Old Code (HTTP/2 only)

```python
# Old - Single protocol
_httpx_client = httpx.Client(
    http2=True,
    timeout=30.0,
    limits=httpx.Limits(
        max_keepalive_connections=10,
        max_connections=20,
        keepalive_expiry=60.0
    )
)
```

### To New Code (Auto-negotiation)

```python
# New - Automatic protocol selection
_httpx_client = httpx.Client(
    http2=True,  # Support HTTP/2
    http1=True,  # Also support HTTP/1.1
    timeout=30.0,
    limits=httpx.Limits(
        max_keepalive_connections=20,  # Increased
        max_connections=50,             # Increased
        keepalive_expiry=120.0         # Increased
    )
)
```

## Best Practices

1. **Don't Create Multiple Clients**: Use the shared client via `get_httpx_client()`
2. **Environment-Aware**: The client automatically adapts to Docker vs native environments
3. **Monitor Logs**: Check which protocol is being used:
   - Native: `"HTTP/2 enabled for optimal performance"`
   - Docker: `"Running in Docker environment - HTTP/2 disabled for compatibility"`
4. **Use Connection Pooling**: Even with HTTP/1.1, connection pooling provides significant performance benefits
5. **Clean Up on Shutdown**: Call `cleanup_httpx_client()` when stopping the application

## Performance Optimization Tips

1. **Batch Operations**: Group API calls to reuse connections
2. **Avoid Frequent Reconnects**: Keep application running
3. **Monitor Logs**: Check which protocol is being used
4. **Test Your Broker**: Run the test scripts to understand your broker's behavior

## Technical Details

### Protocol Negotiation (ALPN)

During TLS handshake:
1. Client advertises: `["h2", "http/1.1"]`
2. Server selects best protocol
3. Connection proceeds with selected protocol
4. httpx remembers protocol per connection

### Connection Pooling

- Connections are kept alive for 120 seconds
- Up to 20 connections stay persistent
- Maximum 50 total connections
- Automatic cleanup of idle connections

### HTTP/2 Benefits (When Available)

- Header compression (HPACK)
- Multiplexing (multiple requests per connection)
- Server push (not used by broker APIs)
- Binary protocol (more efficient)

### HTTP/1.1 with Keep-Alive

- Simple request/response model
- Connection reuse via Keep-Alive
- Text-based protocol
- Widely compatible

## Summary of Environment Differences

| Feature | Native Environment | Docker Environment |
|---------|-------------------|-------------------|
| **Protocol** | HTTP/2 (with HTTP/1.1 fallback) | HTTP/1.1 only |
| **Performance** | 15-45ms (reused connection) | 50-70ms (reused connection) |
| **First Request** | 80-150ms | 100-200ms |
| **Multiplexing** | Yes (HTTP/2) | No |
| **Header Compression** | Yes (HPACK) | No |
| **Connection Pooling** | Yes | Yes |
| **Keep-Alive** | Yes | Yes |
| **Auto-Detection** | N/A | Via DOCKER_CONTAINER env var |

## Conclusion

The current HTTPX client configuration provides:
- **Environment-Aware**: Automatically adapts to Docker vs native deployments
- **Optimal Performance**: 
  - Native: 15-45ms latency with HTTP/2
  - Docker: 50-70ms latency with HTTP/1.1 + connection pooling
- **Universal Compatibility**: Works reliably with all broker APIs
- **Zero Configuration**: No manual protocol selection needed
- **Resource Efficient**: Proper connection pooling and cleanup in both environments

The trade-off between HTTP/2 performance and Docker compatibility is handled automatically, ensuring reliable operation in all deployment scenarios.