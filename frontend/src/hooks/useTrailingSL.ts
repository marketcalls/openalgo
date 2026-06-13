/**
 * useTrailingSL — browser-driven stop-loss / trailing-SL engine for the scalping terminal.
 *
 * Evaluates each tracked leg's SL on every LTP tick:
 *  - trail only RAISES the stop, never lowers it
 *  - trailing does not start until price is >= MIN_TRAIL_PROFIT above entry (1cliq rule)
 *  - on breach, fires a MARKET exit (opposite side) for the position quantity
 *
 * SL config is persisted to the backend (database/scalping_db.py) so it survives reload.
 * Long legs (side BUY) trail with the stop below price; short legs (SELL) mirror it.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { scalpingApi } from '@/api/scalping'
import type {
  ScalpingAction,
  ScalpingProduct,
  ScalpingSLState,
  SelectedLeg,
} from '@/types/scalping'
import { showToast } from '@/utils/toast'

const MIN_TRAIL_PROFIT = 1 // don't trail until >= 1 rupee in profit
const PERSIST_THROTTLE_MS = 2000

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

export function slKey(symbol: string, exchange: string): string {
  return `${exchange}:${symbol}`
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
    lowestPrice: entry,
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
  ticks: Array<{ leg: SelectedLeg | null; ltp: number | undefined }>
  onAfterExit?: () => void
}

export function useTrailingSL({ ticks, onAfterExit }: UseTrailingSLArgs) {
  const [slMap, setSlMap] = useState<Record<string, SLState>>({})
  const slMapRef = useRef(slMap)
  slMapRef.current = slMap
  const lastPersistRef = useRef<Record<string, number>>({})
  const exitingRef = useRef<Set<string>>(new Set())

  // Restore persisted SL config on mount.
  useEffect(() => {
    let cancelled = false
    scalpingApi
      .getSLStates()
      .then((resp) => {
        if (cancelled || resp.status !== 'success') return
        const restored: Record<string, SLState> = {}
        for (const s of resp.data) {
          restored[slKey(s.symbol, s.exchange)] = fromBackend(s)
        }
        setSlMap(restored)
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [])

  const persist = useCallback((sl: SLState, force = false) => {
    const key = slKey(sl.symbol, sl.exchange)
    const now = Date.now()
    if (!force && now - (lastPersistRef.current[key] ?? 0) < PERSIST_THROTTLE_MS) return
    lastPersistRef.current[key] = now
    scalpingApi.saveSL(toBackend(sl)).catch(() => {})
  }, [])

  const setSL = useCallback(
    (sl: SLState) => {
      setSlMap((prev) => ({ ...prev, [slKey(sl.symbol, sl.exchange)]: sl }))
      persist(sl, true)
    },
    [persist]
  )

  const clearSL = useCallback((symbol: string, exchange: string, product: string) => {
    const key = slKey(symbol, exchange)
    setSlMap((prev) => {
      const next = { ...prev }
      delete next[key]
      return next
    })
    scalpingApi.deleteSL(symbol, exchange, product).catch(() => {})
  }, [])

  const exitLeg = useCallback(
    async (sl: SLState) => {
      const key = slKey(sl.symbol, sl.exchange)
      if (exitingRef.current.has(key)) return
      exitingRef.current.add(key)
      const action: ScalpingAction = sl.side === 'BUY' ? 'SELL' : 'BUY'
      try {
        const res = await scalpingApi.placeOrder({
          symbol: sl.symbol,
          exchange: sl.exchange,
          action,
          quantity: sl.quantity,
          product: sl.product,
        })
        if (res.status === 'success') {
          showToast.success(`SL hit — exited ${sl.symbol} (${action} ${sl.quantity})`, 'orders')
        } else {
          showToast.error(`SL exit failed for ${sl.symbol}: ${res.message ?? ''}`, 'orders')
        }
      } catch (e) {
        showToast.error(`SL exit error for ${sl.symbol}: ${(e as Error).message}`, 'orders')
      } finally {
        clearSL(sl.symbol, sl.exchange, sl.product)
        exitingRef.current.delete(key)
        onAfterExit?.()
      }
    },
    [clearSL, onAfterExit]
  )

  // Tick signal: re-run evaluation whenever any tracked leg's LTP changes.
  const tickSignal = ticks
    .map((t) => `${t.leg?.exchange}:${t.leg?.symbol}:${t.ltp ?? ''}`)
    .join('|')

  useEffect(() => {
    let changed = false
    const updates: Record<string, SLState> = {}
    const breaches: SLState[] = []

    for (const { leg, ltp } of ticks) {
      if (!leg || ltp == null) continue
      const key = slKey(leg.symbol, leg.exchange)
      const sl = slMapRef.current[key]
      if (!sl || !sl.active) continue

      const { next, breached } = evaluateTrail(sl, ltp)
      if (breached) {
        breaches.push({ ...next, active: false })
      } else if (next.currentSl !== sl.currentSl || next.highestPrice !== sl.highestPrice) {
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
