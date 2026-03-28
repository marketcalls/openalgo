import { useState } from 'react'
import { Cpu, Award, ChevronDown, ChevronUp, Loader2 } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useDashboardStore } from '@/stores/dashboardStore'
import { useModelPredictions } from '@/api/dashboardApi'
import type { Signal } from '@/types/dashboard'

// ---------------------------------------------------------------------------
// ModelPredictions -- Compact: "6/7 UP" + best model badge.
// Full table only in Research mode or on expand.
// ---------------------------------------------------------------------------

const signalColor: Record<Signal, string> = {
  BUY: 'text-emerald-400',
  SELL: 'text-rose-400',
  HOLD: 'text-amber-400',
}

export function ModelPredictions() {
  const mode = useDashboardStore((s) => s.mode)
  const symbol = useDashboardStore((s) => s.selectedSymbol)
  const { data, isLoading } = useModelPredictions(symbol)
  const models = data?.predictions ?? []
  const [expanded, setExpanded] = useState(false)

  if (isLoading || models.length === 0) {
    return (
      <div className="flex h-full items-center justify-center rounded-lg border border-slate-800/50 bg-slate-900/80">
        <Loader2 size={20} className="animate-spin text-slate-500" />
      </div>
    )
  }

  const bestIdx = models.reduce((best, m, i) => (m.probability > models[best].probability ? i : best), 0)
  const best = models[bestIdx]
  const agreeCount = models.filter((m) => m.signal === 'BUY').length
  const majorityDir = agreeCount > models.length / 2 ? 'UP' : 'DOWN'

  // Execution compact
  if (mode === 'execution' && !expanded) {
    return (
      <div className="flex h-full flex-col rounded-lg border border-slate-800/50 bg-slate-900/80 backdrop-blur-sm overflow-hidden">
        <div className="flex items-center justify-between px-3 py-2 border-b border-slate-800/50">
          <div className="flex items-center gap-2">
            <Cpu size={12} className="text-slate-400" />
            <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">Models</span>
          </div>
        </div>

        <div className="flex-1 min-h-0 p-3 space-y-3">
          {/* Big agreement score */}
          <div className="flex items-center justify-between">
            <div>
              <p className="text-2xl font-black text-slate-100">
                {agreeCount}/{models.length}
                <span className={cn('ml-2 text-lg', agreeCount > models.length / 2 ? 'text-emerald-400' : 'text-rose-400')}>
                  {majorityDir}
                </span>
              </p>
              <p className="text-[10px] text-slate-500">models agree on direction</p>
            </div>
            {/* Best model badge */}
            <div className="flex items-center gap-1 rounded-full bg-amber-950/40 border border-amber-700/30 px-2.5 py-1">
              <Award size={12} className="text-amber-400" />
              <div className="text-[10px]">
                <p className="font-bold text-amber-300">{best.modelName}</p>
                <p className="text-amber-400/70">{(best.probability * 100).toFixed(0)}% prob</p>
              </div>
            </div>
          </div>

          {/* Dissenting models */}
          {models.filter((m) => m.signal !== 'BUY').length > 0 && (
            <div className="rounded bg-slate-800/50 px-2 py-1.5">
              <p className="text-[9px] text-slate-500 uppercase tracking-wider mb-1">Disagree</p>
              {models.filter((m) => m.signal !== 'BUY').map((m) => (
                <div key={m.modelId} className="flex items-center justify-between text-[10px]">
                  <span className="text-slate-400">{m.modelName}</span>
                  <span className={cn('font-bold', signalColor[m.signal])}>
                    {m.signal} {(m.probability * 100).toFixed(0)}%
                  </span>
                </div>
              ))}
            </div>
          )}

          <button
            onClick={() => setExpanded(true)}
            className="flex items-center gap-1 text-[10px] text-sky-400 hover:text-sky-300 transition-colors"
          >
            <ChevronDown size={10} /> Full table
          </button>
        </div>
      </div>
    )
  }

  // Research / expanded: full table
  return (
    <div className="flex h-full flex-col rounded-lg border border-slate-800/50 bg-slate-900/80 backdrop-blur-sm overflow-hidden">
      <div className="flex items-center justify-between px-3 py-2 border-b border-slate-800/50">
        <div className="flex items-center gap-2">
          <Cpu size={12} className="text-slate-400" />
          <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">Model Predictions</span>
        </div>
        <span className="text-xs font-bold text-slate-200">{agreeCount}/{models.length} {majorityDir}</span>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto p-3 space-y-2">
        <table className="w-full text-[10px]">
          <thead>
            <tr className="text-slate-500 border-b border-slate-800">
              <th className="py-1 text-left font-medium">Model</th>
              <th className="py-1 text-center font-medium">Dir</th>
              <th className="py-1 text-center font-medium">Prob</th>
              <th className="py-1 text-center font-medium">Horizon</th>
            </tr>
          </thead>
          <tbody>
            {models.map((m, i) => (
              <tr
                key={m.modelId}
                className={cn(
                  'border-b border-slate-800/50',
                  m.signal === 'BUY' ? 'bg-emerald-950/10' : m.signal === 'SELL' ? 'bg-rose-950/10' : '',
                )}
              >
                <td className="py-1 font-medium text-slate-300">
                  <div className="flex items-center gap-1">
                    {i === bestIdx && <Award size={10} className="text-amber-400" />}
                    {m.modelName}
                  </div>
                </td>
                <td className={cn('py-1 text-center font-bold', signalColor[m.signal])}>{m.signal}</td>
                <td className="py-1 text-center font-mono text-slate-300">{(m.probability * 100).toFixed(0)}%</td>
                <td className="py-1 text-center text-slate-500">{m.horizonMinutes}m</td>
              </tr>
            ))}
          </tbody>
        </table>

        {mode === 'execution' && expanded && (
          <button
            onClick={() => setExpanded(false)}
            className="flex items-center gap-1 text-[10px] text-sky-400 hover:text-sky-300 transition-colors"
          >
            <ChevronUp size={10} /> Compact view
          </button>
        )}
      </div>
    </div>
  )
}
