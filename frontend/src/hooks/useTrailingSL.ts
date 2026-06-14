/**
 * useTrailingSL — browser-driven stop-loss / trailing-SL engine for the scalping terminal.
 *
 * Evaluates each tracked leg's SL on every LTP tick:
 *  - trail only RAISES the stop, never lowers it
 *  - trailing does not start until price is >= MIN_TRAIL_PROFIT above entry (1cliq rule)
 *  - on breach, fires a risk-reducing MARKET exit sized to the CURRENT open position
 *    (not a stale saved quantity), and only clears the SL once the exit succeeds
 *
 * The engine subscribes to the live feed for EVERY active SL itself, so a stop-loss
 * restored on reload (or for a leg that isn't the currently-selected CE/PE) is still
 * monitored — "state survives reload" is a real safety guarantee, not cosmetic.
 *
 * SL config is persisted to the backend (database/scalping_db.py) so it survives reload.
 * Long legs (side BUY) trail with the stop below price; short legs (SELL) mirror it.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { scalpingApi } from '@/api/scalping'
import type { ScalpingAction, ScalpingProduct, ScalpingSLState } from '@/types/scalping'
import { showToast } from '@/utils/toast'
import { useMarketData } from './useMarketData'

const MIN_TRAIL_PROFIT = 1 // don't trail until >= 1 rupee in profit
const PERSIST_THROTTLE_MS = 2000
const EXIT_RETRY_COOLDOWN_MS = 2000 // throttle retries when an SL exit keeps failing

export interface SLState {
  symbol: string
  exchange: string
  product: ScalpingProduct
  side: ScalpingAction
  entry: number
  quantity: number
  initialSl: number
  trailingEnabled: boolean
  trailingStep: number
  highestPrice: number
  lowestPrice: number
  currentSl: number
  active: boolean
}

// Keyed by exchange:symbol:product to match the DB uniqueness
// (database/scalping_db.py UniqueConstraint) and avoid MIS/NRML collisions.
export function slKey(symbol: string, exchange: string, product: string): string {
  return `${exchange}:${symbol}:${product}`
}

// Find the active SL for a specific leg + product (matches the DB scoping, so an
// MIS and an NRML SL on the same strike are never confused).
export function findLegSL(
  slMap: Record<string, SLState>,
  symbol: string,
  exchange: string,
  product: string
): SLState | undefined {
  return slMap[slKey(symbol, exchange, product)]
}

function fromBackend(s: ScalpingSLState): SLState {
  const entry = s.entry_price ?? 0
  return {
    symbol: s.symbol,
    exchange: s.exchange,
    product: s.product,
    side: s.side,
    entry,
    quantity: s.quantity ?? 0,
    initialSl: s.initial_sl ?? entry,
    trailingEnabled: s.trailing_enabled ?? false,
    trailingStep: s.trailing_step ?? 0,
    highestPrice: s.highest_price ?? entry,
    lowestPrice: s.lowest_price ?? entry,
    currentSl: s.current_sl ?? s.initial_sl ?? entry,
    active: s.is_active ?? true,
  }
}

function toBackend(
  s: SLState
): Partial<ScalpingSLState> & Pick<ScalpingSLState, 'symbol' | 'exchange' | 'product'> {
  return {
    symbol: s.symbol,
    exchange: s.exchange,
    product: s.product,
    side: s.side,
    entry_price: s.entry,
    quantity: s.quantity,
    initial_sl: s.initialSl,
    trailing_enabled: s.trailingEnabled,
    trailing_step: s.trailingStep,
    highest_price: s.highestPrice,
    lowest_price: s.lowestPrice,
    current_sl: s.currentSl,
    is_active: s.active,
  }
}

/**
 * Pure trail evaluation. For a long (BUY) leg the stop sits below price and only
 * rises; for a short (SELL) leg it sits above price and only falls.
 * Returns the updated state and whether the stop was breached by this tick.
 */
