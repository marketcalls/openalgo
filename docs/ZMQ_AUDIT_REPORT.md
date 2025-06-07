# ZMQ and WebSocket Implementation Audit Report

## Executive Summary

This audit examines the ZMQ (ZeroMQ) and WebSocket implementation in OpenAlgo, specifically addressing the multi-instance port conflict issue and identifying performance improvement opportunities. The analysis reveals that while the system has implemented dynamic port allocation for ZMQ, there's a critical architectural issue where the WebSocket proxy server is hardcoded to connect to port 5555, preventing proper multi-instance operation.

## Architecture Overview

### Current Implementation

1. **WebSocket Proxy Server** (`websocket_proxy/server.py`):
   - Runs on configurable port (default 8765, can be 8766 for second instance)
   - **CRITICAL ISSUE**: Hardcoded to connect to ZMQ port 5555 (line 68)
   - Handles client authentication and subscription management
   - Distributes market data from broker adapters to clients

2. **Broker Adapters** (`base_adapter.py`, `angel_adapter.py`, `zerodha_adapter.py`):
   - Each adapter publishes to ZMQ on dynamically allocated ports
   - Default port is 5555, falls back to dynamic allocation if occupied
   - Maintains a class-level registry of bound ports to prevent conflicts
   - Recent fix (commit 1bbcbce) implemented dynamic port binding for Zerodha

3. **ZMQ Communication**:
   - Publishers (Broker Adapters): Bind to ports starting from 5555
   - Subscriber (WebSocket Proxy): Connects to tcp://localhost:5555 only
   - Topic-based filtering using format: `EXCHANGE_SYMBOL_MODE`

## Root Cause Analysis

### Multi-Instance Port Conflict Issue

**Problem**: When running two OpenAlgo instances:
- Instance 1: Flask on 5000, WebSocket on 8765, expects ZMQ on 5555
- Instance 2: Flask on 5001, WebSocket on 8766, expects ZMQ on 5556

**Current Behavior**:
1. First broker adapter binds to port 5555 successfully
2. Second broker adapter detects 5555 is occupied and binds to a dynamic port (e.g., 5556+)
3. **BOTH WebSocket proxy servers connect to port 5555** (hardcoded)
4. Second instance receives no data because its adapter publishes to a different port

**Code Evidence**:
```python
# websocket_proxy/server.py, line 68
self.socket.connect("tcp://localhost:5555")  # Connect to broker adapter publisher
```

## Identified Issues

### 1. Hardcoded ZMQ Subscriber Port
The WebSocket proxy server is hardcoded to connect to port 5555, making it impossible for multiple instances to connect to their respective broker adapters.

### 2. No Discovery Mechanism
There's no mechanism for the WebSocket proxy to discover which port its broker adapter is using.

### 3. Multiple Adapters Per Instance
The current architecture allows multiple broker adapters per instance, but the proxy can only connect to one ZMQ port.

### 4. Resource Cleanup
While the Zerodha adapter has proper cleanup in `disconnect()` and `__del__`, the cleanup may not always execute during abnormal terminations.

## Performance Analysis

### Current Performance Characteristics

1. **ZMQ Pub/Sub Pattern**:
   - Efficient for one-to-many distribution
   - Zero-copy message passing
   - Minimal latency overhead

2. **Topic-Based Filtering**:
   - Efficient subscription filtering at ZMQ level
   - Reduces unnecessary message processing

3. **Async WebSocket Handling**:
   - Non-blocking client connections
   - Efficient event loop usage

### Performance Improvement Opportunities

1. **Message Batching**:
   - Current: Each tick published individually
   - Improvement: Batch multiple ticks in a single ZMQ message

2. **Connection Pooling**:
   - Current: Single ZMQ socket per adapter
   - Improvement: Multiple sockets for parallel publishing

3. **Binary Serialization**:
   - Current: JSON serialization (text-based)
   - Improvement: Use MessagePack or Protocol Buffers for smaller payloads

4. **Memory Optimization**:
   - Current: Full tick data transformation for all modes
   - Improvement: Lazy transformation based on actual subscriptions

## Recommended Solutions

### Solution 1: Dynamic Port Discovery (Recommended)

Implement a discovery mechanism where broker adapters register their ZMQ ports, and the WebSocket proxy discovers the correct port to connect to.

**Implementation Steps**:
1. Add environment variable `ZMQ_PUB_PORT` for each instance
2. Modify WebSocket proxy to read this configuration
3. Update broker adapters to publish their bound port

**Code Changes Required**:

1. In `.env` file:
```env
# Instance 1
ZMQ_PUB_PORT='5555'

# Instance 2  
ZMQ_PUB_PORT='5556'
```

2. In `websocket_proxy/server.py`:
```python
# Line 68, replace hardcoded port
zmq_port = os.getenv('ZMQ_PUB_PORT', '5555')
self.socket.connect(f"tcp://localhost:{zmq_port}")
```

3. In `base_adapter.py`:
```python
# After binding, set environment variable
os.environ['ACTUAL_ZMQ_PORT'] = str(self.zmq_port)
```

### Solution 2: Port Registry Service

