# WebSocket Frontend Management Audit

## Executive Summary

This audit examines the WebSocket implementation in OpenAlgo's React frontend, focusing on connection management during tab switching, page navigation, and browser visibility changes. The analysis identifies critical gaps in resource management and provides recommendations for implementing a robust, centralized WebSocket solution.

**Key Finding**: The current implementation lacks Page Visibility API integration, causing WebSocket connections to remain active when tabs are hidden, leading to unnecessary resource consumption and potential connection issues.

---

## Implementation Status (2026-02-03)

### ✅ Completed Items

| Feature | Description | Files |
|---------|-------------|-------|
| **usePageVisibility hook** | Full visibility tracking with metadata | `/hooks/usePageVisibility.ts` |
| **Visibility-aware WebSocket** | Pauses/resumes connection on tab hide/show | `/hooks/useMarketData.ts` |
| **Visibility-aware useLivePrice** | Pauses WebSocket + polling when hidden | `/hooks/useLivePrice.ts` |
| **Positions page optimization** | Stale warning, pause indicator, smart polling | `/pages/Positions.tsx` |
| **Holdings page optimization** | Stale warning, pause indicator, smart polling | `/pages/Holdings.tsx` |

### New Options Added

```typescript
// useMarketData new options:
pauseWhenHidden?: boolean  // Default: true
pauseDelay?: number        // Default: 5000ms

// useLivePrice new options:
pauseWhenHidden?: boolean  // Default: true
pauseDelay?: number        // Default: 5000ms

// New return values:
isPaused: boolean          // Whether streaming is paused
```

---

## Table of Contents

