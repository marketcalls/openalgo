import { useEffect, useMemo, useRef, useState } from 'react'
import type { SymbolData } from '@/lib/MarketDataManager'
import { chainGreeks, forwardFromParity, priceForGreeks, yearsToExpiry } from '@/lib/optionGreeks'
import type { OptionChainResponse, OptionStrike } from '@/types/option-chain'
import { useMarketData } from './useMarketData'
import { useOptionChainPolling } from './useOptionChainPolling'

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
): { chain: OptionStrike[]; forwardPrice: number | null } {
  const timeToExpiry = yearsToExpiry(polledData.expiry_ts, clockOffsetMs)
  if (timeToExpiry <= 0) {
    return { chain, forwardPrice: polledData.forward_price ?? null }
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
    return { chain, forwardPrice: polledData.forward_price ?? null }
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

  return {
    forwardPrice: forward,
    chain: chain.map((row, i) => {
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
    }),
  }
}

/**
 * Merge exact contract ticks into a chain and recompute its complete Greek
 * vector from that chain's own expiry and ATM parity pair.
 */
export function mergeOptionChainMarketData(
  polledData: OptionChainResponse,
  optionExchange: string,
  marketData: Map<string, SymbolData>,
  clockOffsetMs: number,
  interestRate = 0,
  fallbackUnderlyingLtp = polledData.underlying_ltp,
  recomputeWithoutTicks = true
): OptionChainResponse {
  const underlyingKey = `${polledData.underlying_exchange}:${polledData.underlying_symbol}`
  const hasRelevantTicks =
    marketData.has(underlyingKey) ||
    polledData.chain.some(
      (row) =>
        (row.ce?.symbol && marketData.has(`${optionExchange}:${row.ce.symbol}`)) ||
        (row.pe?.symbol && marketData.has(`${optionExchange}:${row.pe.symbol}`))
    )
  if (!recomputeWithoutTicks && !hasRelevantTicks) return polledData

  const mergedChain = polledData.chain.map((strike) => {
    const mergeContract = (contract: typeof strike.ce) => {
      if (!contract?.symbol) return contract
      const tick = marketData.get(`${optionExchange}:${contract.symbol}`)?.data
      if (!tick) return contract

      const depthBuy = tick.depth?.buy?.[0]
      const depthSell = tick.depth?.sell?.[0]
      return {
        ...contract,
        ltp: roundToTickSize(tick.ltp, contract.tick_size) ?? contract.ltp,
        bid:
          roundToTickSize(depthBuy?.price ?? tick.bid_price, contract.tick_size) ?? contract.bid,
        ask:
          roundToTickSize(depthSell?.price ?? tick.ask_price, contract.tick_size) ?? contract.ask,
        bid_qty: depthBuy?.quantity ?? tick.bid_size ?? contract.bid_qty ?? 0,
        ask_qty: depthSell?.quantity ?? tick.ask_size ?? contract.ask_qty ?? 0,
      }
    }

    return {
      ...strike,
      ce: mergeContract(strike.ce),
      pe: mergeContract(strike.pe),
    }
  })

  const underlyingTick = marketData.get(underlyingKey)
  const underlyingLtp = underlyingTick?.data?.ltp ?? fallbackUnderlyingLtp
  const repriced = withGreeks(
    mergedChain,
    polledData,
    underlyingLtp,
    clockOffsetMs,
    interestRate
  )

  return {
    ...polledData,
    underlying_ltp: underlyingLtp,
    forward_price: hasRelevantTicks
      ? repriced.forwardPrice
      : (polledData.forward_price ?? repriced.forwardPrice),
    chain: repriced.chain,
  }
}

/** Exclude REST fallback values and cache entries from another WS session. */
export function currentWebSocketMarketData(
  marketData: Map<string, SymbolData>,
  isAuthenticated: boolean,
  connectionEpoch: number,
  relevantKeys?: ReadonlySet<string>
): Map<string, SymbolData> {
  if (!isAuthenticated) return new Map()
  return new Map(
    Array.from(marketData).filter(
      ([key, symbolData]) =>
        (relevantKeys === undefined || relevantKeys.has(key.toUpperCase())) &&
        symbolData.updateSource === 'websocket' && symbolData.connectionEpoch === connectionEpoch
    )
  )
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
    dataIdentity,
    refetch,
  } = useOptionChainPolling(apiKey, underlying, exchange, expiryDate, strikeCount, {
    enabled,
    refreshInterval: oiRefreshInterval,
    pauseWhenHidden,
    derivativeExchange: optionExchange,
  })

  // Build symbol list from the latest option-chain response for subscription.
  const wsSymbols = useMemo(() => {
    const symbols: Array<{ symbol: string; exchange: string }> = []

    // Add the canonical underlying reference for real-time price updates.
    // The backend, rather than this hook, resolves a perpetual or near-month future when needed.
    // For CRYPTO: bare underlying (e.g. BTC) isn't tradeable — use perpetual (e.g. BTCUSDFUT)
    if (polledData) {
      symbols.push({
        symbol: polledData.underlying_symbol,
        exchange: polledData.underlying_exchange,
      })
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
  }, [polledData, optionExchange])

  // WebSocket for real-time LTP + Depth (Bid/Ask) updates
  const {
    data: wsData,
    isConnected: isWsConnected,
    isAuthenticated: isWsAuthenticated,
    isPaused: isWsPaused,
    connectionEpoch: wsConnectionEpoch,
  } = useMarketData({
    symbols: wsSymbols,
    mode: 'Depth', // Get LTP + Bid/Ask depth
    enabled: enabled && wsSymbols.length > 0,
  })
  const currentWsData = useMemo(() => {
    const relevantKeys = new Set(
      wsSymbols.map(({ exchange: symbolExchange, symbol }) =>
        `${symbolExchange}:${symbol}`.toUpperCase()
      )
    )
    return currentWebSocketMarketData(
      wsData,
      isWsAuthenticated && enabled,
      wsConnectionEpoch,
      relevantKeys
    )
  }, [wsData, isWsAuthenticated, wsConnectionEpoch, wsSymbols, enabled])

  // Track last LTP update time using ref to avoid triggering effect loops
  const lastLtpUpdateRef = useRef<number>(0)

  // biome-ignore lint/correctness/useExhaustiveDependencies: request/session identity changes must explicitly invalidate stream freshness even though the values are reset triggers rather than effect inputs
  useEffect(() => {
    lastLtpUpdateRef.current = 0
    setLastLtpUpdate(null)
  }, [
    apiKey,
    underlying,
    exchange,
    optionExchange,
    expiryDate,
    strikeCount,
    enabled,
    isWsAuthenticated,
    wsConnectionEpoch,
  ])

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

    // Only manager-tagged WebSocket updates prove stream freshness. Recent
    // REST fallback/cache updates remain valid prices but must not imply Live.
    let newestLtpUpdate = lastLtpUpdateRef.current
    for (const [, symbolData] of currentWsData) {
      if (symbolData.lastUpdate && symbolData.lastUpdate > newestLtpUpdate) {
        newestLtpUpdate = symbolData.lastUpdate
      }
    }

    if (newestLtpUpdate > lastLtpUpdateRef.current) {
      lastLtpUpdateRef.current = newestLtpUpdate
      setLastLtpUpdate(new Date(newestLtpUpdate))
    }

    setMergedData(
      mergeOptionChainMarketData(
        polledData,
        optionExchange,
        currentWsData,
        clockOffsetRef.current,
        interestRate
      )
    )
  }, [
    polledData,
    currentWsData,
    optionExchange,
    interestRate,
  ])

  // Determine streaming status
  const isStreaming = enabled && isWsConnected && isWsAuthenticated && wsSymbols.length > 0
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
    lastStreamUpdate: lastLtpUpdate,
    dataIdentity,
    streamingSymbols: wsSymbols.length,
    clockOffsetMs: clockOffsetRef.current,
    forwardPrice: mergedData?.forward_price ?? null,
    refetch,
  }
}