Implement a lightweight registry service that tracks adapter-to-port mappings.

**Advantages**:
- Supports multiple adapters per instance
- Dynamic adapter discovery
- Better fault tolerance

**Implementation**:
- Use a shared SQLite database or Redis
- Adapters register their ports on startup
- Proxy queries registry for available adapters

### Solution 3: IPC Socket Instead of TCP

Use ZMQ IPC (Inter-Process Communication) sockets with unique names per instance.

**Implementation**:
```python
# Adapter
self.socket.bind(f"ipc:///tmp/openalgo_{instance_id}.ipc")

# Proxy
self.socket.connect(f"ipc:///tmp/openalgo_{instance_id}.ipc")
```

## Performance Optimization Recommendations

### 1. Implement Message Batching

```python
class BatchedPublisher:
    def __init__(self, batch_size=10, batch_timeout=0.1):
        self.batch = []
        self.batch_size = batch_size
        self.batch_timeout = batch_timeout
        self.last_publish = time.time()
    
    def publish(self, topic, data):
        self.batch.append((topic, data))
        if len(self.batch) >= self.batch_size or \
           time.time() - self.last_publish > self.batch_timeout:
            self._flush_batch()
    
    def _flush_batch(self):
        if self.batch:
            # Send all messages in one ZMQ frame
            self.socket.send_multipart([
                b"BATCH",
                msgpack.packb(self.batch)
            ])
            self.batch = []
            self.last_publish = time.time()
```

### 2. Use Binary Serialization

```python
# Replace JSON with MessagePack
import msgpack

# In base_adapter.py
def publish_market_data(self, topic, data):
    self.socket.send_multipart([
        topic.encode('utf-8'),
        msgpack.packb(data)  # Binary serialization
    ])

# In server.py
[topic, data] = await self.socket.recv_multipart()
market_data = msgpack.unpackb(data, raw=False)
```

### 3. Implement Connection Multiplexing

```python
class MultiplexedAdapter(BaseBrokerWebSocketAdapter):
    def __init__(self, num_publishers=3):
        super().__init__()
        self.publishers = []
        for i in range(num_publishers):
            socket = self.context.socket(zmq.PUB)
            port = self._bind_to_available_port(socket)
            self.publishers.append((socket, port))
    
    def publish_market_data(self, topic, data):
        # Round-robin distribution
        publisher = self.publishers[hash(topic) % len(self.publishers)]
        publisher[0].send_multipart([...])
```

### 4. Optimize WebSocket Proxy Memory Usage

```python
# Lazy transformation based on subscription mode
def _normalize_market_data(self, message, mode):
    if mode == 1:  # LTP only
        return {'ltp': message.get('last_traded_price', 0) / 100}
    elif mode == 2:  # Quote
        # Only extract quote fields
        pass
    # ... rest of implementation
```

## Implementation Priority

1. **High Priority** (Immediate):
   - Fix hardcoded ZMQ port issue (Solution 1)
   - Add proper error handling for port conflicts

2. **Medium Priority** (Next Sprint):
   - Implement message batching
   - Add connection health monitoring
   - Improve resource cleanup

3. **Low Priority** (Future):
   - Binary serialization
   - Connection multiplexing
   - Advanced monitoring and metrics

## Testing Recommendations

1. **Multi-Instance Testing**:
   ```bash
   # Terminal 1
   FLASK_PORT=5000 WEBSOCKET_PORT=8765 ZMQ_PUB_PORT=5555 python app.py
   
   # Terminal 2
   FLASK_PORT=5001 WEBSOCKET_PORT=8766 ZMQ_PUB_PORT=5556 python app.py
   ```

2. **Load Testing**:
   - Simulate 1000+ concurrent WebSocket clients
   - Measure message latency and throughput
   - Monitor memory usage under load

3. **Fault Tolerance Testing**:
   - Test adapter crashes and reconnections
   - Verify port cleanup after abnormal termination
   - Test network interruptions

## Conclusion

The OpenAlgo WebSocket implementation is well-architected with good separation of concerns and error handling. However, the hardcoded ZMQ port in the WebSocket proxy prevents proper multi-instance operation. The recommended immediate fix is to implement dynamic port configuration (Solution 1), which requires minimal code changes and maintains backward compatibility.

For performance optimization, message batching and binary serialization offer the best return on investment, potentially reducing network overhead by 50-70% for high-frequency data streams.

## Appendix: Quick Fix Implementation

For immediate resolution, apply this patch:

```python
# websocket_proxy/server.py
# Line 68, replace:
self.socket.connect("tcp://localhost:5555")

# With:
zmq_port = int(os.getenv('ZMQ_PUB_PORT', '5555'))
self.socket.connect(f"tcp://localhost:{zmq_port}")
logger.info(f"WebSocket proxy connecting to ZMQ publisher on port {zmq_port}")
```

Then update your `.env` files:
- Instance 1: Add `ZMQ_PUB_PORT=5555`
- Instance 2: Add `ZMQ_PUB_PORT=5556`

This ensures each WebSocket proxy connects to its corresponding broker adapter's ZMQ publisher port.