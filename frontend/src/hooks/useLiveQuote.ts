import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { tradingApi, type QuotesData, type DepthData, type DepthLevel } from '@/api/trading'
import { useMarketData } from '@/hooks/useMarketData'
import { useMarketStatus } from '@/hooks/useMarketStatus'
import { useAuthStore } from '@/stores/authStore'

/**
 * Depth data in normalized format (used by both WebSocket and REST)
 */
export interface NormalizedDepth {
  buy: DepthLevel[]
  sell: DepthLevel[]
}

/**
 * Combined quote and depth data
 */
export interface LiveQuoteData {
  ltp?: number
  open?: number
  high?: number
  low?: number
  close?: number
  volume?: number
  oi?: number
  change?: number
  changePercent?: number
  bidPrice?: number
  askPrice?: number
  bidSize?: number
  askSize?: number
  depth?: NormalizedDepth
}

/**
 * Configuration options for useLiveQuote hook
 */
export interface UseLiveQuoteOptions {
  /** Whether the hook is enabled (default: true) */
  enabled?: boolean
  /** WebSocket subscription mode: 'LTP', 'Quote', or 'Depth' (default: 'Depth') */
  mode?: 'LTP' | 'Quote' | 'Depth'
  /** Whether to fetch REST quotes as fallback (default: true) */
  useQuotesFallback?: boolean
  /** Whether to fetch REST depth as fallback (default: true) */
  useDepthFallback?: boolean
  /** Time in ms after which WebSocket data is considered stale (default: 5000) */
  staleThreshold?: number
  /** Interval in ms to refresh REST data (default: 30000) */
  refreshInterval?: number
  /** Pause when tab is hidden (default: true) */
  pauseWhenHidden?: boolean
}

/**
 * Return type for useLiveQuote hook
 */
export interface UseLiveQuoteResult {
  /** Combined quote and depth data */
  data: LiveQuoteData
  /** Whether real-time data is available (WebSocket connected AND market open) */
  isLive: boolean
  /** Whether WebSocket is connected */
  isConnected: boolean
  /** Whether data is being loaded */
  isLoading: boolean
  /** Whether WebSocket is paused due to tab being hidden */
  isPaused: boolean
  /** Whether using REST API fallback instead of WebSocket */
  isFallbackMode: boolean
  /** Data source: 'websocket', 'rest', or 'none' */
  dataSource: 'websocket' | 'rest' | 'none'
  /** Manually refresh REST data */
  refresh: () => Promise<void>
}

/**
 * Centralized hook for real-time quote and depth data with automatic REST fallback.
 *
 * Similar to useLivePrice but for single symbol with full quote + depth support.
 * Use this for PlaceOrderDialog, symbol details, or anywhere you need live market data.
 *
 * Priority chain:
 * 1. WebSocket data (when market is open and data is fresh)
 * 2. REST API data (fallback when WebSocket unavailable)
 *
 * @example
 * ```tsx
 * const { data, isLive, isLoading } = useLiveQuote('RELIANCE', 'NSE', {
 *   enabled: dialogOpen,
 *   mode: 'Depth',
 * });
 *
 * // Access data
 * console.log(data.ltp, data.bidPrice, data.depth?.buy);
 * ```
 */
