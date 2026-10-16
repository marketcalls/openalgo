// frontend/src/components/pnl/PnlScripBars.tsx
/**
 * Horizontal bars per symbol (fork-only): biggest winners at the top, biggest
 * losers at the bottom, realized as a solid bar and the open unrealized as a
 * lighter bar next to it. Plain HTML, no chart library: symbols are not a
 * time axis.
 */
import { useMemo, useState } from 'react'
import { Button } from '@/components/ui/button'
import { negative, positive } from '@/lib/pnlPalette'
import { ChartWatermark } from './ChartWatermark'

export interface ScripBar {
  symbol: string
  realized: number
  unrealized: number | null
}

interface Props {
  rows: ScripBar[]
  isDark: boolean
  formatCurrency: (value: number) => string
  showRealized: boolean
  showUnrealized: boolean
}

const LIMIT = 30

export function PnlScripBars({
  rows,
  isDark,
  formatCurrency,
  showRealized,
  showUnrealized,
}: Props) {
  const [all, setAll] = useState(false)
  const items = useMemo(() => {
    const value = (r: ScripBar) =>
      (showRealized ? r.realized : 0) + (showUnrealized ? (r.unrealized ?? 0) : 0)
    const sorted = [...rows]
      .map((r) => ({ ...r, total: value(r) }))
      .filter((r) => r.total !== 0)
      .sort((a, b) => b.total - a.total)
    if (all || sorted.length <= LIMIT) return sorted
    const half = LIMIT / 2
    return [...sorted.slice(0, half), ...sorted.slice(-half)]
  }, [rows, showRealized, showUnrealized, all])

  const maxAbs = Math.max(1, ...items.map((r) => Math.abs(r.total)))
  const up = positive(isDark)
  const down = negative(isDark)

  if (items.length === 0) {
    return <p className="py-10 text-center text-muted-foreground">Nothing to plot</p>
  }

  return (
    <div className="relative space-y-1">
      <ChartWatermark isDark={isDark} />
      {items.map((r) => {
        const width = `${(Math.abs(r.total) / maxAbs) * 50}%`
        const positiveBar = r.total >= 0
        return (
          <div key={r.symbol} className="relative z-[1] flex items-center gap-3 text-sm">
            <span className="w-28 shrink-0 truncate">{r.symbol}</span>
            <div className="relative h-5 flex-1">
              <div className="absolute inset-y-0 left-1/2 w-px bg-border" />
              <div
                className="absolute inset-y-0 rounded-sm"
                style={{
                  width,
                  backgroundColor: positiveBar ? up : down,
                  left: positiveBar ? '50%' : undefined,
                  right: positiveBar ? undefined : '50%',
                }}
              />
            </div>
            <span
              className={`w-28 shrink-0 text-right font-mono text-xs ${positiveBar ? 'text-green-600' : 'text-red-600'}`}
            >
              {formatCurrency(r.total)}
            </span>
          </div>
        )
      })}
      {rows.length > LIMIT && (
        <div className="pt-2 text-center">
          <Button size="sm" variant="outline" onClick={() => setAll((a) => !a)}>
            {all
              ? 'Show top and bottom only'
              : `Show all ${items.length === LIMIT ? 'symbols' : ''}`}
          </Button>
        </div>
      )}
    </div>
  )
}
