/**
 * useMarketData - Hook for real-time market data via shared WebSocket connection
 *
 * This hook delegates to the MarketDataManager singleton via MarketDataContext,
 * ensuring a single WebSocket connection is shared across all components.
 *
 * API is backward-compatible with the original implementation.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useMarketDataContextOptional } from '@/contexts/MarketDataContext'
import { MarketDataManager, type SymbolData, type SubscriptionMode } from '@/lib/MarketDataManager'

// Re-export types for backward compatibility
export type { DepthLevel, MarketData, SymbolData } from '@/lib/MarketDataManager'

interface UseMarketDataOptions {
  symbols: Array<{ symbol: string; exchange: string }>
  mode?: SubscriptionMode
  enabled?: boolean
  autoReconnect?: boolean
}

interface UseMarketDataReturn {
  data: Map<string, SymbolData>
  isConnected: boolean
  isAuthenticated: boolean
  isConnecting: boolean
  isPaused: boolean
  isFallbackMode: boolean
  error: string | null
  connect: () => Promise<void>
  disconnect: () => void
}

export function useMarketData({
  symbols,
  mode = 'LTP',
  enabled = true,
  autoReconnect = true,
}: UseMarketDataOptions): UseMarketDataReturn {
  // Try to get context (may be null if used outside provider, e.g., WebSocketTest page)
  const context = useMarketDataContextOptional()

  // Use context manager if available, otherwise get singleton directly (for standalone use)
  const managerRef = useRef<MarketDataManager>(
    context?.manager ?? MarketDataManager.getInstance()
  )

  const [marketData, setMarketData] = useState<Map<string, SymbolData>>(new Map())
  const [connectionState, setConnectionState] = useState({
    isConnected: context?.isConnected ?? false,
    isAuthenticated: context?.isAuthenticated ?? false,
    isPaused: context?.isPaused ?? false,
    isFallbackMode: context?.isFallbackMode ?? false,
    error: context?.error ?? null,
  })

  // Track if we're in the process of connecting
  const [isConnecting, setIsConnecting] = useState(false)

  // Stable symbol key for dependency tracking
  const symbolsKey = useMemo(
    () => symbols.map((s) => `${s.exchange}:${s.symbol}`).sort().join(','),
    [symbols]
  )

  // Configure autoReconnect on the manager
  useEffect(() => {
    const manager = managerRef.current
    manager.setAutoReconnect(autoReconnect)
  }, [autoReconnect])

  // Subscribe to connection state changes
  useEffect(() => {
    const manager = managerRef.current
    const unsubscribe = manager.addStateListener((state) => {
      setConnectionState({
        isConnected: state.isConnected,
        isAuthenticated: state.isAuthenticated,
        isPaused: state.isPaused,
        isFallbackMode: state.isFallbackMode,
        error: state.error,
      })
      setIsConnecting(state.connectionState === 'connecting' || state.connectionState === 'authenticating')
    })

    return unsubscribe
  }, [])

  // Subscribe to symbols when enabled
  useEffect(() => {
    if (!enabled || symbols.length === 0) {
      // Clear data when disabled
      setMarketData(new Map())
      return
    }

    const manager = managerRef.current

    // Auto-connect if not connected (manager handles deduplication)
    if (!connectionState.isConnected && !connectionState.isPaused) {
      manager.connect()
    }

    // Subscribe to each symbol
    const unsubscribes: Array<() => void> = []

    for (const { symbol, exchange } of symbols) {
      const unsubscribe = manager.subscribe(symbol, exchange, mode, (data: SymbolData) => {
        setMarketData((prev) => {
          const key = `${data.exchange}:${data.symbol}`
          const updated = new Map(prev)
          updated.set(key, data)
          return updated
        })
      })
      unsubscribes.push(unsubscribe)

      // Initialize with cached data if available
      const cached = manager.getCachedData(symbol, exchange)
      if (cached) {
        const key = `${exchange}:${symbol}`
        setMarketData((prev) => {
          const updated = new Map(prev)
          updated.set(key, cached)
          return updated
        })
      }
    }

    return () => {
      // Unsubscribe from all symbols
      unsubscribes.forEach((unsub) => unsub())
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, symbolsKey, mode])

  // Connect function (for manual connection)
  const connect = useCallback(async () => {
    await managerRef.current.connect()
  }, [])

  // Disconnect function (note: this disconnects the shared connection)
  const disconnect = useCallback(() => {
    managerRef.current.disconnect()
  }, [])

  return {
    data: marketData,
    isConnected: connectionState.isConnected,
    isAuthenticated: connectionState.isAuthenticated,
    isConnecting,
    isPaused: connectionState.isPaused,
    isFallbackMode: connectionState.isFallbackMode,
    error: connectionState.error,
    connect,
    disconnect,
  }
}
