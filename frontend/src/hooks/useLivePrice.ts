import { useCallback, useEffect, useMemo, useState } from 'react'
import { tradingApi, type QuotesData } from '@/api/trading'
import { useMarketData } from '@/hooks/useMarketData'
import { useMarketStatus } from '@/hooks/useMarketStatus'
import { useAuthStore } from '@/stores/authStore'

/**
 * Base interface for items that can have live price data
 */
export interface PriceableItem {
  symbol: string
  exchange: string
  ltp?: number
  pnl?: number
  pnlpercent?: number
  quantity?: number
  average_price?: number
}

/**
 * Configuration options for useLivePrice hook
 */
export interface UseLivePriceOptions {
  /** Whether the hook is enabled (default: true) */
  enabled?: boolean
  /** Time in ms after which WebSocket data is considered stale (default: 5000) */
  staleThreshold?: number
  /** Whether to use MultiQuotes API as fallback when WebSocket unavailable (default: true) */
  useMultiQuotesFallback?: boolean
  /** Interval in ms to refresh MultiQuotes data (default: 30000) */
  multiQuotesRefreshInterval?: number
}

/**
 * Return type for useLivePrice hook
 */
export interface UseLivePriceResult<T extends PriceableItem> {
  /** Enhanced items with real-time LTP and recalculated PnL */
  data: T[]
  /** Whether real-time data is available (WebSocket connected AND market open) */
  isLive: boolean
  /** Whether WebSocket is connected */
  isConnected: boolean
  /** Whether any market is currently open */
  isAnyMarketOpen: boolean
  /** Map of MultiQuotes data for external access if needed */
  multiQuotes: Map<string, QuotesData>
  /** Manually refresh MultiQuotes data */
  refreshMultiQuotes: () => Promise<void>
}

/**
 * Centralized hook for real-time price data with automatic fallback.
 *
 * Priority chain:
 * 1. WebSocket LTP (when market is open and data is fresh)
 * 2. MultiQuotes API (fallback when WebSocket unavailable)
 * 3. REST API data (baseline from initial fetch)
 *
 * @example
 * ```tsx
 * const { data: enhancedHoldings, isLive } = useLivePrice(holdings, {
 *   enabled: holdings.length > 0,
 *   useMultiQuotesFallback: true,
 * });
 * ```
 */
