import { Building2, Loader2 } from 'lucide-react'
import { Gauge } from './shared/Gauge'
import { cn } from '@/lib/utils'
import { useDashboardStore } from '@/stores/dashboardStore'
import { useInstitutionalScore } from '@/api/dashboardApi'
import type { Signal } from '@/types/dashboard'

// ---------------------------------------------------------------------------
// InstitutionalScore -- Execution: compact gauge with score + trend badges.
// Research: full component breakdown.
// ---------------------------------------------------------------------------

const signalDot: Record<Signal, string> = {
  BUY: 'bg-emerald-400',
  SELL: 'bg-rose-400',
  HOLD: 'bg-amber-400',
}

export function InstitutionalScore() {
  const mode = useDashboardStore((s) => s.mode)
  const symbol = useDashboardStore((s) => s.selectedSymbol)
  const { data: d, isLoading } = useInstitutionalScore(symbol)

  if (isLoading || !d) {
    return (
      <div className="flex h-full items-center justify-center rounded-lg border border-slate-800/50 bg-slate-900/80">
        <Loader2 size={20} className="animate-spin text-slate-500" />
      </div>
    )
  }

  // Execution: compact
  if (mode === 'execution') {
    return (
      <div className="flex h-full flex-col rounded-lg border border-slate-800/50 bg-slate-900/80 backdrop-blur-sm overflow-hidden">
        <div className="flex items-center justify-between px-3 py-2 border-b border-slate-800/50">
          <div className="flex items-center gap-2">
            <Building2 size={12} className="text-slate-400" />
            <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">Inst. Score</span>
          </div>
        </div>

        <div className="flex-1 min-h-0 flex flex-col items-center justify-center p-3 gap-2">
          <div className="relative">
            <Gauge value={d.overallScore} size={80} strokeWidth={6} />
            <div className="absolute inset-0 flex flex-col items-center justify-center">
              <span className="text-xl font-black text-slate-100">{d.overallScore}</span>
              <span className="text-[8px] text-slate-500">/ 100</span>
            </div>
          </div>
          <div className="flex gap-1.5 text-[9px]">
            <span className="rounded bg-emerald-950/50 border border-emerald-800/40 px-1.5 py-0.5 text-emerald-400 font-bold">
              {d.trend.toUpperCase()}
            </span>
          </div>
          {/* Top 3 components only */}
          <div className="w-full space-y-0.5">
            {d.components.slice(0, 3).map((comp) => (
              <div key={comp.name} className="flex items-center gap-1.5 text-[10px]">
                <span className={cn('h-1.5 w-1.5 rounded-full shrink-0', signalDot[comp.signal])} />
                <span className="flex-1 text-slate-400 truncate">{comp.name}</span>
                <span className="font-bold text-slate-300 tabular-nums">{comp.score}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    )
  }

  // Research: full
  return (
    <div className="flex h-full flex-col rounded-lg border border-slate-800/50 bg-slate-900/80 backdrop-blur-sm overflow-hidden">
      <div className="flex items-center justify-between px-3 py-2 border-b border-slate-800/50">
        <div className="flex items-center gap-2">
          <Building2 size={12} className="text-slate-400" />
          <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">Institutional Score</span>
        </div>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto p-3">
        <div className="flex flex-col items-center gap-3">
          <div className="relative">
            <Gauge value={d.overallScore} size={90} strokeWidth={7} />
            <div className="absolute inset-0 flex flex-col items-center justify-center">
              <span className="text-xl font-black text-slate-100">{d.overallScore}</span>
              <span className="text-[9px] text-slate-500">/ 100</span>
            </div>
          </div>
          <div className="flex gap-2 text-[10px]">
            <span className="rounded bg-emerald-950/50 border border-emerald-800/40 px-2 py-0.5 text-emerald-400 font-bold">MARKUP</span>
            <span className="rounded bg-sky-950/50 border border-sky-800/40 px-2 py-0.5 text-sky-400 font-bold">ACCUMULATION</span>
          </div>
          <div className="w-full space-y-1.5">
            {d.components.map((comp) => (
              <div key={comp.name} className="flex items-center gap-2">
                <span className={cn('h-1.5 w-1.5 rounded-full', signalDot[comp.signal])} />
                <span className="w-20 text-[10px] text-slate-400 truncate">{comp.name}</span>
                <div className="flex-1 h-1.5 rounded-full bg-slate-800 overflow-hidden">
                  <div
                    className={cn('h-full rounded-full transition-all duration-500',
                      comp.score >= 70 ? 'bg-emerald-500' : comp.score >= 50 ? 'bg-amber-500' : 'bg-rose-500')}
                    style={{ width: `${comp.score}%` }}
                  />
                </div>
                <span className="w-6 text-right text-[10px] font-bold text-slate-300">{comp.score}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
