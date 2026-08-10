import { useEffect, useMemo, useRef, useState } from 'react'
import { chainGreeks, forwardFromParity, priceForGreeks, yearsToExpiry } from '@/lib/optionGreeks'
import type { OptionChainResponse, OptionStrike } from '@/types/option-chain'
import { useMarketData } from './useMarketData'
import { useOptionChainPolling } from './useOptionChainPolling'

// Index symbols that use NSE_INDEX/BSE_INDEX for quotes (matches backend lists)
const NSE_INDEX_SYMBOLS = new Set([
  'NIFTY',
  'BANKNIFTY',
  'FINNIFTY',
  'MIDCPNIFTY',
  'NIFTYNXT50',
  'NIFTYIT',
  'NIFTYPHARMA',
  'NIFTYBANK',
])
const BSE_INDEX_SYMBOLS = new Set(['SENSEX', 'BANKEX', 'SENSEX50'])

function getUnderlyingExchange(symbol: string, optionExchange: string): string {
  const normalizedExchange = optionExchange.toUpperCase()
  if (NSE_INDEX_SYMBOLS.has(symbol)) return 'NSE_INDEX'
  if (BSE_INDEX_SYMBOLS.has(symbol)) return 'BSE_INDEX'
  if (normalizedExchange === 'CRYPTO') return 'CRYPTO'
  if (normalizedExchange === 'BFO') return 'BSE'
  if (normalizedExchange === 'NFO') return 'NSE'
  return normalizedExchange
}

// Round price to nearest tick size (e.g., 0.05 for options)
// Fixes broker WebSocket data that may not be aligned to tick size
function roundToTickSize(
  price: number | undefined,
  tickSize: number | undefined
): number | undefined {
  if (price === undefined || price === null) return undefined
  if (!tickSize || tickSize <= 0) return price
  // Round to nearest tick and fix floating point precision
  return Number((Math.round(price / tickSize) * tickSize).toFixed(2))
}

/**
 * Attach Greeks to a merged chain, recomputed from the prices it already holds.
 *
 * This runs on every tick batch rather than on the 30s poll, which is what makes
 * the Greeks stream: they cost no extra network traffic and no broker calls,
 * because every input is already on the client. A full 80-leg chain is well
 * under a millisecond.
 *
 * Both the forward price and the tenor are recomputed here too, so delta shifts
 * as the underlying moves and theta decays between polls.
 */
function withGreeks(
  chain: OptionStrike[],
  polledData: OptionChainResponse,
  underlyingLtp: number,
  clockOffsetMs: number,
  interestRate: number
): OptionStrike[] {
  const timeToExpiry = yearsToExpiry(polledData.expiry_ts, clockOffsetMs)
  if (timeToExpiry <= 0) {
    return chain
  }

  // Black-76 prices off the forward. The ATM legs are already streaming, so
  // put-call parity gives a live forward for free, and it tracks the futures
  // premium that a spot LTP would miss.
  const atmRow = chain.find((row) => row.strike === polledData.atm_strike)
  const forward = forwardFromParity(
    polledData.atm_strike,
    atmRow?.ce ? priceForGreeks(atmRow.ce.ltp, atmRow.ce.bid, atmRow.ce.ask) : 0,
    atmRow?.pe ? priceForGreeks(atmRow.pe.ltp, atmRow.pe.bid, atmRow.pe.ask) : 0,
    underlyingLtp
  )

  if (!(forward > 0)) {
    return chain
  }

  const greeks = chainGreeks(
    chain.map((row) => ({
      strike: row.strike,
      cePrice: row.ce ? priceForGreeks(row.ce.ltp, row.ce.bid, row.ce.ask) : 0,
      pePrice: row.pe ? priceForGreeks(row.pe.ltp, row.pe.bid, row.pe.ask) : 0,
    })),
    forward,
    timeToExpiry,
    interestRate
  )

  return chain.map((row, i) => {
    const { ce: ceGreeks, pe: peGreeks } = greeks[i]
    return {
      ...row,
      // Spread onto a fresh object: `row.ce` can still be the polled response's
      // own object when this leg had no tick, and mutating that would corrupt
      // the polling hook's state.
      ce: row.ce
        ? {
            ...row.ce,
            implied_volatility: ceGreeks?.iv,
            delta: ceGreeks?.delta,
            gamma: ceGreeks?.gamma,
            theta: ceGreeks?.theta,
            vega: ceGreeks?.vega,
          }
        : null,
      pe: row.pe
        ? {
            ...row.pe,
            implied_volatility: peGreeks?.iv,
            delta: peGreeks?.delta,
            gamma: peGreeks?.gamma,
            theta: peGreeks?.theta,
            vega: peGreeks?.vega,
          }
        : null,
    }
  })
}