export function useLivePrice<T extends PriceableItem>(
  items: T[],
  options: UseLivePriceOptions = {}
): UseLivePriceResult<T> {
  const {
    enabled = true,
    staleThreshold = 5000,
    useMultiQuotesFallback = true,
    multiQuotesRefreshInterval = 30000,
  } = options

  const { apiKey } = useAuthStore()
  const { isMarketOpen, isAnyMarketOpen } = useMarketStatus()
  const anyMarketOpen = isAnyMarketOpen()

  // State for MultiQuotes fallback data
  const [multiQuotes, setMultiQuotes] = useState<Map<string, QuotesData>>(new Map())

  // Extract symbols for WebSocket subscription
  const symbols = useMemo(
    () =>
      items.map((item) => ({
        symbol: item.symbol,
        exchange: item.exchange,
      })),
    [items]
  )

  // WebSocket market data - connect when enabled (market check removed for testing)
  const { data: marketData, isConnected: wsConnected } = useMarketData({
    symbols,
    mode: 'LTP',
    enabled: enabled && items.length > 0,
  })

  // Effective live status
  const isLive = wsConnected && anyMarketOpen

  /**
   * Fetch MultiQuotes data from API
   */
  const fetchMultiQuotes = useCallback(async () => {
    if (!apiKey || items.length === 0 || !useMultiQuotesFallback) return

    try {
      const symbolsList = items.map((item) => ({
        symbol: item.symbol,
        exchange: item.exchange,
      }))

      const response = await tradingApi.getMultiQuotes(apiKey, symbolsList)

      if (response.status === 'success' && response.results) {
        const quotesMap = new Map<string, QuotesData>()
        response.results.forEach((result) => {
          const key = `${result.exchange}:${result.symbol}`
          if (result.data) {
            quotesMap.set(key, result.data)
          }
        })
        setMultiQuotes(quotesMap)
      }
    } catch {
      // Silently fail - MultiQuotes is a fallback mechanism
      console.debug('MultiQuotes fetch failed, using cached/REST data')
    }
  }, [apiKey, items, useMultiQuotesFallback])

  // Fetch MultiQuotes on mount and when items change
  useEffect(() => {
    if (!enabled || items.length === 0 || !useMultiQuotesFallback) return

    // Initial fetch
    fetchMultiQuotes()

    // Set up periodic refresh
    const interval = setInterval(fetchMultiQuotes, multiQuotesRefreshInterval)

    return () => clearInterval(interval)
  }, [enabled, items.length, useMultiQuotesFallback, fetchMultiQuotes, multiQuotesRefreshInterval])

  /**
   * Enhance items with real-time LTP and calculated average_price
   * Priority: WebSocket (fresh + market open) → MultiQuotes → REST API
   *
   * Note: pnl and pnlpercent always come from REST API (not recalculated)
   * average_price is calculated backwards from: avgPrice = currentLtp - (pnl / qty)
   */
  const enhancedData = useMemo(() => {
    return items.map((item) => {
      const key = `${item.exchange}:${item.symbol}`
      const wsData = marketData.get(key)
      const mqData = multiQuotes.get(key)

      const qty = item.quantity || 0
      const originalPnl = item.pnl || 0

      // Check if market is open for this exchange
      const exchangeMarketOpen = isMarketOpen(item.exchange)

      // Check if WebSocket LTP is fresh AND market is open
      const hasWsData =
        exchangeMarketOpen &&
        wsData?.data?.ltp &&
        wsData.lastUpdate &&
        Date.now() - wsData.lastUpdate < staleThreshold

      // Check if we have MultiQuotes data (fallback when WebSocket not available)
      const hasMqData = !hasWsData && mqData?.ltp

      // Determine the best available LTP source
      let currentLtp: number | undefined
      let dataSource: 'websocket' | 'multiquotes' | 'rest' = 'rest'

      if (hasWsData && wsData?.data?.ltp) {
        currentLtp = wsData.data.ltp
        dataSource = 'websocket'
      } else if (hasMqData && mqData?.ltp) {
        currentLtp = mqData.ltp
        dataSource = 'multiquotes'
      } else {
        currentLtp = item.ltp
        dataSource = 'rest'
      }

      // For closed positions (qty=0), preserve all REST API values
      if (qty === 0) {
        return {
          ...item,
          ltp: currentLtp,
          _dataSource: dataSource,
        } as T & { _dataSource: string }
      }

      // Calculate average price from REST data if not provided
      // Formula: AvgPrice = LTP - (PnL / Qty)
      let avgPrice = item.average_price
      if (!avgPrice && currentLtp && qty !== 0) {
        avgPrice = currentLtp - originalPnl / qty
      }

      // Return with updated LTP and calculated avgPrice
      // pnl and pnlpercent always from REST API
      return {
        ...item,
        ltp: currentLtp,
        average_price: avgPrice,
        // pnl and pnlpercent preserved from REST API via spread
        _dataSource: dataSource,
      } as T & { _dataSource: string }
    })
  }, [items, marketData, multiQuotes, isMarketOpen, staleThreshold])

  return {
    data: enhancedData,
    isLive,
    isConnected: wsConnected,
    isAnyMarketOpen: anyMarketOpen,
    multiQuotes,
    refreshMultiQuotes: fetchMultiQuotes,
  }
}

/**
 * Calculate aggregated stats from items with live price data
 */
export function calculateLiveStats<T extends PriceableItem>(
  items: T[],
  originalStats?: {
    totalholdingvalue?: number
    totalinvvalue?: number
    totalprofitandloss?: number
    totalpnlpercentage?: number
  }
) {
  if (!originalStats) return null

  let totalPnl = 0
  let totalInvestment = 0
  let totalHoldingValue = 0

  items.forEach((item) => {
    totalPnl += item.pnl || 0
    const avgPrice = item.average_price || 0
    const qty = item.quantity || 0
    const ltp = item.ltp || avgPrice
    totalInvestment += avgPrice * qty
    totalHoldingValue += ltp * qty
  })

  const totalPnlPercent = totalInvestment > 0 ? (totalPnl / totalInvestment) * 100 : 0

  return {
    ...originalStats,
    totalholdingvalue: totalHoldingValue,
    totalinvvalue: totalInvestment,
    totalprofitandloss: totalPnl,
    totalpnlpercentage: totalPnlPercent,
  }
}
