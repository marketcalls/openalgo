# WebSocket Real-Time Execution Engine

## Overview

OpenAlgo now supports real-time order execution and PnL updates using WebSocket market data instead of REST API polling. This provides sub-second latency for order execution and instant PnL updates on the Positions page.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           BROKER WEBSOCKET                                   │
│                    (Real-time market data feed)                              │
└─────────────────────────────────┬───────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         WEBSOCKET PROXY                                      │
│                    (websocket_proxy/server.py)                               │
│  ┌─────────────────┐    ┌──────────────────┐    ┌─────────────────────────┐ │
│  │  ZeroMQ PUB/SUB │───▶│ MarketDataService│───▶│ Backend Subscribers     │ │
│  │  (broker data)  │    │ (data caching)   │    │ - Execution Engine      │ │
│  └─────────────────┘    └──────────────────┘    │ - Position Manager      │ │
│          │                                       │ - RMS (future)          │ │
│          │                                       └─────────────────────────┘ │
│          ▼                                                                   │
│  ┌─────────────────────────────────────────────────────────────────────────┐│
│  │                    Frontend WebSocket Clients                            ││
│  │              (Positions page, WebSocket Test Console)                    ││
│  └─────────────────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────────────────┘
```

## Components

### 1. MarketDataService (`services/market_data_service.py`)

A singleton service that caches real-time market data from the WebSocket proxy and distributes it to backend subscribers.

**Features:**
- Thread-safe data caching with timestamps
- Priority-based subscriber system (CRITICAL, HIGH, NORMAL, LOW)
- Data freshness monitoring
- Health status tracking

**Subscriber Priorities:**
| Priority | Use Case | Processing Order |
|----------|----------|------------------|
| CRITICAL | Order execution engine | First |
| HIGH | Position MTM updates | Second |
| NORMAL | General consumers | Third |
| LOW | Logging, analytics | Last |

### 2. WebSocket Execution Engine (`sandbox/websocket_execution_engine.py`)

Event-driven order execution engine that processes orders immediately when price conditions are met.

**Features:**
- Subscribes to MarketDataService with CRITICAL priority
- Maintains in-memory index of pending orders by symbol
- Sub-second order execution (vs 5-second polling)
- Automatic fallback to polling when WebSocket data is stale

**Order Index Structure:**
```python
# Maps symbol_key -> list of pending order IDs
_pending_orders_index = {
    "NSE:RELIANCE": ["order_001", "order_002"],
    "NSE:TCS": ["order_003"],
    "NFO:NIFTY24JAN22000CE": ["order_004", "order_005"]
}
```

### 3. Position Manager MTM Updates (`sandbox/position_manager.py`)

Real-time Mark-to-Market (MTM) updates for sandbox positions using WebSocket data.

**Data Flow:**
1. Try fetching LTP from MarketDataService cache
2. Check data freshness (< 5 seconds old)
3. If fresh → use WebSocket data for MTM
4. If stale → fallback to REST API (multiquotes)

### 4. Frontend useMarketData Hook (`frontend/src/hooks/useMarketData.ts`)

Reusable React hook for WebSocket market data subscriptions.

**Usage:**
```typescript
const { data, isConnected, isAuthenticated, error } = useMarketData({
  symbols: [
    { symbol: 'RELIANCE', exchange: 'NSE' },
    { symbol: 'TCS', exchange: 'NSE' }
  ],
  mode: 'LTP',
  enabled: true
})

// Access real-time LTP
const reliance = data.get('NSE:RELIANCE')
console.log(reliance?.data?.ltp) // 1424.50
```

### 5. Positions Page Real-Time PnL (`frontend/src/pages/Positions.tsx`)

The Positions page now displays real-time PnL calculated from WebSocket LTP data.

**Features:**
- "Live" badge indicator when WebSocket is connected
- Instant PnL updates (sub-second)
- Same implementation for both Live and Sandbox modes
- Automatic fallback to REST data when WebSocket unavailable

---

## Advantages Over REST Polling

| Aspect | Before | WebSocket (After) |
|--------|--------|-------------------|
| **Order Execution** | Polling every 5 seconds | Sub-second (~100ms) |
| **PnL Updates** | Static (one-time load) | Real-time as prices tick |
| **API Load** | Continuous REST requests | Event-driven, no polling |
| **CPU Usage** | Higher (constant requests) | Lower (push-based) |
| **Network Traffic** | High (repeated full payloads) | Low (incremental updates) |
| **Order Fill** | Batch check every 5 seconds | Immediate on price match |
| **Scalability** | Limited by API rate limits | Handles 1000+ symbols |

### Order Execution Latency Comparison

```
REST Polling:
┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐
│ Poll 1  │    │ Poll 2  │    │ Poll 3  │    │ Poll 4  │
│ t=0s    │    │ t=5s    │    │ t=10s   │    │ t=15s   │
└─────────┘    └─────────┘    └─────────┘    └─────────┘
                    ▲
                    │ Price hits limit at t=6s
                    │ Order executes at t=10s (4 second delay!)