export function evaluateTrail(sl: SLState, ltp: number): { next: SLState; breached: boolean } {
  if (sl.side === 'SELL') {
    const lowest = Math.min(sl.lowestPrice ?? sl.entry, ltp)
    let currentSl = sl.currentSl
    if (sl.trailingEnabled && sl.trailingStep > 0 && sl.entry - ltp >= MIN_TRAIL_PROFIT) {
      const candidate = lowest + sl.trailingStep
      if (candidate < currentSl) currentSl = candidate
    }
    return { next: { ...sl, lowestPrice: lowest, currentSl }, breached: ltp >= currentSl }
  }

  // Long leg (BUY)
  const highest = Math.max(sl.highestPrice ?? sl.entry, ltp)
  let currentSl = sl.currentSl
  if (sl.trailingEnabled && sl.trailingStep > 0 && ltp - sl.entry >= MIN_TRAIL_PROFIT) {
    const candidate = highest - sl.trailingStep
    if (candidate > currentSl) currentSl = candidate
  }
  return { next: { ...sl, highestPrice: highest, currentSl }, breached: ltp <= currentSl }
}

interface UseTrailingSLArgs {
  onAfterExit?: () => void
  // Returns the CURRENT signed net position quantity for a leg (0 if flat).
  // The SL exit is sized and directed from this, never from the saved quantity.
  resolvePosition?: (symbol: string, exchange: string, product: string) => number
}

