# WebSocket Connection Manager

## Product Requirements Document (PRD)

### Overview

**Feature:** Shared WebSocket Connection Manager
**Issue:** [#848](https://github.com/marketcalls/openalgo/issues/848)
**Status:** Implemented
**Release:** v2.x

### Problem Statement

The OpenAlgo React frontend requires real-time market data across multiple pages and components. Previously, each component that needed market data created its own WebSocket connection, leading to:

| Problem | Impact |
|---------|--------|
| Multiple WebSocket connections | 3-4 connections per user session |
| Redundant authentication | Each connection authenticates separately |
| Duplicate subscriptions | Same symbol subscribed multiple times |
| Resource waste | Server handles N connections instead of 1 |
| Inconsistent state | Each component manages its own connection lifecycle |

**Example of the problem:**
```
Holdings page    → WebSocket #1 → Subscribe RELIANCE, TCS
Positions page   → WebSocket #2 → Subscribe RELIANCE, INFY
PlaceOrderDialog → WebSocket #3 → Subscribe RELIANCE
OptionChain      → WebSocket #4 → Subscribe NIFTY options (50+ symbols)
```
Result: 4 connections, 4 authentications, RELIANCE subscribed 3 times.

### Goals

1. **Single Connection:** One WebSocket connection shared across all components
2. **Ref-counted Subscriptions:** Subscribe to each symbol only once, regardless of how many components need it
3. **Centralized Lifecycle:** Single point of control for connect/disconnect/pause/resume
4. **Backward Compatibility:** Existing hooks (`useMarketData`, `useLivePrice`, `useLiveQuote`) continue to work with unchanged API
5. **Resource Optimization:** Pause connection when tab is hidden to save bandwidth

### Non-Goals

- Persisting WebSocket connection across page refreshes (requires Service Workers)
- Multi-tab connection sharing (out of scope)
- Modifying the WebSocket server protocol

### REST API Fallback

When WebSocket connections fail (e.g., after market hours when the broker WebSocket is unavailable), the system automatically falls back to REST API polling:

| Scenario | Behavior |
|----------|----------|
| WebSocket connects successfully | Real-time data via WebSocket |
| WebSocket fails 3 consecutive times | Automatic switch to REST API polling |
| REST API polling | Fetches `/api/v1/multiquotes` every 5 seconds |
| WebSocket restored | Automatic switch back to WebSocket |

### Success Metrics

| Metric | Before | After | Target |
|--------|--------|-------|--------|
| WebSocket connections per session | 3-4 | 1 | 1 |
| Authentication requests | 3-4 | 1 | 1 |
| Duplicate symbol subscriptions | Yes | No | No |
| Memory usage (callbacks) | N × data | 1 × data | Reduced |

### User Stories

1. **As a trader**, I want real-time prices on Holdings and Positions pages without creating multiple server connections.

2. **As a trader**, I want the WebSocket to pause when I switch to another browser tab to save bandwidth.

3. **As a trader**, I want the connection to resume automatically when I return to the OpenAlgo tab.

4. **As a developer**, I want to use the same `useMarketData` hook API without worrying about connection management.

---

## Technical Design Document

### Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                            App.tsx                                   │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │                        Providers.tsx                           │  │
│  │  ┌─────────────────────────────────────────────────────────┐  │  │
│  │  │                  MarketDataProvider                      │  │  │
│  │  │         (React Context + Visibility Handling)            │  │  │
│  │  │                         │                                │  │  │
│  │  │                         ▼                                │  │  │
│  │  │              MarketDataManager (Singleton)               │  │  │
│  │  │                         │                                │  │  │
│  │  │                         ▼                                │  │  │
│  │  │              Single WebSocket to :8765                   │  │  │
│  │  └─────────────────────────────────────────────────────────┘  │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                                                                      │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────────┐    │
│  │ Holdings │  │Positions │  │  Order   │  │   OptionChain    │    │
│  │          │  │          │  │  Dialog  │  │                  │    │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────────┬─────────┘    │
│       │             │             │                  │              │
│       ▼             ▼             ▼                  ▼              │
│  useLivePrice  useLivePrice  useLiveQuote   useOptionChainLive     │
│       │             │             │                  │              │
│       └─────────────┴─────────────┴──────────────────┘              │
│                              │                                       │
│                              ▼                                       │
│                       useMarketData                                  │
│                              │                                       │
│                              ▼                                       │
│                    MarketDataManager.subscribe()                     │
└─────────────────────────────────────────────────────────────────────┘
```

### Component Design

#### 1. MarketDataManager (Singleton)

**Location:** `src/lib/MarketDataManager.ts`

**Purpose:** Centralized WebSocket connection and subscription management.

**Design Pattern:** Singleton with ref-counted subscriptions and callback registry.

```typescript
class MarketDataManager {
  // Singleton instance
  private static instance: MarketDataManager | null = null

  // WebSocket connection
  private socket: WebSocket | null = null

  // Subscriptions with reference counting
  // Key: "EXCHANGE:SYMBOL:MODE" (e.g., "NSE:RELIANCE:LTP")
  private subscriptions: Map<string, SubscriptionEntry> = new Map()

  // Cached market data for immediate delivery to new subscribers
  // Key: "EXCHANGE:SYMBOL" (e.g., "NSE:RELIANCE")
  private dataCache: Map<string, SymbolData> = new Map()

  // Connection state listeners
  private stateListeners: Set<StateListener> = new Set()
}
```

**Key Methods:**

| Method | Purpose |
|--------|---------|
| `getInstance()` | Get singleton instance |
| `subscribe(symbol, exchange, mode, callback)` | Subscribe to market data, returns unsubscribe function |
| `connect()` | Establish WebSocket connection |
| `disconnect()` | Close connection |
| `pauseConnection()` | Close connection but keep subscriptions in memory |
| `resumeConnection()` | Reconnect and resubscribe all symbols |
| `addStateListener(listener)` | Listen for connection state changes |
| `getCachedData(symbol, exchange)` | Get cached data for immediate display |

**Subscription Reference Counting:**

```
Component A subscribes to RELIANCE
  └─► subscriptions["NSE:RELIANCE:LTP"] = { refCount: 1, callbacks: [A] }
  └─► WebSocket: SUBSCRIBE RELIANCE

Component B subscribes to RELIANCE
  └─► subscriptions["NSE:RELIANCE:LTP"] = { refCount: 2, callbacks: [A, B] }
  └─► WebSocket: (no message - already subscribed)

Component A unsubscribes
  └─► subscriptions["NSE:RELIANCE:LTP"] = { refCount: 1, callbacks: [B] }
  └─► WebSocket: (no message - still has subscribers)

Component B unsubscribes
  └─► subscriptions["NSE:RELIANCE:LTP"] = (deleted)
  └─► WebSocket: UNSUBSCRIBE RELIANCE
```

#### 2. MarketDataContext (React Context)

**Location:** `src/contexts/MarketDataContext.tsx`

**Purpose:** Provide MarketDataManager to React component tree with centralized visibility handling.

**Key Features:**
- Wraps MarketDataManager singleton
- Handles tab visibility (pause after 5s hidden, resume on visible)
- Exposes connection state to all children

```typescript
interface MarketDataContextValue {
  manager: MarketDataManager
  connectionState: ConnectionState
  isConnected: boolean
  isAuthenticated: boolean
  isPaused: boolean
  isFallbackMode: boolean  // NEW: true when using REST API polling
  error: string | null
  subscribe: (symbol, exchange, mode, callback) => () => void
  getCachedData: (symbol, exchange) => SymbolData | undefined
  connect: () => Promise<void>
  disconnect: () => void
}
```

#### 3. useMarketData Hook (Refactored)

**Location:** `src/hooks/useMarketData.ts`

**Purpose:** React hook for subscribing to market data (backward-compatible API).

**Before Refactor:** ~464 lines, manages own WebSocket
**After Refactor:** ~150 lines, delegates to MarketDataManager

**API (unchanged):**
```typescript
function useMarketData({
  symbols: Array<{ symbol: string; exchange: string }>,
  mode?: 'LTP' | 'Quote' | 'Depth',
  enabled?: boolean,
}): {
  data: Map<string, SymbolData>,
  isConnected: boolean,
  isAuthenticated: boolean,
  isConnecting: boolean,
  isPaused: boolean,
  isFallbackMode: boolean,  // NEW: true when using REST API polling
  error: string | null,
  connect: () => Promise<void>,
  disconnect: () => void,
}
```

### State Machine

```
                                    ┌─────────────┐
                                    │ disconnected│◄──────────────────┐
                                    └──────┬──────┘                   │
                                           │                          │
                                    connect()                         │
                                           │                          │
                                           ▼                          │
                                    ┌─────────────┐                   │
                                    │ connecting  │                   │
                                    └──────┬──────┘                   │
                                           │                          │
                                    socket.onopen                     │
                                           │                          │
                                           ▼                          │
                                    ┌─────────────┐                   │
                                    │  connected  │                   │
                                    └──────┬──────┘                   │
                                           │                          │
                                    send auth                    disconnect()
                                           │                     or error
                                           ▼                          │
                                    ┌──────────────┐                  │
                                    │authenticating│                  │
                                    └──────┬───────┘                  │
                                           │                          │
                                    auth success                      │
                                           │                          │
                                           ▼                          │
┌────────┐  pauseConnection()      ┌──────────────┐                   │
│ paused │◄────────────────────────│authenticated │───────────────────┘
└───┬────┘                         └──────────────┘
    │
    │ resumeConnection()
    │
    └──────────────────────────────► connecting
```

### REST API Fallback Mode

When WebSocket connections fail repeatedly (e.g., after market hours), the system automatically switches to REST API polling:

```
WebSocket Connection Attempt
           │
     Connection fails
           │
           ▼
┌──────────────────┐
│ Increment failure│
│ counter          │
└────────┬─────────┘
         │
         ├───── failures < 3 ──────► Retry WebSocket
         │
         └───── failures >= 3
                     │
                     ▼
          ┌─────────────────┐
          │ Enable Fallback │
          │    Mode         │
          └────────┬────────┘
                   │
                   ▼
          ┌─────────────────┐
          │ Fetch API Key   │
          │ from server     │
          └────────┬────────┘
                   │
                   ▼
          ┌─────────────────┐
          │ Start polling   │
          │ /api/v1/multi   │
          │ quotes (5s)     │
          └────────┬────────┘
                   │
     ┌─────────────┴─────────────┐
     │                           │
WebSocket restored        Continue polling
     │                           │
     ▼                           ▼
┌─────────────────┐    ┌─────────────────┐
│ Disable fallback│    │ Update market   │
│ Stop polling    │    │ data cache      │
│ Reset failures  │    │ Notify callbacks│
└─────────────────┘    └─────────────────┘
```

**Key behaviors:**
- **Trigger:** 3 consecutive WebSocket connection failures OR max reconnect attempts reached
- **Polling interval:** 5 seconds (configurable via `setFallbackPollingRate()`)
- **API endpoint:** `/api/v1/multiquotes` with all subscribed symbols
- **Auto-recovery:** When WebSocket successfully reconnects, fallback mode is automatically disabled

### Data Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                      WebSocket Server :8765                      │
└─────────────────────────────────┬───────────────────────────────┘
                                  │
                          market_data message
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────┐
│                      MarketDataManager                           │
│                                                                  │
│  1. Parse message: { symbol: "RELIANCE", exchange: "NSE", ... } │
│  2. Update dataCache["NSE:RELIANCE"]                            │
│  3. Find subscriptions for NSE:RELIANCE                         │
│  4. Call each callback with updated data                        │
│                                                                  │
└──────────────┬─────────────────┬─────────────────┬──────────────┘
               │                 │                 │
               ▼                 ▼                 ▼
        ┌──────────┐      ┌──────────┐      ┌──────────┐
        │ Holdings │      │ Positions│      │  Order   │
        │ callback │      │ callback │      │  Dialog  │
        │          │      │          │      │ callback │
        └──────────┘      └──────────┘      └──────────┘
               │                 │                 │
               ▼                 ▼                 ▼
        setMarketData()   setMarketData()   setMarketData()
               │                 │                 │
               ▼                 ▼                 ▼
          React re-render with new LTP values
```

### Visibility Handling

**Purpose:** Save bandwidth and server resources when user isn't viewing the page.

**Flow:**
```
Tab Hidden
    │
    ▼
Start 5-second timer
    │
    ├─► Tab Visible before 5s → Cancel timer, no action
    │
    └─► Still hidden after 5s
            │
            ▼
        pauseConnection()
            │
            ├─► Close WebSocket
            └─► Keep subscriptions in memory
                    │
                    ▼
                Tab Visible
                    │
                    ▼
                resumeConnection()
                    │
                    ├─► Create new WebSocket
                    ├─► Authenticate
                    └─► Resubscribe all symbols
```

**Why 5-second delay?**
- Prevents unnecessary disconnect for quick tab switches
- User might switch tabs briefly to check something
- Reconnection has overhead (auth, resubscribe)

### Connection Guard

**Problem:** Multiple components calling `connect()` simultaneously could create race conditions.

**Solution:** Comprehensive state checking before creating new connection:

```typescript
async connect(): Promise<void> {
  // Guard against multiple connections
  if (
    this.socket?.readyState === WebSocket.OPEN ||
    this.socket?.readyState === WebSocket.CONNECTING ||
    this.connectionState === 'connecting' ||
    this.connectionState === 'connected' ||
    this.connectionState === 'authenticating' ||
    this.connectionState === 'authenticated'
  ) {
    return  // Already connected or connecting
  }

  this.setConnectionState('connecting')
  // ... proceed with connection
}
```

---

## Implementation Details

### Files Created

| File | Purpose |
|------|---------|
| `src/lib/MarketDataManager.ts` | Singleton WebSocket manager |
| `src/contexts/MarketDataContext.tsx` | React context and provider |

### Files Modified

| File | Change |
|------|--------|
| `src/app/providers.tsx` | Added `<MarketDataProvider>` |
| `src/hooks/useMarketData.ts` | Refactored to use MarketDataManager |

### Files Unchanged

| File | Reason |
|------|--------|
| `src/hooks/useLivePrice.ts` | Uses useMarketData internally (API unchanged) |
| `src/hooks/useLiveQuote.ts` | Uses useMarketData internally (API unchanged) |
| `src/hooks/useOptionChainLive.ts` | Uses useMarketData internally (API unchanged) |
| `src/pages/WebSocketTest.tsx` | Intentionally independent for testing |

### Hook Dependency Chain

```
useLivePrice ────────┐
                     │
useLiveQuote ────────┼───► useMarketData ───► MarketDataManager
                     │
useOptionChainLive ──┘
```

---

## API Reference

### MarketDataManager

```typescript
class MarketDataManager {
  /**
   * Get the singleton instance
   */
  static getInstance(): MarketDataManager

  /**
   * Subscribe to market data for a symbol
   * @returns Unsubscribe function
   */
  subscribe(
    symbol: string,
    exchange: string,
    mode: 'LTP' | 'Quote' | 'Depth',
    callback: (data: SymbolData) => void
  ): () => void

  /**
   * Connect to WebSocket server
   * Safe to call multiple times - will not create duplicate connections
   */
  connect(): Promise<void>

  /**
   * Disconnect from WebSocket server
   */
  disconnect(): void

  /**
   * Pause connection (close socket, keep subscriptions)
   * Used when tab is hidden
   */
  pauseConnection(): void

  /**
   * Resume connection after pause
   * Reconnects and resubscribes to all symbols
   */
  resumeConnection(): Promise<void>

  /**
   * Add listener for connection state changes
   * @returns Unsubscribe function
   */
  addStateListener(listener: StateListener): () => void

  /**
   * Get current connection state
   */
  getState(): {
    connectionState: ConnectionState
    isConnected: boolean
    isAuthenticated: boolean
    isPaused: boolean
    isFallbackMode: boolean  // true when using REST API polling
    error: string | null
  }

  /**
   * Check if currently in fallback mode (REST API polling)
   */
  isFallback(): boolean

  /**
   * Set the polling rate for REST API fallback mode
   * @param rate Polling interval in milliseconds (default: 5000)
   */
  setFallbackPollingRate(rate: number): void

  /**
   * Get cached data for a symbol (for immediate display)
   */
  getCachedData(symbol: string, exchange: string): SymbolData | undefined
}
```

### Types

```typescript
type ConnectionState =
  | 'disconnected'
  | 'connecting'
  | 'connected'
  | 'authenticating'
  | 'authenticated'
  | 'paused'

type SubscriptionMode = 'LTP' | 'Quote' | 'Depth'

interface SymbolData {
  symbol: string
  exchange: string
  data: MarketData
  lastUpdate?: number
}

interface MarketData {
  ltp?: number
  open?: number
  high?: number
  low?: number
  close?: number
  volume?: number
  change?: number
  change_percent?: number
  bid_price?: number
  ask_price?: number
  bid_size?: number
  ask_size?: number
  depth?: {
    buy: DepthLevel[]
    sell: DepthLevel[]
  }
}
```

---

## Testing Guide

### Manual Testing Checklist

- [x] Only 1 WebSocket in DevTools Network tab (Socket filter)
- [x] Same symbol subscribed once even if multiple components need it
- [x] Tab hidden >5s → connection pauses
- [x] Tab visible → connection resumes and resubscribes
- [x] PlaceOrderDialog uses existing connection
- [x] OptionChain streams LTP correctly
- [x] Holdings/Positions show live P&L updates
- [x] Navigation between pages doesn't create new connections
- [x] Page refresh creates new connection (expected)

### REST API Fallback Testing

- [x] WebSocket fails 3+ times → switches to REST API polling
- [x] Console shows `[MarketDataManager] Switching to REST API fallback mode`
- [x] Market data still updates every 5 seconds in fallback mode
- [x] `isFallbackMode` is `true` in fallback mode
- [x] WebSocket restored → automatic switch back (console: `Disabling REST API fallback mode`)
- [x] After-market-hours usage works with REST API polling

### How to Verify Single Connection

1. Open DevTools → Network tab
2. Click **Clear** (🚫) to reset history
3. Click **Socket** filter (or **WS** in some browsers)
4. Navigate to a page with market data (e.g., Positions)
5. Verify **1 WebSocket connection** appears with status "Pending"
6. Navigate to other pages (Holdings, OptionChain, Dashboard)
7. Verify **still only 1 WebSocket** (same connection reused)

### DevTools Connection Status

| Time Column | Meaning |
|-------------|---------|
| `Pending` | Active connection |
| `14.35 s` | Closed (was open for 14.35 seconds) |
| `(unknown)` | Closed immediately or failed |

---

## FAQ

### Why do I see multiple WebSocket connections in DevTools?

DevTools keeps a **history** of all connections. Connections with a time duration (e.g., "14.35 s") are **closed**. Only "Pending" connections are active. Click Clear to reset the history.

### Why does refreshing the page create a new connection?

Page refresh destroys the JavaScript context, including the singleton instance. This is unavoidable without using Service Workers or SharedWorkers.

### Why does switching tabs close the connection?

This is a **feature** to save bandwidth and server resources. When you're not viewing the page, there's no need to receive market data updates. The connection resumes automatically when you return.

### Can I disable the pause-when-hidden behavior?

Yes, pass `pauseWhenHidden: false` to the MarketDataProvider:

```tsx
<MarketDataProvider pauseWhenHidden={false}>
  {children}
</MarketDataProvider>
```

### How does subscription deduplication work?

Each subscription is keyed by `EXCHANGE:SYMBOL:MODE`. If two components subscribe to the same key, only one WebSocket subscription is created. A reference count tracks how many components are using it. The WebSocket unsubscribe is only sent when the last component unsubscribes.

### Why is the app using REST API instead of WebSocket?

This happens when the WebSocket connection fails repeatedly (3+ times). Common causes:
- **After market hours:** Broker WebSocket servers may be unavailable
- **Network issues:** Unstable connection causing frequent disconnects
- **Server maintenance:** WebSocket server temporarily down

The app automatically switches to REST API polling (`/api/v1/multiquotes`) every 5 seconds. When WebSocket becomes available again, it will automatically switch back.

### How can I tell if I'm in fallback mode?

Check the `isFallbackMode` property in your hook or context:

```typescript
const { isFallbackMode } = useMarketData({ symbols, mode: 'LTP' })

if (isFallbackMode) {
  console.log('Using REST API polling - WebSocket unavailable')
}
```

### Can I change the REST API polling interval?

Yes, use the `setFallbackPollingRate()` method on the MarketDataManager:

```typescript
const manager = MarketDataManager.getInstance()
manager.setFallbackPollingRate(10000) // Poll every 10 seconds
```

### Why does REST API fallback need an API key?

The `/api/v1/multiquotes` endpoint requires authentication. The MarketDataManager automatically fetches your API key from `/api/v1/apikey` when entering fallback mode.

---

## Changelog

### v1.1.0 (REST API Fallback)

- **NEW:** Automatic REST API fallback when WebSocket fails
  - Triggers after 3 consecutive connection failures
  - Polls `/api/v1/multiquotes` every 5 seconds
  - Automatically recovers when WebSocket is restored
- **NEW:** `isFallbackMode` state exposed in hook, context, and manager
- **NEW:** `setFallbackPollingRate()` method to customize polling interval
- **NEW:** `isFallback()` method on MarketDataManager
- Improved reliability for after-market-hours usage

### v1.0.0 (Issue #848)

- Initial implementation of shared WebSocket connection manager
- Singleton pattern for MarketDataManager
- Ref-counted subscriptions
- React Context for provider integration
- Visibility handling (pause after 5s hidden)
- Backward-compatible useMarketData API
- Connection guard to prevent duplicate connections
