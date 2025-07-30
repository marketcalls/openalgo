# WebSocket macOS Fix Guide

## Issue
WebSockets work on Windows but fail on macOS due to IPv4/IPv6 dual-stack handling differences.

## Root Cause
- macOS resolves `localhost` to both `::1` (IPv6) and `127.0.0.1` (IPv4)
- The code uses IPv4-only sockets (`AF_INET`) but checks ports using `localhost`
- This creates a mismatch between port checking and actual binding

## Solution Applied
Changed all `localhost` references to explicit IPv4 address `127.0.0.1` in:
1. `websocket_proxy/port_check.py`
2. `websocket_proxy/server.py`

## Environment Configuration
Update your `.env` file with these settings:

```bash
# WebSocket Configuration - Use explicit IPv4 addresses for macOS compatibility
WEBSOCKET_HOST=127.0.0.1
WEBSOCKET_PORT=8765

# ZeroMQ Configuration
ZMQ_HOST=127.0.0.1
ZMQ_PORT=5555
```

## Cross-Platform Cleanup Enhancement

### Enhanced Signal Handling:
- **Mac/Linux**: SIGINT (Ctrl+C) + SIGTERM
- **Windows**: SIGINT + Console Control Events (if win32api available)
- **All Platforms**: `atexit` handlers as fallback

### Cleanup Mechanisms:
1. **Primary**: Signal handlers catch Ctrl+C
2. **Secondary**: `atexit.register()` for process exit
3. **Tertiary**: Event loop cleanup with error handling
4. **Last Resort**: Force resource nullification

## Platform-Specific Behavior:

### macOS:
✅ Full signal support (SIGINT, SIGTERM)
✅ Proper port release
✅ Thread cleanup

### Linux:
✅ Full signal support (SIGINT, SIGTERM)  
✅ Proper port release
✅ Thread cleanup

### Windows:
✅ SIGINT support
⚠️ No SIGTERM (not available)
✅ Console control events (if win32api installed)
✅ Fallback to atexit handlers

## Testing
After making these changes:

1. Start OpenAlgo: `python app.py`
2. Press Ctrl+C to stop
3. Restart immediately: `python app.py`
4. Should start without "port in use" errors

## Troubleshooting

If port is still in use after Ctrl+C:
```bash
# Check what's using the port
lsof -ti:8765

# Kill the process (Mac/Linux)
lsof -ti:8765 | xargs kill -9

# Windows equivalent
netstat -ano | findstr :8765
taskkill /PID <PID> /F
```

## Alternative Solutions
If cleanup still fails:

1. **Add delay**: Wait 2-3 seconds between stop/start
2. **Use different port**: Change `WEBSOCKET_PORT` in .env
3. **Restart system**: As last resort for stuck ports

## Dependencies
For best Windows support, install:
```bash
pip install pywin32  # For win32api console handlers
```

The fix provides multi-layered cleanup ensuring port release across all platforms.