WebSocket:
┌──────────────────────────────────────────────────────────┐
│ Continuous stream: t=0s ───────────────────────▶ t=15s  │
│                              ▲                          │
│                              │ Price hits limit at t=6s │
│                              │ Order executes at t=6.1s │
│                              │ (100ms delay!)           │
└──────────────────────────────────────────────────────────┘
```

---

## Fallback Mechanism

The system is designed with automatic fallback to ensure order execution continues even when WebSocket is unavailable.

### Backend Fallback (Execution Engine)

```
┌─────────────────────────────────────────────────────────────┐
│                    STARTUP DECISION                          │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  Is WebSocket proxy healthy?                                 │
│       │                                                      │
│       ├── YES ──▶ Start WebSocket Execution Engine           │
│       │           (with health monitoring)                   │
│       │                                                      │
│       └── NO ───▶ Start Polling Execution Engine             │
│                   (5-second interval)                        │
│                                                              │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                    RUNTIME FALLBACK                          │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  Health Monitor (every 5 seconds):                          │
│       │                                                      │
│       ├── Data fresh (< 30s) ──▶ Continue WebSocket mode    │
│       │                                                      │
│       └── Data stale (> 30s) ──▶ Start polling fallback     │
│                                   │                          │
│                                   ▼                          │
│                          ┌────────────────┐                  │
│                          │ Polling thread │                  │
│                          │ runs parallel  │                  │
│                          └────────────────┘                  │
│                                   │                          │
│           WebSocket recovers ◀────┘                          │
│                   │                                          │
│                   ▼                                          │
│           Stop polling fallback                              │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### Backend Fallback (Position MTM)

```python
# In position_manager.py
def _update_positions_mtm(self):
    # Step 1: Try WebSocket data first
    ws_quotes = self._fetch_quotes_from_websocket(symbols_list)

    # Step 2: Find symbols without fresh WebSocket data
    missing_symbols = [s for s in symbols_list if s not in ws_quotes]

    # Step 3: Fallback to REST API for missing symbols
    if missing_symbols:
        rest_quotes = self._fetch_quotes_from_rest(missing_symbols)
        ws_quotes.update(rest_quotes)

    # Step 4: Update MTM with combined data
    self._apply_mtm_updates(ws_quotes)
```

### Frontend Fallback (Positions Page)

```typescript
// In Positions.tsx
const enhancedPositions = useMemo(() => {
  return positions.map((pos) => {
    const key = `${pos.exchange}:${pos.symbol}`
    const wsData = marketData.get(key)

    // Only use WebSocket data if fresh (< 5 seconds)
    if (wsData?.data?.ltp && wsData.lastUpdate &&
        Date.now() - wsData.lastUpdate < 5000) {
      // Calculate PnL with real-time LTP
      return { ...pos, ltp: wsData.data.ltp, pnl: calculatePnl(...) }
    }

    // Fallback: Use REST API data from position fetch
    return pos
  })
}, [positions, marketData])

// REST polling interval adjusts based on WebSocket status
const pollInterval = wsConnected ? 30000 : 10000  // 30s vs 10s
```

### Fallback Scenarios

| Scenario | Detection | Fallback Action |
|----------|-----------|-----------------|
| WebSocket proxy not running | Startup health check | Use polling engine |
| WebSocket disconnected | Health monitor (30s stale) | Start parallel polling |
| After market hours | No new data updates | Automatic REST fallback |
| Market holidays | No new data updates | Automatic REST fallback |
| Network issues | Connection error | Auto-reconnect + polling |

---

## Reconnection Mechanism

The system automatically recovers when WebSocket connection is restored.

### Frontend Reconnection

