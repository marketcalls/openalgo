# Essential .env Changes for Docker Setup (Without Eventlet)

## 1. Flask Host Configuration
```bash
# Change from 127.0.0.1 to 0.0.0.0 to allow external connections
FLASK_HOST_IP='0.0.0.0'  # Required for Docker
FLASK_PORT='5000'
```

## 2. WebSocket Configuration
```bash
# WebSocket server must bind to 0.0.0.0 inside Docker
WEBSOCKET_HOST='0.0.0.0'  # Required for Docker
WEBSOCKET_PORT='8765'
WEBSOCKET_URL='ws://localhost:8765'  # URL for clients connecting from host
```

## 3. ZeroMQ Configuration
```bash
# ZMQ must also bind to 0.0.0.0 for internal communication
ZMQ_HOST='0.0.0.0'  # Required for Docker
ZMQ_PORT='5555'
```

## Summary of Changes

### From (Local Development):
```bash
FLASK_HOST_IP='127.0.0.1'
WEBSOCKET_HOST='127.0.0.1'
ZMQ_HOST='127.0.0.1'
```

### To (Docker):
```bash
FLASK_HOST_IP='0.0.0.0'
WEBSOCKET_HOST='0.0.0.0'
ZMQ_HOST='0.0.0.0'
```

## Why These Changes?

1. **0.0.0.0 vs 127.0.0.1**: 
   - `127.0.0.1` only allows connections from within the container
   - `0.0.0.0` allows connections from outside the container (host machine)

2. **WEBSOCKET_URL**: 
   - Remains as `ws://localhost:8765` because this is the URL clients use from the host machine
   - Docker maps the container's port to the host's localhost

3. **No other changes needed**: 
   - All other settings (API keys, database URLs, etc.) remain the same
   - The docker-compose.yaml already maps the ports correctly

## Verification

After making these changes and rebuilding Docker:

1. Access the web interface: http://localhost:5000
2. WebSocket connections will work on: ws://localhost:8765
3. Test with: `python test/simple_ltp_test.py`