interface UseOptionChainLiveOptions {
  enabled: boolean
  /** Polling interval for OI/Volume data in ms (default: 30000) */
  oiRefreshInterval?: number
  /** Pause WebSocket and polling when tab is hidden (default: true) */
  pauseWhenHidden?: boolean
  /**
   * Risk-free rate as an annualized percentage, used for Greeks.
   * Defaults to 0, matching the server's DEFAULT_INTEREST_RATES.
   */
  interestRate?: number
}

/**
 * Hook for real-time option chain data using hybrid approach:
 * - WebSocket for real-time LTP/Bid/Ask updates
 * - REST polling for OI/Volume data (less frequent)
 * - Greeks recomputed locally on every tick from the streaming prices
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
  options: UseOptionChainLiveOptions = {
    enabled: true,
    oiRefreshInterval: 30000,
    pauseWhenHidden: true,
  }
) {
  const { enabled, oiRefreshInterval = 30000, pauseWhenHidden = true, interestRate = 0 } = options

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
    // For CRYPTO: bare underlying (e.g. BTC) isn't tradeable — use perpetual (e.g. BTCUSDFUT)
    const underlyingExch = getUnderlyingExchange(underlying, optionExchange)
    if (underlyingExch === 'CRYPTO') {
      symbols.push({ symbol: `${underlying}USDFUT`, exchange: underlyingExch })
    } else {
      symbols.push({ symbol: underlying, exchange: underlyingExch })
    }

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

  // Time to expiry is computed in the browser, so a skewed client clock would
  // bias every Greek on the page. Each poll carries the server's clock; the
  // difference corrects it. Network latency makes this off by roughly half an
  // RTT, which is irrelevant against a tenor measured in hours or days.
  const clockOffsetRef = useRef<number>(0)
  useEffect(() => {
    if (polledData?.server_ts) {
      clockOffsetRef.current = polledData.server_ts * 1000 - Date.now()
    }
  }, [polledData?.server_ts])

  // Merge WebSocket LTP data into polled option chain data
  useEffect(() => {
    if (!polledData) {
      setMergedData(null)
      return
    }

    // No WebSocket data yet: still compute Greeks off the polled prices so the
    // first paint is complete rather than showing dashes until the first tick.
    if (wsData.size === 0) {
      setMergedData({
        ...polledData,
        chain: withGreeks(
          polledData.chain,
          polledData,
          polledData.underlying_ltp,
          clockOffsetRef.current,
          interestRate
        ),
      })
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
            bid:
              roundToTickSize(depthBuy?.price ?? wsSymbolData.data.bid_price, tickSize) ??
              strike.ce.bid,
            ask:
              roundToTickSize(depthSell?.price ?? wsSymbolData.data.ask_price, tickSize) ??
              strike.ce.ask,
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
            bid:
              roundToTickSize(depthBuy?.price ?? wsSymbolData.data.bid_price, tickSize) ??
              strike.pe.bid,
            ask:
              roundToTickSize(depthSell?.price ?? wsSymbolData.data.ask_price, tickSize) ??
              strike.pe.ask,
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
      chain: withGreeks(
        mergedChain,
        polledData,
        underlyingLtp,
        clockOffsetRef.current,
        interestRate
      ),
    })
  }, [polledData, wsData, optionExchange, underlying, interestRate])

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
