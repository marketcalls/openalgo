import { Layers, Loader2 } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useDashboardStore } from '@/stores/dashboardStore'
import { useTimeframeMatrix } from '@/api/dashboardApi'
import type { Bias, TimeframeCell } from '@/types/dashboard'

// ---------------------------------------------------------------------------
// TimeframeMatrix -- Plain English labels with direction icons.
// Instead of just "HH/HL", says "Trend intact" or "Pullback" or "Reversal risk".
// ---------------------------------------------------------------------------

const biasIcon: Record<Bias, string> = {
  bullish: '\u2197',  // ↗
  bearish: '\u2198',  // ↘
  neutral: '\u2192',  // →
}

const biasColor: Record<Bias, string> = {
  bullish: 'text-emerald-400',
  bearish: 'text-rose-400',
  neutral: 'text-amber-400',
}

const rowBg: Record<Bias, string> = {
  bullish: 'bg-emerald-950/15',
  bearish: 'bg-rose-950/15',
  neutral: 'bg-slate-900/30',
}

function getPlainEnglish(cell: TimeframeCell): { label: string; color: string } {
  if (cell.bias === 'bullish' && cell.strength >= 75) {
    return { label: 'Trend intact', color: 'text-emerald-400' }
  }
  if (cell.bias === 'bullish' && cell.strength >= 50) {
    return { label: 'Trending up', color: 'text-emerald-400/80' }
  }
  if (cell.bias === 'bearish' && cell.strength >= 75) {
    return { label: 'Reversal risk', color: 'text-rose-400' }
  }
  if (cell.bias === 'bearish' && cell.strength >= 50) {
    return { label: 'Weak / Falling', color: 'text-rose-400/80' }
  }
  if (cell.bias === 'neutral' && cell.strength >= 50) {
    return { label: 'Range / Pullback', color: 'text-amber-400' }
  }
  return { label: 'Indecisive', color: 'text-slate-400' }
}

export function TimeframeMatrix() {
  const mode = useDashboardStore((s) => s.mode)
  const symbol = useDashboardStore((s) => s.selectedSymbol)
  const { data, isLoading } = useTimeframeMatrix(symbol)
  const cells = data?.cells ?? []

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center rounded-lg border border-slate-800/50 bg-slate-900/80">
        <Loader2 size={20} className="animate-spin text-slate-500" />
      </div>
    )
  }

  const allBullish = cells.length > 0 && cells.every((c) => c.bias === 'bullish')
  const allBearish = cells.length > 0 && cells.every((c) => c.bias === 'bearish')

  return (
    <div className="flex h-full flex-col rounded-lg border border-slate-800/50 bg-slate-900/80 backdrop-blur-sm overflow-hidden">
      <div className="flex items-center justify-between px-3 py-2 border-b border-slate-800/50">
        <div className="flex items-center gap-2">
          <Layers size={12} className="text-slate-400" />
          <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">Timeframes</span>
        </div>
        {allBullish && (
          <span className="rounded bg-emerald-950/40 border border-emerald-800/40 px-1.5 py-0.5 text-[9px] font-bold text-emerald-400">
            ALL ALIGNED
          </span>
        )}
        {allBearish && (
          <span className="rounded bg-rose-950/40 border border-rose-800/40 px-1.5 py-0.5 text-[9px] font-bold text-rose-400">
            ALL BEARISH
          </span>
        )}
      </div>

      <div className="flex-1 min-h-0 overflow-auto p-2">
        <div className="space-y-1">
          {cells.map((c) => {
            const english = getPlainEnglish(c)
            return (
              <div
                key={c.timeframe}
                className={cn('flex items-center gap-2 rounded-lg px-3 py-1.5', rowBg[c.bias])}
              >
                {/* Timeframe label */}
                <span className="w-8 text-xs font-bold text-slate-300">{c.timeframe}</span>

                {/* Direction icon */}
                <span className={cn('text-base font-bold', biasColor[c.bias])}>
                  {biasIcon[c.bias]}
                </span>

                {/* Plain English */}
                <span className={cn('flex-1 text-xs font-medium', english.color)}>
                  {english.label}
                </span>

                {/* Strength bar (compact) */}
                <div className="w-10 h-1.5 rounded-full bg-slate-800 overflow-hidden">
                  <div
                    className={cn('h-full rounded-full', biasColor[c.bias].replace('text-', 'bg-'))}
                    style={{ width: `${c.strength}%` }}
                  />
                </div>

                {/* Research mode: show structure + ADX */}
                {mode === 'research' && (
                  <>
                    <span className="text-[10px] text-slate-500 w-10 text-center">
                      {c.bias === 'bullish' ? 'HH/HL' : c.bias === 'bearish' ? 'LH/LL' : 'RANGE'}
                    </span>
                    <span className="text-[10px] font-mono text-slate-400 w-6 text-right">{c.trendAngle}</span>
                  </>
                )}
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
