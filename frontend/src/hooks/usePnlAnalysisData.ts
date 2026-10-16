// frontend/src/hooks/usePnlAnalysisData.ts
/**
 * The one fetch behind the P&L page (fork-only): closed lots and open positions
 * for every segment, plus the daily realized / unrealized curve for Equity.
 * It runs when Fetch is clicked, and again (debounced) when the symbol filter
 * changes, because the equity curve narrows by symbol on the server.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { type PnlHistoryClosedTrade, type PnlHistoryOpenPosition, tradingApi } from '@/api/trading'
import type { PnlEmbeddedFilters } from '@/hooks/usePnlFilters'
import type { CurveData } from '@/lib/pnlCurve'
import { useAuthStore } from '@/stores/authStore'
import { showToast } from '@/utils/toast'

export interface PnlData {
  closedTrades: PnlHistoryClosedTrade[]
  openPositions: PnlHistoryOpenPosition[]
  unrealizedAvailable: boolean
  curve: CurveData | null
  /** The segment this data was fetched for. */
  segment: string
  startDate: string
  endDate: string
}

const EMPTY: PnlData = {
  closedTrades: [],
  openPositions: [],
  unrealizedAvailable: false,
  curve: null,
  segment: '',
  startDate: '',
  endDate: '',
}

// One toast after a fetch instead of a list that stays on the page.
function notifyCurveNotes(notes: CurveData['notes']) {
  const brief = (names: string[]) =>
    names.length > 4
      ? `${names.slice(0, 4).join(', ')} +${names.length - 4} more`
      : names.join(', ')
  const parts: string[] = []
  const orphanSymbols = Array.from(new Set(notes.orphan_sells.map((o) => o.symbol)))
  if (orphanSymbols.length > 0) {
    parts.push(
      `${orphanSymbols.length} symbols had a sell with no earlier buy in the ledger and were left out (${brief(orphanSymbols)})`
    )
  }
  if (notes.missing_close.length > 0) {
    parts.push(`no daily price for ${brief(notes.missing_close)}, held at cost`)
  }
  if (notes.calendar) parts.push(`trading days: ${notes.calendar}`)
  if (parts.length > 0) showToast.warning(parts.join('; '), 'system')
}

export function usePnlAnalysisData(embedded: PnlEmbeddedFilters | null) {
  const { apiKey } = useAuthStore()
  const [data, setData] = useState<PnlData>(EMPTY)
  const [isLoading, setIsLoading] = useState(false)
  const [hasFetched, setHasFetched] = useState(false)
  const seq = useRef(0)

  const embeddedRef = useRef(embedded)
  embeddedRef.current = embedded

  const load = useCallback(
    async (quiet = false) => {
      const e = embeddedRef.current
      if (!e) return
      if (!apiKey) {
        showToast.error('API key not available', 'system')
        return
      }
      const mySeq = ++seq.current
      setIsLoading(true)
      try {
        const symbol = e.tableFilters.symbol.trim() || undefined
        const [history, curve] = await Promise.all([
          tradingApi.getPnlHistory(apiKey, e.startDate, e.endDate, {
            segment: e.segment === 'all' ? undefined : e.segment,
          }),
          e.segment === 'equity'
            ? tradingApi.getPnlCurve(apiKey, e.startDate, e.endDate, 'actual_cost', symbol)
            : Promise.resolve(null),
        ])
        if (mySeq !== seq.current) return
        if (history.status !== 'success' || !history.data) {
          showToast.error(history.message || 'Failed to load P&L history', 'system')
          return
        }
        let curveData: CurveData | null = null
        if (curve) {
          if (curve.status === 'success' && curve.data) {
            curveData = curve.data
            if (!quiet) notifyCurveNotes(curve.data.notes)
          } else {
            showToast.error(curve.message || 'Failed to load the P&L curve', 'system')
          }
        }
        setData({
          closedTrades: history.data.closed_trades,
          openPositions: history.data.open_positions,
          unrealizedAvailable: history.data.total_unrealized_pnl != null,
          curve: curveData,
          segment: e.segment,
          startDate: e.startDate,
          endDate: e.endDate,
        })
        setHasFetched(true)
      } catch {
        if (mySeq === seq.current) showToast.error('Failed to load P&L', 'system')
      } finally {
        if (mySeq === seq.current) setIsLoading(false)
      }
    },
    [apiKey]
  )

  // Fetch when the shared Fetch is clicked.
  const fetchToken = embedded?.fetchToken ?? 0
  // biome-ignore lint/correctness/useExhaustiveDependencies: only the counter triggers a fetch
  useEffect(() => {
    if (fetchToken > 0) load()
  }, [fetchToken])

  // The equity curve takes the symbol on the server: re-fetch, quietly, when it changes.
  const symbolNeedle = embedded?.tableFilters.symbol.trim() ?? ''
  const isEquity = embedded?.segment === 'equity'
  // biome-ignore lint/correctness/useExhaustiveDependencies: only a symbol change should re-fetch
  useEffect(() => {
    if (!isEquity || fetchToken === 0) return
    const timer = window.setTimeout(() => load(true), 400)
    return () => window.clearTimeout(timer)
  }, [symbolNeedle])

  return { data, isLoading, hasFetched }
}
