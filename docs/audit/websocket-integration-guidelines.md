# WebSocket Integration Guidelines

## Developer Guide for Real-Time Data in OpenAlgo React Frontend

This document provides guidelines for creating new pages that require real-time market data streaming with proper fallback mechanisms.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [When to Use WebSocket vs REST](#2-when-to-use-websocket-vs-rest)
3. [The Fallback Chain Pattern](#3-the-fallback-chain-pattern)
4. [Step-by-Step Integration Guide](#4-step-by-step-integration-guide)
5. [Code Examples](#5-code-examples)
6. [Page Visibility Integration](#6-page-visibility-integration)
7. [Error Handling](#7-error-handling)
8. [Testing Guidelines](#8-testing-guidelines)
9. [Checklist for New Pages](#9-checklist-for-new-pages)

---

## 1. Architecture Overview

### 1.1 Data Sources (Priority Order)

```
┌─────────────────────────────────────────────────────────────────┐
│                     DATA SOURCE PRIORITY                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   Priority 1: WebSocket LTP                                     │
│   ├── Condition: Market open + Connection active + Data fresh   │
│   └── Latency: <100ms real-time updates                         │
│                           │                                     │
│                           ▼ (fallback if unavailable)           │
│   Priority 2: MultiQuotes API                                   │
│   ├── Condition: WebSocket unavailable or stale                 │
│   └── Latency: ~500ms, refreshed every 30s                      │
│                           │                                     │
│                           ▼ (fallback if unavailable)           │
│   Priority 3: REST API (Initial Fetch)                          │
│   ├── Condition: Default baseline data                          │
│   └── Latency: On-demand, polling interval 10-30s               │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 1.2 Key Hooks

| Hook | Purpose | When to Use |
|------|---------|-------------|
| `useLivePrice<T>` | Centralized price with all fallbacks | **Primary choice** for positions/holdings |
| `useMarketData` | Direct WebSocket connection | Testing, custom implementations |
| `useMarketStatus` | Market open/close detection | Exchange-aware timing |
| `usePageVisibility` | Tab visibility detection | Resource optimization (to be implemented) |

### 1.3 Backend Components

```
Frontend                    Backend
────────                    ───────
useMarketData ──────────► WebSocket Proxy (port 8765)
     │                            │
     │                     ┌──────┴──────┐
     │                     ▼             ▼
useLivePrice ◄───── ZeroMQ Bus    Broker Adapters
     │                     │             │
     ▼                     └──────┬──────┘
MultiQuotes API                   ▼
     │                     Broker WebSockets
     ▼                     (Angel, Zerodha, etc.)
REST API
```

---

## 2. When to Use WebSocket vs REST

### 2.1 Use WebSocket (via `useLivePrice`) When:

✅ Displaying live market prices (LTP, bid/ask)
✅ Real-time P&L calculations
✅ Market depth visualization
✅ Price alerts or triggers
✅ High-frequency data updates needed

### 2.2 Use REST API Only When:

✅ Initial page load data
✅ Historical data (candles, past trades)
✅ Order placement/modification (actions)
✅ Account information (funds, margins)
✅ Static data (symbols, expiries)

### 2.3 Decision Matrix

| Data Type | WebSocket | REST | Polling |
|-----------|-----------|------|---------|
| Current LTP | ✅ Primary | Fallback | Every 30s |
| Positions list | ❌ | ✅ Primary | Every 10-30s |
| Position P&L | ✅ (recalculate) | Initial | - |
| Order book | ❌ | ✅ Primary | Every 10s |
| Order status | Socket.IO | ✅ | On-demand |
| Holdings list | ❌ | ✅ Primary | Every 10-30s |
| Holding value | ✅ (recalculate) | Initial | - |

---

## 3. The Fallback Chain Pattern

### 3.1 How `useLivePrice` Implements Fallback

```typescript
// Priority chain in useLivePrice.ts
const enhancedData = useMemo(() => {
  return items.map((item) => {
    const key = `${item.exchange}:${item.symbol}`
    const wsData = marketData.get(key)      // WebSocket data
    const mqData = multiQuotes.get(key)      // MultiQuotes API data

    // Check WebSocket freshness (< 5 seconds old + market open)
    const hasWsData = exchangeMarketOpen &&
      wsData?.data?.ltp &&
      wsData.lastUpdate &&
      Date.now() - wsData.lastUpdate < staleThreshold

    // Fallback chain
    let currentLtp: number
    let dataSource: 'websocket' | 'multiquotes' | 'rest'

    if (hasWsData) {
      currentLtp = wsData.data.ltp          // Priority 1: WebSocket
      dataSource = 'websocket'
    } else if (mqData?.ltp) {
      currentLtp = mqData.ltp               // Priority 2: MultiQuotes
      dataSource = 'multiquotes'
    } else {
      currentLtp = item.ltp                 // Priority 3: REST
      dataSource = 'rest'
    }

    return { ...item, ltp: currentLtp, _dataSource: dataSource }
  })
}, [items, marketData, multiQuotes, staleThreshold])
```

### 3.2 Freshness Detection

```typescript
// Data is considered stale after 5 seconds without update
const STALE_THRESHOLD = 5000 // ms

const isFresh = (lastUpdate: number) => {
  return Date.now() - lastUpdate < STALE_THRESHOLD
}
```

---

## 4. Step-by-Step Integration Guide

### Step 1: Define Your Data Interface

```typescript
// types/myFeature.ts
import type { PriceableItem } from '@/hooks/useLivePrice'

// Extend PriceableItem for useLivePrice compatibility
export interface MyDataItem extends PriceableItem {
  symbol: string       // Required
  exchange: string     // Required
  ltp?: number         // Optional - will be enhanced
  pnl?: number         // Optional - will be recalculated
  pnlpercent?: number  // Optional - will be recalculated
  quantity?: number    // Optional - for P&L calculation
  average_price?: number // Optional - for P&L calculation

  // Your custom fields
  customField: string
}
```

### Step 2: Create REST API Fetcher

```typescript
// api/myFeature.ts
export const myFeatureApi = {
  async getData(apiKey: string): Promise<MyDataResponse> {
    const response = await fetch('/api/v1/myfeature', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ apikey: apiKey }),
    })
    return response.json()
  }
}
```

### Step 3: Create the Page Component

```typescript
// pages/MyFeaturePage.tsx
import { useCallback, useEffect, useState } from 'react'
import { useLivePrice } from '@/hooks/useLivePrice'
import { useAuthStore } from '@/stores/authStore'
import { myFeatureApi } from '@/api/myFeature'
import type { MyDataItem } from '@/types/myFeature'

export default function MyFeaturePage() {
  const { apiKey } = useAuthStore()
  const [items, setItems] = useState<MyDataItem[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Step 3a: Integrate useLivePrice
  const { data: enhancedItems, isLive, isConnected } = useLivePrice(items, {
    enabled: items.length > 0,
    useMultiQuotesFallback: true,
    staleThreshold: 5000,
    multiQuotesRefreshInterval: 30000,
  })

  // Step 3b: REST API fetcher
  const fetchData = useCallback(async () => {
    if (!apiKey) return
    try {
      const response = await myFeatureApi.getData(apiKey)
      if (response.status === 'success') {
        setItems(response.data)
        setError(null)
      } else {
        setError(response.message)
      }
    } catch (err) {
      setError('Failed to fetch data')
    } finally {
      setIsLoading(false)
    }
  }, [apiKey])

  // Step 3c: Initial fetch + polling
  useEffect(() => {
    fetchData()

    // Reduce polling when live data available
    const intervalMs = isLive ? 30000 : 10000
    const interval = setInterval(fetchData, intervalMs)

    return () => clearInterval(interval)
  }, [fetchData, isLive])

  // Step 3d: Render with enhanced data
  return (
    <div>
      <LiveIndicator isLive={isLive} isConnected={isConnected} />

      {isLoading ? (
        <LoadingSpinner />
      ) : error ? (
        <ErrorMessage message={error} />
      ) : (
        <DataTable items={enhancedItems} />
      )}
    </div>
  )
}
```

### Step 4: Create Live Indicator Component

```typescript
// components/LiveIndicator.tsx
import { Radio } from 'lucide-react'
import { Badge } from '@/components/ui/badge'

interface LiveIndicatorProps {
  isLive: boolean
  isConnected: boolean
}

export function LiveIndicator({ isLive, isConnected }: LiveIndicatorProps) {
  if (!isConnected) {
    return (
      <Badge variant="outline" className="text-muted-foreground">
        Offline
      </Badge>
    )
  }

  return (
    <Badge
      variant={isLive ? "default" : "secondary"}
      className={isLive ? "bg-green-500 animate-pulse" : ""}
    >
      <Radio className="h-3 w-3 mr-1" />
      {isLive ? 'Live' : 'Connected'}
    </Badge>
  )
}
```

---

## 5. Code Examples

### 5.1 Basic Position-like Page (Reference: Positions.tsx)

```typescript
import { useLivePrice } from '@/hooks/useLivePrice'
import { useAuthStore } from '@/stores/authStore'

export default function WatchlistPage() {
  const { apiKey } = useAuthStore()
  const [watchlist, setWatchlist] = useState<WatchlistItem[]>([])

  // Fetch initial data from REST API
  const fetchWatchlist = useCallback(async () => {
    const response = await tradingApi.getWatchlist(apiKey)
    setWatchlist(response.data)
  }, [apiKey])

  // Enhance with live prices
  const { data: liveWatchlist, isLive } = useLivePrice(watchlist, {
    enabled: watchlist.length > 0,
    useMultiQuotesFallback: true,
  })

  // Polling with live-aware interval
  useEffect(() => {
    fetchWatchlist()
    const interval = setInterval(fetchWatchlist, isLive ? 60000 : 10000)
    return () => clearInterval(interval)
  }, [fetchWatchlist, isLive])

  return (
    <Table>
      {liveWatchlist.map((item) => (
        <TableRow key={item.symbol}>
          <TableCell>{item.symbol}</TableCell>
          <TableCell>{item.ltp?.toFixed(2)}</TableCell>
          <TableCell className={item.change >= 0 ? 'text-green-500' : 'text-red-500'}>
            {item.change?.toFixed(2)}%
          </TableCell>
        </TableRow>
      ))}
    </Table>
  )
}
```

### 5.2 Page with Custom P&L Calculation

```typescript
import { useLivePrice, calculateLiveStats } from '@/hooks/useLivePrice'

export default function PortfolioPage() {
  const [portfolio, setPortfolio] = useState<PortfolioItem[]>([])
  const [stats, setStats] = useState<PortfolioStats | null>(null)

  const { data: livePortfolio, isLive } = useLivePrice(portfolio, {
    enabled: portfolio.length > 0,
  })

  // Recalculate aggregated stats with live data
  const liveStats = useMemo(() => {
    if (!stats) return stats

    const hasLiveData = livePortfolio.some(
      (item) => (item as any)._dataSource !== 'rest'
    )

    if (!hasLiveData) return stats

    return calculateLiveStats(livePortfolio, stats)
  }, [stats, livePortfolio])

  return (
    <div>
      <StatsSummary stats={liveStats} />
      <PortfolioTable items={livePortfolio} />
    </div>
  )
}
```

### 5.3 Direct WebSocket Usage (Advanced)

For cases where you need direct WebSocket control:

```typescript
import { useMarketData } from '@/hooks/useMarketData'

export default function MarketDepthPage() {
  const symbols = [
    { symbol: 'RELIANCE', exchange: 'NSE' },
    { symbol: 'TCS', exchange: 'NSE' },
  ]

  const {
    data: marketData,
    isConnected,
    isAuthenticated,
    error,
    connect,
    disconnect,
  } = useMarketData({
    symbols,
    mode: 'Depth',  // Get full market depth, not just LTP
    enabled: true,
    autoReconnect: true,
  })

  return (
    <div>
      {Array.from(marketData.entries()).map(([key, symbolData]) => (
        <DepthChart key={key} data={symbolData.data} />
      ))}
    </div>
  )
}
```

---

## 6. Page Visibility Integration

### 6.1 The Visibility Hook (IMPLEMENTED)

The `usePageVisibility` hook is now available at `/frontend/src/hooks/usePageVisibility.ts`:

```typescript
import { usePageVisibility } from '@/hooks/usePageVisibility'

// Full return type with metadata
const {
  isVisible,         // Current visibility state
  wasHidden,         // True briefly when returning from hidden
  timeSinceVisible,  // Time in ms since becoming visible
  timeSinceHidden,   // Time in ms since becoming hidden (0 if visible)
  lastVisibilityChange, // Timestamp of last change
} = usePageVisibility()

// Or use the simplified version
import { useIsPageVisible } from '@/hooks/usePageVisibility'
const isVisible = useIsPageVisible()
```

### 6.2 Integrate with Your Page

```typescript
import { usePageVisibility } from '@/hooks/usePageVisibility'
import { useLivePrice } from '@/hooks/useLivePrice'

export default function MyPage() {
  const isVisible = usePageVisibility()
  const [items, setItems] = useState([])
  const [lastFetch, setLastFetch] = useState<number>(Date.now())

  // Only enable WebSocket when page is visible
  const { data: enhancedItems, isLive } = useLivePrice(items, {
    enabled: items.length > 0 && isVisible,  // Pause when hidden
    useMultiQuotesFallback: true,
  })

  // Refresh data when page becomes visible after being hidden
  useEffect(() => {
    if (isVisible) {
      const timeSinceLastFetch = Date.now() - lastFetch

      // If hidden for more than 30 seconds, refresh immediately
      if (timeSinceLastFetch > 30000) {
        fetchData()
      }
    }
  }, [isVisible, lastFetch])

  // Polling only when visible
  useEffect(() => {
    if (!isVisible) return  // Don't poll when hidden

    const intervalMs = isLive ? 30000 : 10000
    const interval = setInterval(() => {
      fetchData()
      setLastFetch(Date.now())
    }, intervalMs)

    return () => clearInterval(interval)
  }, [isVisible, isLive])

  return (
    <div>
      <StaleDataBanner
        show={!isVisible || !isLive}
        message="Data may be delayed"
      />
      {/* ... */}
    </div>
  )
}
```

### 6.3 Stale Data Banner Component

```typescript
// components/StaleDataBanner.tsx
import { AlertTriangle } from 'lucide-react'
import { Alert, AlertDescription } from '@/components/ui/alert'

interface StaleDataBannerProps {
  show: boolean
  message?: string
}

export function StaleDataBanner({
  show,
  message = 'Data may be outdated'
}: StaleDataBannerProps) {
  if (!show) return null

  return (
    <Alert variant="warning" className="mb-4">
      <AlertTriangle className="h-4 w-4" />
      <AlertDescription>{message}</AlertDescription>
    </Alert>
  )
}
```

---

## 7. Error Handling

### 7.1 Connection Errors

```typescript
const { error, isConnected } = useLivePrice(items, { enabled: true })

// Handle WebSocket connection issues gracefully
useEffect(() => {
  if (error) {
    console.warn('WebSocket error, using fallback:', error)
    // The hook automatically falls back to MultiQuotes/REST
    // No additional action needed
  }
}, [error])
```

### 7.2 Fallback Status Display

```typescript
function DataSourceIndicator({ dataSource }: { dataSource: string }) {
  const indicators = {
    websocket: { color: 'green', label: 'Live' },
    multiquotes: { color: 'yellow', label: 'Delayed' },
    rest: { color: 'gray', label: 'Cached' },
  }

  const { color, label } = indicators[dataSource] || indicators.rest

  return (
    <span className={`text-${color}-500 text-xs`}>
      ({label})
    </span>
  )
}
```

### 7.3 Network Recovery

```typescript
// Detect network status changes
useEffect(() => {
  const handleOnline = () => {
    toast.success('Connection restored')
    fetchData()  // Refresh data immediately
  }

  const handleOffline = () => {
    toast.warning('Connection lost - data may be stale')
  }

  window.addEventListener('online', handleOnline)
  window.addEventListener('offline', handleOffline)

  return () => {
    window.removeEventListener('online', handleOnline)
    window.removeEventListener('offline', handleOffline)
  }
}, [])
```

---

## 8. Testing Guidelines

### 8.1 Unit Testing Hooks

```typescript
// __tests__/hooks/useLivePrice.test.ts
import { renderHook, waitFor } from '@testing-library/react'
import { useLivePrice } from '@/hooks/useLivePrice'

describe('useLivePrice', () => {
  it('should fallback to REST data when WebSocket unavailable', async () => {
    const items = [
      { symbol: 'RELIANCE', exchange: 'NSE', ltp: 2500 }
    ]

    const { result } = renderHook(() =>
      useLivePrice(items, { enabled: true })
    )

    // Initially uses REST data
    expect(result.current.data[0].ltp).toBe(2500)
    expect(result.current.isLive).toBe(false)
  })
})
```

### 8.2 Manual Testing Checklist

- [ ] Page loads with REST data correctly
- [ ] WebSocket connects and "Live" badge appears
- [ ] LTP updates in real-time during market hours
- [ ] Falls back to MultiQuotes when WebSocket disconnects
- [ ] Polling continues at correct interval
- [ ] Tab switching doesn't cause errors
- [ ] Data refreshes when tab becomes visible
- [ ] Memory doesn't leak on long sessions

### 8.3 Testing Fallback Scenarios

```typescript
// Force different fallback scenarios for testing
const testScenarios = {
  // 1. Simulate WebSocket failure
  wsFailure: () => {
    // Disconnect WebSocket manually in DevTools
    // Verify MultiQuotes fallback activates
  },

  // 2. Simulate stale data
  staleData: () => {
    // Wait 6+ seconds without WebSocket updates
    // Verify fallback to MultiQuotes
  },

  // 3. Simulate market closed
  marketClosed: () => {
    // Test outside market hours
    // Verify REST data used, no WebSocket attempted
  },
}
```

---

## 9. Checklist for New Pages

### Before Development

- [ ] Determine if real-time data is needed
- [ ] Identify which data fields need live updates
- [ ] Define your `PriceableItem` interface
- [ ] Plan REST API endpoints for initial/fallback data

### During Development

- [ ] Extend `PriceableItem` for your data type
- [ ] Use `useLivePrice` as primary data hook
- [ ] Implement REST API fetcher with proper error handling
- [ ] Add polling with live-aware intervals
- [ ] Include "Live" indicator badge
- [ ] Handle loading and error states

### Page Visibility (Recommended)

- [ ] Import and use `usePageVisibility` hook
- [ ] Disable WebSocket when tab is hidden
- [ ] Pause polling when tab is hidden
- [ ] Refresh data when tab becomes visible
- [ ] Show stale data indicator when appropriate

### Testing

- [ ] Test with WebSocket connected
- [ ] Test with WebSocket disconnected (fallback)
- [ ] Test during market open hours
- [ ] Test during market closed hours
- [ ] Test tab switching behavior
- [ ] Verify no memory leaks in long sessions

### Code Review

- [ ] Cleanup functions for all effects
- [ ] Proper dependency arrays
- [ ] No unnecessary re-renders
- [ ] Error boundaries in place
- [ ] Accessible loading/error states

---

## Quick Reference

### Import Pattern

```typescript
// Standard imports for a live data page
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useLivePrice, calculateLiveStats } from '@/hooks/useLivePrice'
import { usePageVisibility } from '@/hooks/usePageVisibility'
import { useAuthStore } from '@/stores/authStore'
```

### Hook Configuration (IMPLEMENTED)

```typescript
const {
  data,              // Enhanced items with live LTP and P&L
  isLive,            // WebSocket connected AND market open AND not paused
  isConnected,       // WebSocket connection status
  isPaused,          // Whether streaming is paused (tab hidden)
  isAnyMarketOpen,   // Any exchange currently trading
  multiQuotes,       // Fallback data from MultiQuotes API
  refreshMultiQuotes // Manual refresh function
} = useLivePrice(items, {
  enabled: items.length > 0,        // Enable when data available
  staleThreshold: 5000,             // 5 seconds freshness window
  useMultiQuotesFallback: true,     // Enable MultiQuotes fallback
  multiQuotesRefreshInterval: 30000, // Refresh every 30 seconds
  pauseWhenHidden: true,            // NEW: Pause when tab hidden (default: true)
  pauseDelay: 5000,                 // NEW: Delay before pausing (default: 5000ms)
})
```

### Polling Pattern (IMPLEMENTED in Positions & Holdings)

```typescript
const { isVisible, wasHidden, timeSinceHidden } = usePageVisibility()
const lastFetchRef = useRef<number>(Date.now())

// Visibility-aware polling
useEffect(() => {
  if (!isVisible) return  // Pause when hidden

  fetchData()
  lastFetchRef.current = Date.now()

  const interval = setInterval(() => {
    fetchData()
    lastFetchRef.current = Date.now()
  }, isLive ? 30000 : 10000)

  return () => clearInterval(interval)
}, [isVisible, isLive, fetchData])

// Refresh when returning from hidden
useEffect(() => {
  if (!wasHidden || !isVisible) return

  // If hidden for more than 30 seconds, refresh immediately
  if (timeSinceHidden > 30000) {
    setShowStaleWarning(true)
    fetchData()
    const timeout = setTimeout(() => setShowStaleWarning(false), 5000)
    return () => clearTimeout(timeout)
  }
}, [wasHidden, isVisible, timeSinceHidden, fetchData])
```

---

## Related Documentation

- [WebSocket Frontend Management Audit](./websocket-frontend-management.md)
- [WebSocket Security Audit](./websocket-security.md)
- [Services Documentation](../prompt/services_documentation.md)

---

**Last Updated**: 2026-02-03
**Author**: Claude Code
**Version**: 1.0