export function useLiveQuote(
  symbol: string,
  exchange: string,
  options: UseLiveQuoteOptions = {}
): UseLiveQuoteResult {
  const {
    enabled = true,
    mode = 'Depth',
    useQuotesFallback = true,
    useDepthFallback = true,
    staleThreshold = 5000,
    refreshInterval = 30000,
  } = options

  const { apiKey } = useAuthStore()
  const { isMarketOpen } = useMarketStatus()

  // REST fallback state
  const [restQuotes, setRestQuotes] = useState<QuotesData | null>(null)
  const [restDepth, setRestDepth] = useState<DepthData | null>(null)
  const [isLoadingRest, setIsLoadingRest] = useState(false)

  // Track last fetch time
  const lastFetchRef = useRef<number>(0)

  // Check if we have valid symbol/exchange
  const hasSymbol = !!symbol && !!exchange

  // WebSocket subscription
  const symbols = useMemo(
    () => hasSymbol ? [{ symbol, exchange }] : [],
    [symbol, exchange, hasSymbol]
  )

  const { data: marketData, isConnected: wsConnected, isPaused: wsPaused, isFallbackMode } = useMarketData({
    symbols,
    mode,
    enabled: enabled && hasSymbol,
  })

  const wsData = marketData.get(`${exchange}:${symbol}`)?.data
  const wsLastUpdate = marketData.get(`${exchange}:${symbol}`)?.lastUpdate

  // Check if market is open for this exchange
  const marketOpen = isMarketOpen(exchange)

  // Check if WebSocket data is fresh
  const hasWsData = !!(wsConnected && wsData && wsLastUpdate &&
    (Date.now() - wsLastUpdate < staleThreshold))

  // Effective live status (WebSocket connected, data fresh, market open)
  const isLive = hasWsData && marketOpen && !wsPaused

  /**
   * Fetch REST data (quotes and/or depth)
   */
  const fetchRestData = useCallback(async () => {
    if (!apiKey || !hasSymbol) return

    setIsLoadingRest(true)
    try {
      // Fetch quotes and depth in parallel
      const promises: Promise<void>[] = []

      if (useQuotesFallback) {
        promises.push(
          tradingApi.getQuotes(apiKey, symbol, exchange)
            .then(response => {
              if (response.status === 'success' && response.data) {
                setRestQuotes(response.data)
              }
            })
            .catch(() => {
            })
        )
      }

      if (useDepthFallback && mode === 'Depth') {
        promises.push(
          tradingApi.getDepth(apiKey, symbol, exchange)
            .then(response => {
              if (response.status === 'success' && response.data) {
                setRestDepth(response.data)
              }
            })
            .catch(() => {
            })
        )
      }

      await Promise.all(promises)
      lastFetchRef.current = Date.now()
    } finally {
      setIsLoadingRest(false)
    }
  }, [apiKey, symbol, exchange, hasSymbol, useQuotesFallback, useDepthFallback, mode])

  // Fetch on mount and when symbol changes
  // Use refs to track current state and avoid stale closures in intervals
  const enabledRef = useRef(enabled)
  const hasSymbolRef = useRef(hasSymbol)
  const fetchRestDataRef = useRef(fetchRestData)

  // Keep refs in sync with latest values
  useEffect(() => {
    enabledRef.current = enabled
    hasSymbolRef.current = hasSymbol
    fetchRestDataRef.current = fetchRestData
  }, [enabled, hasSymbol, fetchRestData])

  useEffect(() => {
    if (!enabled || !hasSymbol) return

    // Initial fetch - use ref to ensure we have the latest function
    fetchRestDataRef.current()

    // Set up periodic refresh
    const interval = setInterval(() => {
      // Check current enabled state before fetching
      if (enabledRef.current && hasSymbolRef.current) {
        fetchRestDataRef.current()
      }
    }, refreshInterval)

    return () => clearInterval(interval)
    // Only depend on stable values that should trigger new interval setup
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, hasSymbol, symbol, exchange, refreshInterval])

  // Reset state when symbol changes
  useEffect(() => {
    setRestQuotes(null)
    setRestDepth(null)
  }, [symbol, exchange])

  // Convert REST depth format to normalized format
  const restDepthNormalized: NormalizedDepth | undefined = useMemo(() => {
    if (!restDepth) return undefined
    return {
      buy: restDepth.bids.map(level => ({ price: level.price, quantity: level.quantity })),
      sell: restDepth.asks.map(level => ({ price: level.price, quantity: level.quantity })),
    }
  }, [restDepth])

  // Merge WebSocket and REST data
  const mergedData: LiveQuoteData = useMemo(() => {
    // Determine best depth source
    const depth = wsData?.depth ?? restDepthNormalized

    // Determine best bid/ask from depth or quotes
    const bidPrice = wsData?.depth?.buy?.[0]?.price ??
                     restDepthNormalized?.buy?.[0]?.price ??
                     wsData?.bid_price ??
                     restQuotes?.bid
    const askPrice = wsData?.depth?.sell?.[0]?.price ??
                     restDepthNormalized?.sell?.[0]?.price ??
                     wsData?.ask_price ??
                     restQuotes?.ask
    const bidSize = wsData?.depth?.buy?.[0]?.quantity ??
                    restDepthNormalized?.buy?.[0]?.quantity ??
                    wsData?.bid_size
    const askSize = wsData?.depth?.sell?.[0]?.quantity ??
                    restDepthNormalized?.sell?.[0]?.quantity ??
                    wsData?.ask_size

    // Merge all data with priority: WebSocket > REST depth > REST quotes
    return {
      ltp: wsData?.ltp ?? restDepth?.ltp ?? restQuotes?.ltp,
      open: wsData?.open ?? restDepth?.open ?? restQuotes?.open,
      high: wsData?.high ?? restDepth?.high ?? restQuotes?.high,
      low: wsData?.low ?? restDepth?.low ?? restQuotes?.low,
      close: wsData?.close ?? restDepth?.prev_close ?? restQuotes?.prev_close,
      volume: wsData?.volume ?? restDepth?.volume ?? restQuotes?.volume,
      oi: restDepth?.oi ?? restQuotes?.oi,
      change: wsData?.change,
      changePercent: wsData?.change_percent,
      bidPrice,
      askPrice,
      bidSize,
      askSize,
      depth,
    }
  }, [wsData, restQuotes, restDepth, restDepthNormalized])

  // Calculate change if not available from WebSocket
  const dataWithChange: LiveQuoteData = useMemo(() => {
    if (mergedData.change !== undefined) return mergedData

    const change = mergedData.ltp && mergedData.close
      ? mergedData.ltp - mergedData.close
      : undefined
    const changePercent = change && mergedData.close
      ? (change / mergedData.close) * 100
      : undefined

    return {
      ...mergedData,
      change,
      changePercent,
    }
  }, [mergedData])

  // Determine data source
  const dataSource: 'websocket' | 'rest' | 'none' = useMemo(() => {
    if (hasWsData) return 'websocket'
    if (restQuotes || restDepth) return 'rest'
    return 'none'
  }, [hasWsData, restQuotes, restDepth])

  return {
    data: dataWithChange,
    isLive,
    isConnected: wsConnected,
    isLoading: isLoadingRest && !restQuotes && !restDepth,
    isPaused: wsPaused,
    isFallbackMode,
    dataSource,
    refresh: fetchRestData,
  }
}
