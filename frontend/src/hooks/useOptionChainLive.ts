import { useEffect, useMemo, useRef, useState } from 'react'
import type { OptionChainResponse, OptionStrike } from '@/types/option-chain'
import { useOptionChainPolling } from './useOptionChainPolling'
import { useMarketData } from './useMarketData'

// Index symbols that use NSE_INDEX/BSE_INDEX for quotes (matches backend lists)
const NSE_INDEX_SYMBOLS = new Set([
  'NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY',
  'NIFTYNXT50', 'NIFTYIT', 'NIFTYPHARMA', 'NIFTYBANK',
])
const BSE_INDEX_SYMBOLS = new Set(['SENSEX', 'BANKEX', 'SENSEX50'])

function getUnderlyingExchange(symbol: string, optionExchange: string): string {
  if (NSE_INDEX_SYMBOLS.has(symbol)) return 'NSE_INDEX'
  if (BSE_INDEX_SYMBOLS.has(symbol)) return 'BSE_INDEX'
  return optionExchange === 'BFO' ? 'BSE' : 'NSE'
}

// Round price to nearest tick size (e.g., 0.05 for options)
// Fixes broker WebSocket data that may not be aligned to tick size
function roundToTickSize(price: number | undefined, tickSize: number | undefined): number | undefined {
  if (price === undefined || price === null) return undefined
  if (!tickSize || tickSize <= 0) return price
  // Round to nearest tick and fix floating point precision
  return Number((Math.round(price / tickSize) * tickSize).toFixed(2))
}

interface UseOptionChainLiveOptions {
  enabled: boolean
  /** Polling interval for OI/Volume data in ms (default: 30000) */
  oiRefreshInterval?: number
  /** Pause WebSocket and polling when tab is hidden (default: true) */
  pauseWhenHidden?: boolean
}

/**
 * Hook for real-time option chain data using hybrid approach:
 * - WebSocket for real-time LTP/Bid/Ask updates
 * - REST polling for OI/Volume data (less frequent)
 *
 * @param apiKey - OpenAlgo API key
 * @param underlying - Underlying symbol (NIFTY, BANKNIFTY, etc.)
 * @param exchange - Exchange code for underlying (NSE_INDEX, BSE_INDEX)
 * @param optionExchange - Exchange code for options (NFO, BFO)
 * @param expiryDate - Expiry date in DDMMMYY format
 * @param strikeCount - Number of strikes to fetch
 * @param options - Live options
 */