export function useTrailingSL({ onAfterExit, resolvePosition }: UseTrailingSLArgs) {
  const [slMap, setSlMap] = useState<Record<string, SLState>>({})
  const slMapRef = useRef(slMap)
  slMapRef.current = slMap
  const lastPersistRef = useRef<Record<string, number>>({})
  const lastExitAttemptRef = useRef<Record<string, number>>({})
  const exitingRef = useRef<Set<string>>(new Set())
  const resolvePositionRef = useRef(resolvePosition)
  resolvePositionRef.current = resolvePosition
  const onAfterExitRef = useRef(onAfterExit)
  onAfterExitRef.current = onAfterExit

  // Subscribe the live feed for EVERY active SL (deduped), independent of which
  // CE/PE leg is selected, so restored/background SLs keep getting ticks.
  const slSymbols = useMemo(() => {
    const seen = new Set<string>()
    const list: Array<{ symbol: string; exchange: string }> = []
    for (const sl of Object.values(slMap)) {
      if (!sl.active) continue
      const k = `${sl.exchange}:${sl.symbol}`
      if (seen.has(k)) continue
      seen.add(k)
      list.push({ symbol: sl.symbol, exchange: sl.exchange })
    }
    return list
  }, [slMap])

  const { data: slMarketData } = useMarketData({
    symbols: slSymbols,
    mode: 'LTP',
    enabled: slSymbols.length > 0,
  })
  const slMarketDataRef = useRef(slMarketData)
  slMarketDataRef.current = slMarketData

  // Restore persisted SL config on mount.
  useEffect(() => {
    let cancelled = false
    scalpingApi
      .getSLStates()
      .then((resp) => {
        if (cancelled || resp.status !== 'success') return
        const restored: Record<string, SLState> = {}
        for (const s of resp.data) {
          restored[slKey(s.symbol, s.exchange, s.product)] = fromBackend(s)
        }
        setSlMap(restored)
      })
      .catch(() => {
        if (!cancelled) {
          showToast.error('Failed to restore active stop-losses — verify manually', 'orders')
        }
      })
    return () => {
      cancelled = true
    }
  }, [])

  const persist = useCallback((sl: SLState, force = false) => {
    const key = slKey(sl.symbol, sl.exchange, sl.product)
    const now = Date.now()
    if (!force && now - (lastPersistRef.current[key] ?? 0) < PERSIST_THROTTLE_MS) return
    lastPersistRef.current[key] = now
    scalpingApi.saveSL(toBackend(sl)).catch(() => {})
  }, [])

  const setSL = useCallback(
    (sl: SLState) => {
      setSlMap((prev) => ({ ...prev, [slKey(sl.symbol, sl.exchange, sl.product)]: sl }))
      persist(sl, true)
    },
    [persist]
  )

  const clearSL = useCallback((symbol: string, exchange: string, product: string) => {
    const key = slKey(symbol, exchange, product)
    setSlMap((prev) => {
      const next = { ...prev }
      delete next[key]
      return next
    })
    // Drop bookkeeping for this leg so the refs don't grow across a long session.
    delete lastPersistRef.current[key]
    delete lastExitAttemptRef.current[key]
    exitingRef.current.delete(key)
    scalpingApi.deleteSL(symbol, exchange, product).catch(() => {})
  }, [])

  const exitLeg = useCallback(
    async (sl: SLState) => {
      const key = slKey(sl.symbol, sl.exchange, sl.product)
      if (exitingRef.current.has(key)) return
      // Throttle retries so a persistently-failing exit doesn't hammer the broker.
      const now = Date.now()
      if (now - (lastExitAttemptRef.current[key] ?? 0) < EXIT_RETRY_COOLDOWN_MS) return
      lastExitAttemptRef.current[key] = now
      exitingRef.current.add(key)
      try {
        // Size + direction from the CURRENT live position, not the saved quantity.
        const liveQty =
          resolvePositionRef.current?.(sl.symbol, sl.exchange, sl.product) ?? sl.quantity
        if (!liveQty) {
          // Already flat — nothing to close. Clear the now-stale SL silently.
          clearSL(sl.symbol, sl.exchange, sl.product)
          return
        }
        const action: ScalpingAction = liveQty > 0 ? 'SELL' : 'BUY'
        const qty = Math.abs(liveQty)
        // Risk-reducing exit endpoint — bypasses the entry lot cap and freeze-splits,
        // so a position scaled beyond 20 lots can always be flattened.
        const res = await scalpingApi.closeLeg({
          symbol: sl.symbol,
          exchange: sl.exchange,
          action,
          quantity: qty,
          product: sl.product,
        })
        if (res.status === 'success') {
          showToast.success(`SL hit — exited ${sl.symbol} (${action} ${qty})`, 'orders')
          clearSL(sl.symbol, sl.exchange, sl.product) // clear ONLY on a confirmed exit
        } else {
          // Keep the SL active so the next tick retries — the position is still open.
          showToast.error(
            `SL EXIT FAILED for ${sl.symbol} — position still OPEN & unprotected. Retrying…`,
            'orders'
          )
        }
      } catch (e) {
        showToast.error(
          `SL exit error for ${sl.symbol} — position still OPEN. Retrying… (${(e as Error).message})`,
          'orders'
        )
      } finally {
        exitingRef.current.delete(key)
        onAfterExitRef.current?.()
      }
    },
    [clearSL]
  )

  // Re-run evaluation whenever any active SL's LTP changes.
  const tickSignal = slSymbols
    .map(
      (s) =>
        `${s.exchange}:${s.symbol}:${slMarketData.get(`${s.exchange}:${s.symbol}`)?.data?.ltp ?? ''}`
    )
    .join('|')

  useEffect(() => {
    let changed = false
    const updates: Record<string, SLState> = {}
    const breaches: SLState[] = []

    for (const sl of Object.values(slMapRef.current)) {
      if (!sl.active) continue
      const ltp = slMarketDataRef.current.get(`${sl.exchange}:${sl.symbol}`)?.data?.ltp
      if (ltp == null) continue
      const key = slKey(sl.symbol, sl.exchange, sl.product)
      const { next, breached } = evaluateTrail(sl, ltp)
      if (breached) {
        breaches.push({ ...next, active: false })
      } else if (
        next.currentSl !== sl.currentSl ||
        next.highestPrice !== sl.highestPrice ||
        next.lowestPrice !== sl.lowestPrice
      ) {
        updates[key] = next
        changed = true
      }
    }

    if (changed) {
      setSlMap((prev) => {
        const merged = { ...prev }
        for (const [k, v] of Object.entries(updates)) {
          if (merged[k]?.active) merged[k] = v
        }
        return merged
      })
      for (const v of Object.values(updates)) persist(v)
    }
    for (const b of breaches) exitLeg(b)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tickSignal])

  return { slMap, setSL, clearSL }
}