```typescript
// In useMarketData.ts
socket.onclose = (event) => {
  setIsConnected(false)
  setIsAuthenticated(false)
  subscribedSymbolsRef.current.clear()

  // Auto-reconnect after 3 seconds (unless clean close)
  if (autoReconnect && !event.wasClean && enabled) {
    reconnectTimeoutRef.current = setTimeout(connect, 3000)
  }
}
```

**Reconnection Flow:**
1. WebSocket disconnects unexpectedly
2. Wait 3 seconds
3. Reconnect to WebSocket server
4. Re-authenticate with API key
5. Re-subscribe to all symbols
6. Resume real-time data flow

### Backend Reconnection

The backend uses a **stateless per-check** design, meaning it doesn't maintain a "we're in fallback mode" state. Each data fetch independently checks freshness:

```python
# Every MTM update cycle (independent check)
age = current_time - last_update
if age <= WEBSOCKET_DATA_MAX_AGE:  # 5 seconds
    # Use WebSocket data
else:
    # Use REST fallback
```

**Recovery Timeline:**

```
Timeline:
t=0s    WebSocket connected, using WS data
t=10s   WebSocket disconnects
t=15s   Data becomes stale, fallback to REST
t=20s   Polling fallback active
...
t=60s   WebSocket reconnects
t=61s   New data arrives, last_update refreshed
t=62s   Next check: age = 1s < 5s, use WebSocket data
t=62s   Automatic recovery complete!
```

### Execution Engine Recovery

The WebSocket execution engine has explicit recovery handling:

```python
# Health monitor thread (runs every 5 seconds)
def monitor():
    while self._running:
        is_fresh = self.market_data_service.is_data_fresh(max_age_seconds=30)

        if not is_fresh and not self._fallback_running:
            # Start polling fallback
            self._start_fallback()

        elif is_fresh and self._fallback_running:
            # WebSocket recovered - stop fallback
            logger.info("WebSocket data recovered, stopping polling fallback")
            self._stop_fallback()

        time.sleep(5)
```

---

## Configuration

The WebSocket execution engine is enabled by default. No configuration required.

### Optional Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SANDBOX_ENGINE_TYPE` | `websocket` | Engine type: `websocket` or `polling` |
| `SANDBOX_ENGINE_FALLBACK` | `true` | Enable automatic fallback to polling |

### Data Freshness Thresholds

| Component | Threshold | Purpose |
|-----------|-----------|---------|
| Position MTM | 5 seconds | Use WebSocket data if fresh |
| Execution Engine Health | 30 seconds | Trigger fallback if stale |
| Frontend Display | 5 seconds | Show real-time badge |

---

## Files Reference

| File | Purpose |
|------|---------|
| `services/market_data_service.py` | Singleton market data cache and subscriber management |
| `sandbox/websocket_execution_engine.py` | Event-driven order execution engine |
| `sandbox/execution_thread.py` | Engine type selection and lifecycle management |
| `sandbox/position_manager.py` | MTM updates with WebSocket-first approach |
| `websocket_proxy/server.py` | Integration point feeding MarketDataService |
| `frontend/src/hooks/useMarketData.ts` | Reusable React hook for WebSocket data |
| `frontend/src/pages/Positions.tsx` | Real-time PnL display |

---

## Troubleshooting

### WebSocket Not Connecting

1. Verify WebSocket proxy is running:
   ```bash
   # Check if websocket_proxy process is active
   ps aux | grep websocket_proxy
   ```

2. Check WebSocket URL in `.env`:
   ```
   WEBSOCKET_URL=ws://127.0.0.1:8765
   ```

3. Verify API key exists (required for authentication)

### Orders Not Executing

1. Check execution engine status in logs:
   ```
   Sandbox Execution Engine: WebSocket execution engine started
   ```

2. Verify market data is flowing:
   ```
   MarketDataService: Processing market data for NSE:RELIANCE
   ```

3. Check if fallback is active:
   ```
   WebSocket data is stale, starting polling fallback
   ```

### PnL Not Updating in Real-Time

1. Check "Live" badge on Positions page (should be green when connected)
2. Verify symbols are subscribed in browser console
3. Check WebSocket connection status in Network tab

---

## Performance Metrics

Based on production testing:

| Metric | Value |
|--------|-------|
| Order execution latency | ~100ms (previously 5 seconds) |
| PnL updates | Real-time (previously static, one-time load) |
| Memory overhead | ~50KB per 100 symbols |
| CPU usage reduction | ~40% vs polling |
| Network bandwidth reduction | ~80% vs polling |