export function useOptionChainLive(
  apiKey: string | null,
  underlying: string,
  exchange: string,
  optionExchange: string,
  expiryDate: string,
  strikeCount: number,
  options: UseOptionChainLiveOptions = { enabled: true, oiRefreshInterval: 30000, pauseWhenHidden: true }
) {
  const { enabled, oiRefreshInterval = 30000, pauseWhenHidden = true } = options

  // Track merged data with WebSocket updates
  const [mergedData, setMergedData] = useState<OptionChainResponse | null>(null)
  const [lastLtpUpdate, setLastLtpUpdate] = useState<Date | null>(null)

  // Polling for OI/Volume/Greeks (less frequent)
  const {
    data: polledData,
    isLoading,
    isConnected: isPollingConnected,
    isPaused: isPollingPaused,
    error,
    lastUpdate: lastPollUpdate,
    refetch,
  } = useOptionChainPolling(apiKey, underlying, exchange, expiryDate, strikeCount, {
    enabled,
    refreshInterval: oiRefreshInterval,
    pauseWhenHidden,
  })

  // Build symbol list from polled data for WebSocket subscription
  // Includes both option symbols AND underlying index for real-time spot price
  const wsSymbols = useMemo(() => {
    const symbols: Array<{ symbol: string; exchange: string }> = []

    // Add underlying symbol for real-time spot price
    // Use correct exchange based on whether it's an index or stock
    const underlyingExch = getUnderlyingExchange(underlying, optionExchange)
    symbols.push({ symbol: underlying, exchange: underlyingExch })

    // Add all option symbols
    if (polledData?.chain) {
      for (const strike of polledData.chain) {
        if (strike.ce?.symbol) {
          symbols.push({ symbol: strike.ce.symbol, exchange: optionExchange })
        }
        if (strike.pe?.symbol) {
          symbols.push({ symbol: strike.pe.symbol, exchange: optionExchange })
        }
      }
    }

    return symbols
  }, [polledData?.chain, optionExchange, underlying])

  // WebSocket for real-time LTP + Depth (Bid/Ask) updates
  const {
    data: wsData,
    isConnected: isWsConnected,
    isAuthenticated: isWsAuthenticated,
    isPaused: isWsPaused,
  } = useMarketData({
    symbols: wsSymbols,
    mode: 'Depth', // Get LTP + Bid/Ask depth
    enabled: enabled && wsSymbols.length > 0,
  })

  // Track last LTP update time using ref to avoid triggering effect loops
  const lastLtpUpdateRef = useRef<number>(0)

  // Merge WebSocket LTP data into polled option chain data
  useEffect(() => {
    if (!polledData) {
      setMergedData(null)
      return
    }

    // If no WebSocket data yet, use polled data as-is
    if (wsData.size === 0) {
      setMergedData(polledData)
      return
    }

    // Create merged chain with WebSocket LTP updates
    const mergedChain: OptionStrike[] = polledData.chain.map((strike) => {
      const newStrike = { ...strike }

      // Update CE data from WebSocket
      if (strike.ce?.symbol) {
        const wsKey = `${optionExchange}:${strike.ce.symbol}`
        const wsSymbolData = wsData.get(wsKey)
        if (wsSymbolData?.data) {
          // Try depth data first (dp packets), fallback to quote data (sf packets)
          // Depth mode: depth.buy[0].price, depth.buy[0].quantity
          // Quote mode: bid_price, ask_price, bid_size, ask_size
          const depthBuy = wsSymbolData.data.depth?.buy?.[0]
          const depthSell = wsSymbolData.data.depth?.sell?.[0]
          const tickSize = strike.ce.tick_size
          newStrike.ce = {
            ...strike.ce,
            ltp: roundToTickSize(wsSymbolData.data.ltp, tickSize) ?? strike.ce.ltp,
            bid: roundToTickSize(depthBuy?.price ?? wsSymbolData.data.bid_price, tickSize) ?? strike.ce.bid,
            ask: roundToTickSize(depthSell?.price ?? wsSymbolData.data.ask_price, tickSize) ?? strike.ce.ask,
            bid_qty: depthBuy?.quantity ?? wsSymbolData.data.bid_size ?? strike.ce.bid_qty ?? 0,
            ask_qty: depthSell?.quantity ?? wsSymbolData.data.ask_size ?? strike.ce.ask_qty ?? 0,
          }
        }
      }

      // Update PE data from WebSocket
      if (strike.pe?.symbol) {
        const wsKey = `${optionExchange}:${strike.pe.symbol}`
        const wsSymbolData = wsData.get(wsKey)
        if (wsSymbolData?.data) {
          // Try depth data first (dp packets), fallback to quote data (sf packets)
          const depthBuy = wsSymbolData.data.depth?.buy?.[0]
          const depthSell = wsSymbolData.data.depth?.sell?.[0]
          const tickSize = strike.pe.tick_size
          newStrike.pe = {
            ...strike.pe,
            ltp: roundToTickSize(wsSymbolData.data.ltp, tickSize) ?? strike.pe.ltp,
            bid: roundToTickSize(depthBuy?.price ?? wsSymbolData.data.bid_price, tickSize) ?? strike.pe.bid,
            ask: roundToTickSize(depthSell?.price ?? wsSymbolData.data.ask_price, tickSize) ?? strike.pe.ask,
            bid_qty: depthBuy?.quantity ?? wsSymbolData.data.bid_size ?? strike.pe.bid_qty ?? 0,
            ask_qty: depthSell?.quantity ?? wsSymbolData.data.ask_size ?? strike.pe.ask_qty ?? 0,
          }
        }
      }

      return newStrike
    })

    // Check if any LTP was updated (using ref to avoid loop)
    let hasLtpUpdate = false
    for (const [, symbolData] of wsData) {
      if (symbolData.lastUpdate && symbolData.lastUpdate > lastLtpUpdateRef.current) {
        hasLtpUpdate = true
        lastLtpUpdateRef.current = symbolData.lastUpdate
        break
      }
    }

    if (hasLtpUpdate) {
      setLastLtpUpdate(new Date())
    }

    // Get real-time underlying spot price from WebSocket
    const underlyingExch = getUnderlyingExchange(underlying, optionExchange)
    const underlyingKey = `${underlyingExch}:${underlying}`
    const underlyingWsData = wsData.get(underlyingKey)
    const underlyingLtp = underlyingWsData?.data?.ltp ?? polledData.underlying_ltp

    setMergedData({
      ...polledData,
      underlying_ltp: underlyingLtp,
      chain: mergedChain,
    })
  }, [polledData, wsData, optionExchange, underlying])

  // Determine streaming status
  const isStreaming = isWsConnected && isWsAuthenticated && wsSymbols.length > 0
  const isPaused = isPollingPaused || isWsPaused

  // Combined last update (use LTP update if more recent)
  const lastUpdate = useMemo(() => {
    if (!lastPollUpdate && !lastLtpUpdate) return null
    if (!lastPollUpdate) return lastLtpUpdate
    if (!lastLtpUpdate) return lastPollUpdate
    return lastLtpUpdate > lastPollUpdate ? lastLtpUpdate : lastPollUpdate
  }, [lastPollUpdate, lastLtpUpdate])

  return {
    data: mergedData,
    isLoading,
    isConnected: isPollingConnected,
    isStreaming,
    isPaused,
    error,
    lastUpdate,
    streamingSymbols: wsSymbols.length,
    refetch,
  }
}