1. [Current Architecture Overview](#1-current-architecture-overview)
2. [Affected Pages Analysis](#2-affected-pages-analysis)
3. [Tab Switching Behavior](#3-tab-switching-behavior)
4. [Identified Issues](#4-identified-issues)
5. [Best Practices for WebSocket Management](#5-best-practices-for-websocket-management)
6. [Recommended Implementation](#6-recommended-implementation)
7. [Action Items](#7-action-items)

---

## 1. Current Architecture Overview

### 1.1 WebSocket Hooks

OpenAlgo uses three distinct hooks for real-time communication:

| Hook | Transport | Purpose | File |
|------|-----------|---------|------|
| `useMarketData` | Native WebSocket | Market data streaming (LTP, Quote, Depth) | `/frontend/src/hooks/useMarketData.ts` |
| `useSocket` | Socket.IO (Polling) | Order/trade notifications | `/frontend/src/hooks/useSocket.ts` |
| `useLivePrice` | Composite | Centralized price with fallback chain | `/frontend/src/hooks/useLivePrice.ts` |

### 1.2 Backend Architecture

The backend WebSocket proxy (`websocket_proxy/server.py`) provides:
- Multi-broker support (24+ brokers)
- Connection pooling (3,000 symbols capacity)
- ZeroMQ message bus for high-performance distribution
- Message throttling (50ms for LTP mode)
- Subscription indexing for O(1) client lookup

### 1.3 Data Flow

```
Browser → WebSocket Proxy (port 8765) → ZeroMQ Bus → Broker Adapters → Broker WebSockets
```

---

## 2. Affected Pages Analysis

### 2.1 WebSocket Test Page (`/websocket/test`)

**File**: `/frontend/src/pages/WebSocketTest.tsx` (1,207 lines)

**Current Behavior**:
- Connects directly to WebSocket proxy on user action
- Auto-reconnect with 3-second delay on unclean close
- Manual connect/disconnect buttons
- Saves subscribed symbols to localStorage
- Cleanup on component unmount: closes socket and clears reconnect timeout

**Gaps**:
- No Page Visibility API integration
- Connection stays alive when tab is hidden
- Auto-reconnect triggers even when tab is in background

### 2.2 Positions Page (`/positions`)

**File**: `/frontend/src/pages/Positions.tsx`

**Current Behavior**:
- Uses `useLivePrice` hook for real-time LTP updates
- Falls back to MultiQuotes API when WebSocket unavailable
- Polling interval: 30s when live, 10s when not live
- Shows "Live" badge when WebSocket connected AND market open

**Gaps**:
- WebSocket runs continuously even when tab hidden
- Polling continues in background
- No visibility-based optimization

### 2.3 Holdings Page (`/holdings`)

**File**: `/frontend/src/pages/Holdings.tsx`

**Current Behavior**:
- Identical to Positions page (uses `useLivePrice`)
- Same polling intervals (30s/10s)
- Recalculates portfolio stats with live data

**Gaps**:
- Same issues as Positions page

---

## 3. Tab Switching Behavior

### 3.1 What Currently Happens

When a user switches to another tab or minimizes the browser:

1. **WebSocket Connection**: Stays active, continues receiving market data
2. **Message Processing**: All incoming messages are still parsed and state updated
3. **React Rendering**: React may batch updates but still processes state changes
4. **Auto-Reconnect**: If connection drops while hidden, reconnects immediately
5. **Polling**: REST API polling continues at same interval
6. **Browser Throttling**: Chrome/Firefox throttle timers to 1Hz but WebSocket is unaffected

### 3.2 When User Returns

1. **State May Be Stale**: If connection was lost while hidden, data could be outdated
2. **Reconnection Storm**: Multiple pages/components may attempt reconnection simultaneously
3. **No Stale Indicator**: User doesn't know if data is fresh or stale from background period

### 3.3 Resource Impact

| Resource | Hidden Tab Impact |
|----------|-------------------|
| Network | Continuous WebSocket data + polling requests |
| CPU | Message parsing, state updates, React reconciliation |
| Memory | Growing message buffers, state updates |
| Battery | Significant drain on mobile devices |
| Server | Unnecessary connections and subscriptions maintained |

---

## 4. Identified Issues

### 4.1 Critical Issues

#### Issue #1: No Page Visibility API Integration
**Severity**: High
**Impact**: Wasted resources, battery drain, unnecessary server load

**Location**: All WebSocket hooks

**Evidence**:
```typescript
// useMarketData.ts - No visibility handling
socket.onclose = (event) => {
  if (autoReconnect && !event.wasClean && enabled) {
    reconnectTimeoutRef.current = setTimeout(connect, 3000)  // Reconnects even when hidden
  }
}
```

#### Issue #2: Multiple Independent WebSocket Connections
**Severity**: Medium
**Impact**: No centralized connection management, duplicate connections possible

**Current State**:
- Each hook (`useMarketData`, `useSocket`) manages its own connection
- No shared connection instance across components
- Components on same page may create multiple connections

#### Issue #3: No Graceful Degradation on Tab Hide
**Severity**: Medium
**Impact**: No visual indication of background data staleness

**Missing Features**:
- No stale data indicator when tab becomes visible
- No reconnection status during background period
- No data refresh on tab focus

### 4.2 Moderate Issues

#### Issue #4: Reconnection Without Visibility Check
**Severity**: Medium
**Location**: `useMarketData.ts:239-241`

```typescript
if (autoReconnect && !event.wasClean && enabled) {
  reconnectTimeoutRef.current = setTimeout(connect, 3000)
}
```

**Problem**: Reconnects immediately without checking if tab is visible, wasting resources.

#### Issue #5: Polling Continues in Background
**Severity**: Low
**Location**: `Holdings.tsx:95-100`, `Positions.tsx` (similar)

```typescript
const intervalMs = isLive ? 30000 : 10000
const interval = setInterval(() => fetchHoldings(), intervalMs)
```

**Problem**: REST API polling continues regardless of tab visibility.

#### Issue #6: No Connection Pooling on Frontend
**Severity**: Low
**Impact**: Multiple components using same symbols don't share subscriptions

**Current State**: Each instance of `useMarketData` creates independent subscription requests.

### 4.3 Minor Issues

#### Issue #7: WebSocket Test Page State Persistence
**Severity**: Low
**Location**: `WebSocketTest.tsx:644-646`

```typescript
localStorage.setItem('ws_test_symbols', JSON.stringify(Array.from(activeSymbols.keys())))
```

**Note**: Good implementation - persists symbols. Could be extended to connection state.

#### Issue #8: Socket.IO Uses Polling Only
**Severity**: Info
**Location**: `useSocket.ts:125-127`

```typescript
socketRef.current = io(`${protocol}//${host}:${port}`, {
  transports: ['polling'],
  upgrade: false,
  // ...
})
```

**Note**: This is intentional due to Flask threading issues. Polling is reliable but less efficient.

---

## 5. Best Practices for WebSocket Management

### 5.1 Page Visibility API

**Standard**: `document.visibilityState` and `visibilitychange` event

```typescript
// Core visibility detection
document.addEventListener('visibilitychange', () => {
  const isVisible = document.visibilityState === 'visible'
  if (isVisible) {
    // Resume WebSocket, refresh data
  } else {
    // Pause WebSocket, stop polling
  }
})
```

**Benefits**:
- Reduces battery drain by 40-60% on mobile
- Decreases server load during inactive sessions
- Improves connection reliability by preventing unnecessary reconnects

### 5.2 Connection States

Implement a state machine for WebSocket connections:

```
        ┌───────────────────────────────────────────┐
        │                                           │
        ▼                                           │
    ┌────────┐    visible    ┌───────────┐    data    ┌────────┐
    │  IDLE  │──────────────►│ CONNECTING│──────────►│ ACTIVE │
    └────────┘               └───────────┘           └────────┘
        ▲                         │                      │
        │                    error/close                 │ hidden
        │                         │                      │
        │                         ▼                      ▼
        │                    ┌────────────┐         ┌────────┐
        └────────────────────│  BACKOFF   │◄────────│ PAUSED │
                             └────────────┘         └────────┘
```

### 5.3 Centralized WebSocket Manager

**Pattern**: Singleton service with subscription reference counting

```typescript
class WebSocketManager {
  private static instance: WebSocketManager
  private socket: WebSocket | null = null
  private subscriptions: Map<string, Set<string>> = new Map() // symbol → component IDs
  private visibility: 'visible' | 'hidden' = 'visible'

  subscribe(componentId: string, symbols: string[]) { /* ... */ }
  unsubscribe(componentId: string) { /* ... */ }
  private onVisibilityChange() { /* ... */ }
}
```

**Benefits**:
- Single connection shared across all components
- Reference counting prevents premature disconnect
- Centralized visibility handling
- Unified reconnection strategy

### 5.4 Stale Data Handling

```typescript
interface MarketDataWithFreshness {
  ltp: number
  lastUpdate: number
  isFresh: boolean  // Based on lastUpdate vs current time
  source: 'websocket' | 'multiquotes' | 'rest' | 'cache'
}
```

### 5.5 Intelligent Reconnection

```typescript
// Backoff with visibility awareness
function scheduleReconnect() {
  if (document.visibilityState === 'hidden') {
    // Don't reconnect while hidden - wait for visibility
    return
  }

  const delay = Math.min(1000 * Math.pow(2, attemptCount), 30000)
  reconnectTimer = setTimeout(connect, delay)
}
```

---

## 6. Recommended Implementation

### 6.1 New Centralized WebSocket Service

**File**: `/frontend/src/services/WebSocketService.ts`

```typescript
import { create } from 'zustand'

interface WebSocketState {
  isConnected: boolean
  isAuthenticated: boolean
  visibility: 'visible' | 'hidden'
  subscriptions: Map<string, Set<string>> // symbol → componentIds
  data: Map<string, MarketData>
  lastActivity: number

  // Actions
  connect: () => void
  disconnect: () => void
  subscribe: (componentId: string, symbols: SymbolInfo[]) => void
  unsubscribe: (componentId: string) => void
  setVisibility: (state: 'visible' | 'hidden') => void
}

export const useWebSocketStore = create<WebSocketState>((set, get) => ({
  // ... implementation
}))
```

### 6.2 Visibility-Aware Hook

**File**: `/frontend/src/hooks/usePageVisibility.ts`

```typescript
import { useEffect, useState } from 'react'

export function usePageVisibility() {
  const [isVisible, setIsVisible] = useState(!document.hidden)

  useEffect(() => {
    const handler = () => setIsVisible(!document.hidden)
    document.addEventListener('visibilitychange', handler)
    return () => document.removeEventListener('visibilitychange', handler)
  }, [])

  return isVisible
}
```

### 6.3 Enhanced useMarketData Hook

**File**: `/frontend/src/hooks/useMarketData.ts` (modified)

```typescript
export function useMarketData({
  symbols,
  mode = 'LTP',
  enabled = true,
  pauseWhenHidden = true,  // NEW
}: UseMarketDataOptions): UseMarketDataReturn {
  const isVisible = usePageVisibility()
  const effectiveEnabled = enabled && (isVisible || !pauseWhenHidden)

  // ... existing implementation with effectiveEnabled

  // On visibility change
  useEffect(() => {
    if (isVisible && wasHidden) {
      // Refresh stale data
      resubscribeAll()
    }
  }, [isVisible])
}
```

### 6.4 Component-Level Integration

```tsx
// Positions.tsx (example)
function Positions() {
  const isVisible = usePageVisibility()

  const { data: enhancedPositions, isLive, isStale } = useLivePrice(positions, {
    enabled: positions.length > 0,
    pauseWhenHidden: true,  // NEW
  })

  // Reduce polling when hidden
  useEffect(() => {
    if (!isVisible) return

    const intervalMs = isLive ? 30000 : 10000
    const interval = setInterval(() => fetchPositions(), intervalMs)
    return () => clearInterval(interval)
  }, [isVisible, isLive])

  return (
    <div>
      {isStale && <StaleBanner message="Data may be outdated" />}
      {/* ... */}
    </div>
  )
}
```

---

## 7. Action Items

### 7.1 Immediate (P0) - ✅ COMPLETED

| # | Task | Status | Files Modified |
|---|------|--------|----------------|
| 1 | Create `usePageVisibility` hook | ✅ Done | `/hooks/usePageVisibility.ts` |
| 2 | Integrate visibility check in `useMarketData` auto-reconnect | ✅ Done | `/hooks/useMarketData.ts` |
| 3 | Add `pauseWhenHidden` option to `useMarketData` | ✅ Done | `/hooks/useMarketData.ts` |

### 7.2 Short-term (P1) - ✅ PARTIALLY COMPLETED

| # | Task | Status | Files Modified |
|---|------|--------|----------------|
| 4 | Create centralized `WebSocketService` with Zustand | Pending | - |
| 5 | Add stale data indicator to Positions/Holdings pages | ✅ Done | `/pages/Positions.tsx`, `/pages/Holdings.tsx` |
| 6 | Implement visibility-aware polling in all data-fetching pages | ✅ Done (Positions/Holdings) | `/pages/Positions.tsx`, `/pages/Holdings.tsx` |

### 7.3 Medium-term (P2)

| # | Task | Effort | Impact |
|---|------|--------|--------|
| 7 | Implement subscription reference counting (share connections) | 6h | Medium |
| 8 | Add "Reconnecting..." status indicator across app | 3h | Low |
| 9 | Implement exponential backoff with jitter for reconnection | 2h | Low |
| 10 | Add WebSocket health metrics to HealthMonitor | 4h | Low |

### 7.4 Long-term (P3)

| # | Task | Effort | Impact |
|---|------|--------|--------|
| 11 | Implement service worker for background sync | 8h | Medium |
| 12 | Add cross-tab communication for shared WebSocket | 6h | Medium |
| 13 | Implement request deduplication for MultiQuotes fallback | 4h | Low |

---

## Appendix A: File References

| File | Purpose |
|------|---------|
| `/frontend/src/hooks/useMarketData.ts` | Native WebSocket hook for market data |
| `/frontend/src/hooks/useLivePrice.ts` | Centralized price hook with fallback chain |
| `/frontend/src/hooks/useSocket.ts` | Socket.IO hook for order notifications |
| `/frontend/src/pages/WebSocketTest.tsx` | WebSocket test/debug page |
| `/frontend/src/pages/Positions.tsx` | Positions page with live pricing |
| `/frontend/src/pages/Holdings.tsx` | Holdings page with live pricing |
| `/websocket_proxy/server.py` | Backend WebSocket proxy server |
| `/websocket_proxy/connection_manager.py` | Connection pooling for broker adapters |
| `/websocket_proxy/base_adapter.py` | Base class for broker WebSocket adapters |

---

## Appendix B: Browser Support for Page Visibility API

| Browser | Support |
|---------|---------|
| Chrome | Full (v33+) |
| Firefox | Full (v18+) |
| Safari | Full (v7+) |
| Edge | Full (all versions) |
| Mobile browsers | Full |

**Polyfill**: Not needed for modern browsers. Graceful degradation for unsupported browsers by defaulting to "visible".

---

## Appendix C: Metrics to Monitor Post-Implementation

1. **WebSocket connection duration** - Should see longer connections (less churn)
2. **Messages received per session** - Should decrease (less background processing)
3. **Server-side active connections** - Should decrease during non-market hours
4. **Browser memory usage** - Should stabilize (no growing buffers)
5. **Battery usage on mobile** - User-reported improvement expected

---

**Last Updated**: 2026-02-03
**Author**: Claude Code Audit
**Version**: 1.0
