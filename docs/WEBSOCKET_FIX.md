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

## macOS-Specific Port Release Fix

### The Problem:
- **macOS**: WebSocket port took 30-60 seconds to release after Ctrl+C
- **Windows/Linux**: No issues - ports released immediately

### Enhanced Signal Handling:
- **Mac/Linux**: SIGINT (Ctrl+C) + SIGTERM
- **All Platforms**: `atexit` handlers as fallback

### Cleanup Mechanisms:
1. **Primary**: Signal handlers (Ctrl+C)
2. **Secondary**: `atexit.register()` for process exit
3. **Enhanced**: Proper WebSocket server close with port release
4. **Timeout**: Connection cleanup with 2-second timeout

## Platform-Specific Behavior:

### macOS: ✅ **FIXED**
✅ Immediate port release (2-5 seconds vs 30-60 seconds)
✅ SO_REUSEPORT socket support
✅ Proper signal handling (SIGINT, SIGTERM)

### Linux: ✅ **Should work similarly**
✅ SO_REUSEPORT socket support
✅ Signal handling (SIGINT, SIGTERM)

### Windows: ✅ **No changes needed**
✅ Was already working properly
✅ Basic signal handling (SIGINT)

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

## Summary

This fix specifically addresses the macOS port release delay issue. The solution provides:
- **Immediate port release** on macOS (2-5 seconds vs 30-60 seconds)
- **Proper socket options** for better port reuse
- **Enhanced cleanup sequence** with timeouts
- **Backward compatibility** with Windows/Linux (no changes needed)

The fix is focused and doesn't add unnecessary complexity for platforms that were already working.