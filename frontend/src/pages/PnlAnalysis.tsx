// frontend/src/pages/PnlAnalysis.tsx
/**
 * P&L Analysis (fork-only, SKYSHIELD_PATCHES.md): one page for the P&L report
 * and the P&L curve. One fetch, one set of filters, one model: the summary,
 * strategies, curve, calendar and the Day / Week / Month / Scrip views are all
 * computed from the same data, so they cannot disagree. The old /pnl-history
 * and /pnl-curve pages stay available side by side until this one is trusted.
 */
import { Loader2, X } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { PnlBreakdown } from '@/components/pnl/PnlBreakdown'
import { PnlCalendarPanel } from '@/components/pnl/PnlCalendarPanel'
import { PnlCurvePanel } from '@/components/pnl/PnlCurvePanel'
import { PnlStrategiesPanel } from '@/components/pnl/PnlStrategiesPanel'
import { PnlSummary } from '@/components/pnl/PnlSummary'
import { PnlFilterBar } from '@/components/reports/PnlFilterBar'
import { PnlTableFiltersDialog } from '@/components/reports/PnlTableFiltersDialog'
import { usePnlAnalysisData } from '@/hooks/usePnlAnalysisData'
import { type PnlTableFilters, usePnlFilters } from '@/hooks/usePnlFilters'
import { buildPnlModel, NO_STRATEGY } from '@/lib/pnlModel'
import { MAX_STRATEGY_SERIES } from '@/lib/pnlPalette'
import { makeFormatCurrency } from '@/lib/utils'
import { useAuthStore } from '@/stores/authStore'
import { useThemeStore } from '@/stores/themeStore'

interface Tag {
  key: string
  label: string
  remove: (f: PnlTableFilters) => PnlTableFilters
}

function appliedTags(f: PnlTableFilters): Tag[] {
  const tags: Tag[] = []
  if (f.symbol.trim()) {
    tags.push({
      key: 'symbol',
      label: `Symbol: ${f.symbol.trim()}`,
      remove: (x) => ({ ...x, symbol: '' }),
    })
  }
  for (const s of f.strategies) {
    tags.push({
      key: `s:${s}`,
      label: s === NO_STRATEGY ? 'No strategy' : s,
      remove: (x) => ({ ...x, strategies: x.strategies.filter((v) => v !== s) }),
    })
  }
  for (const e of f.exchanges) {
    tags.push({
      key: `e:${e}`,
      label: e,
      remove: (x) => ({ ...x, exchanges: x.exchanges.filter((v) => v !== e) }),
    })
  }
  for (const p of f.products) {
    tags.push({
      key: `p:${p}`,
      label: p,
      remove: (x) => ({ ...x, products: x.products.filter((v) => v !== p) }),
    })
  }
  return tags
}

export default function PnlAnalysis() {
  const filters = usePnlFilters()
  const { mode } = useThemeStore()
  const isDark = mode === 'dark'
  const { user } = useAuthStore()
  const formatCurrency = useMemo(() => makeFormatCurrency(user?.broker), [user?.broker])

  const { data, isLoading, hasFetched } = usePnlAnalysisData(filters.embedded)
  const pnlType = filters.embedded?.pnlType ?? 'combined'

  const model = useMemo(
    () =>
      buildPnlModel({
        closedTrades: data.closedTrades,
        openPositions: data.openPositions,
        unrealizedAvailable: data.unrealizedAvailable,
        curve: data.curve,
        segment: data.segment,
        pnlType,
        filters: filters.tableFilters,
        maxStrategies: MAX_STRATEGY_SERIES,
      }),
    [data, pnlType, filters.tableFilters]
  )

  // Alt+R puts the plot scale back to the whole range. It leaves the filters and
  // the line toggles alone.
  const [resetSignal, setResetSignal] = useState(0)
  const resetAll = useCallback(() => {
    setResetSignal((n) => n + 1)
  }, [])
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.altKey && !event.ctrlKey && !event.metaKey && event.key.toLowerCase() === 'r') {
        event.preventDefault()
        resetAll()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [resetAll])

  const tags = appliedTags(filters.tableFilters)
  const title =
    pnlType === 'realized'
      ? 'Realized P&L (cumulative)'
      : pnlType === 'unrealized'
        ? 'Unrealized P&L'
        : 'Cumulative P&L (realized + unrealized)'

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">P&L Analysis</h1>
        <p className="text-muted-foreground">
          Realized and unrealized profit and loss for a date range, as a summary, a curve and day,
          week, month and scrip breakdowns
        </p>
      </div>

      <PnlFilterBar filters={filters} />

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2 text-sm">
          {tags.length === 0 ? (
            <span className="text-muted-foreground">No filters applied</span>
          ) : (
            <>
              <span className="text-muted-foreground">Applied:</span>
              {tags.map((tag) => (
                <button
                  key={tag.key}
                  type="button"
                  onClick={() => filters.setTableFilters(tag.remove(filters.tableFilters))}
                  className="flex items-center gap-1 rounded-full border px-2.5 py-0.5 hover:bg-muted"
                  aria-label={`Remove filter ${tag.label}`}
                >
                  {tag.label}
                  <X className="h-3 w-3" />
                </button>
              ))}
            </>
          )}
        </div>
        <PnlTableFiltersDialog
          value={filters.tableFilters}
          onChange={filters.setTableFilters}
          options={model.options}
        />
      </div>

      {!filters.ready && (
        <div className="py-16 text-center text-muted-foreground">
          <p className="font-medium">Build a report</p>
          <p className="text-sm">Choose a segment and a P&L type, then click Fetch</p>
        </div>
      )}

      {filters.ready && !hasFetched && !isLoading && (
        <div className="py-16 text-center text-muted-foreground">
          <p className="font-medium">Ready</p>
          <p className="text-sm">Click Fetch to load the P&L</p>
        </div>
      )}

      {isLoading && (
        <div className="flex items-center justify-center py-6">
          <Loader2 className="h-6 w-6 animate-spin" />
        </div>
      )}

      {hasFetched && (
        <>
          {model.curveIgnoresFilters && (
            <p className="text-xs text-amber-600">
              Exchange and product narrow the Scrip view only: for Equity the curve, summary and
              time views treat NSE and BSE as one position.
            </p>
          )}

          <PnlCalendarPanel
            model={model}
            startDate={data.startDate}
            endDate={data.endDate}
            formatCurrency={formatCurrency}
          />

          <PnlSummary model={model} formatCurrency={formatCurrency} pnlType={pnlType} />

          <PnlCurvePanel
            model={model}
            formatCurrency={formatCurrency}
            isDark={isDark}
            title={title}
            startDate={data.startDate}
            endDate={data.endDate}
            resetSignal={resetSignal}
          />

          <PnlStrategiesPanel model={model} formatCurrency={formatCurrency} isDark={isDark} />

          <PnlBreakdown
            model={model}
            pnlType={pnlType}
            isDark={isDark}
            formatCurrency={formatCurrency}
            startDate={data.startDate}
            endDate={data.endDate}
          />
        </>
      )}
    </div>
  )
}
