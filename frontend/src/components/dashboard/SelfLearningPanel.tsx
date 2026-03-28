import { useState } from 'react'
import { Brain, TrendingUp, TrendingDown, ChevronDown, ChevronUp, Loader2 } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useDashboardStore } from '@/stores/dashboardStore'
import { useSelfLearning } from '@/api/dashboardApi'

// ---------------------------------------------------------------------------
// SelfLearningPanel -- Execution: single sentence summary.
// Research: full details with weight changes, lessons, pattern matches.
// ---------------------------------------------------------------------------

export function SelfLearningPanel() {
  const mode = useDashboardStore((s) => s.mode)
  const symbol = useDashboardStore((s) => s.selectedSymbol)
  const { data: learningData, isLoading } = useSelfLearning(symbol)
  const [expanded, setExpanded] = useState(false)

  if (isLoading || !learningData) {
    return (
      <div className="flex h-full items-center justify-center rounded-lg border border-slate-800/50 bg-slate-900/80">
        <Loader2 size={20} className="animate-spin text-slate-500" />
      </div>
    )
  }

  const metrics = learningData.metrics ?? []
  const accuracy = metrics.find((m) => m.metricId === 'accuracy')
  const winRate = metrics.find((m) => m.metricId === 'win_rate')

  // No weight changes or patterns from the basic API fallback
  const weightChanges: Array<{ agent: string; oldWeight: number; newWeight: number }> = []
  const lessons: Array<{ id: string; text: string; timestamp: number }> = []
  const patternMatches: Array<{ symbol: string; date: string; similarity: number }> = []

  // Build the single-line summary
  const topBoost = weightChanges.length > 0
    ? weightChanges.reduce((best, wc) => {
        const delta = ((wc.newWeight - wc.oldWeight) / wc.oldWeight) * 100
        return delta > best.delta ? { agent: wc.agent, delta } : best
      }, { agent: '', delta: -Infinity })
    : { agent: 'N/A', delta: 0 }

  const topMatch = patternMatches[0]

  // Execution compact: one sentence
  if (mode === 'execution' && !expanded) {
    return (
      <div className="flex h-full flex-col rounded-lg border border-slate-800/50 bg-slate-900/80 backdrop-blur-sm overflow-hidden">
        <div className="flex items-center justify-between px-3 py-2 border-b border-slate-800/50">
          <div className="flex items-center gap-2">
            <Brain size={12} className="text-slate-400" />
            <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">AI Learning</span>
          </div>
          <span className="rounded-full bg-emerald-950/30 border border-emerald-800/30 px-2 py-0.5 text-[10px] text-emerald-400 font-bold">
            {accuracy?.trend === 'improving' ? 'IMPROVING' : accuracy?.trend === 'declining' ? 'DECLINING' : 'STABLE'}
          </span>
        </div>

        <div className="flex-1 min-h-0 p-3 space-y-2">
          {/* Single sentence summary */}
          <p className="text-xs text-slate-300 leading-relaxed">
            Today: <span className="font-bold text-emerald-400">{accuracy?.value ?? 0}% accurate</span>
            {' | '}
            <span className="text-slate-200">{topBoost.agent}</span> boosted
            <span className="font-bold text-emerald-400"> +{topBoost.delta.toFixed(0)}%</span>
            {' | '}
            Similar to <span className="text-sky-400">{topMatch?.symbol} {topMatch?.date}</span> rally
          </p>

          {/* Quick metrics row */}
          <div className="flex items-center gap-3 text-[10px]">
            <div>
              <span className="text-slate-500">Accuracy </span>
              <span className="font-bold text-emerald-400">{accuracy?.value}%</span>
            </div>
            <div>
              <span className="text-slate-500">Win Rate </span>
              <span className="font-bold text-slate-200">{winRate?.value}%</span>
            </div>
          </div>

          <button
            onClick={() => setExpanded(true)}
            className="flex items-center gap-1 text-[10px] text-sky-400 hover:text-sky-300 transition-colors"
          >
            <ChevronDown size={10} /> Details
          </button>
        </div>
      </div>
    )
  }

  // Research / expanded
  return (
    <div className="flex h-full flex-col rounded-lg border border-slate-800/50 bg-slate-900/80 backdrop-blur-sm overflow-hidden">
      <div className="flex items-center justify-between px-3 py-2 border-b border-slate-800/50">
        <div className="flex items-center gap-2">
          <Brain size={12} className="text-slate-400" />
          <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">Self-Learning AI</span>
        </div>
        <span className="rounded-full bg-emerald-950/30 border border-emerald-800/30 px-2 py-0.5 text-[10px] text-emerald-400 font-bold">
          STABLE
        </span>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto p-3 space-y-2">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-[10px] text-slate-500">Today Accuracy</p>
            <p className="text-2xl font-black text-emerald-400">{accuracy?.value ?? 0}%</p>
          </div>
        </div>

        <div>
          <p className="text-[9px] text-slate-500 mb-1">Live Weight Changes</p>
          <div className="space-y-0.5">
            {weightChanges.map((wc) => {
              const delta = ((wc.newWeight - wc.oldWeight) / wc.oldWeight) * 100
              const isUp = delta > 0
              return (
                <div key={wc.agent} className="flex items-center justify-between text-[10px]">
                  <span className="text-slate-400">{wc.agent}</span>
                  <div className="flex items-center gap-1">
                    <span className="text-slate-500 font-mono">{wc.oldWeight.toFixed(1)}</span>
                    <span className="text-slate-600">{'->'}</span>
                    <span className="text-slate-300 font-mono font-bold">{wc.newWeight.toFixed(1)}</span>
                    <span className={cn('font-bold', isUp ? 'text-emerald-400' : 'text-rose-400')}>
                      {isUp ? '+' : ''}{delta.toFixed(0)}%
                    </span>
                    {isUp ? <TrendingUp size={10} className="text-emerald-400" /> : <TrendingDown size={10} className="text-rose-400" />}
                  </div>
                </div>
              )
            })}
          </div>
        </div>

        <div>
          <p className="text-[9px] text-slate-500 mb-1">Recent Lessons</p>
          {lessons.map((l) => (
            <p key={l.id} className="text-[10px] text-slate-400 leading-tight mb-0.5">
              <span className="text-sky-500">*</span> {l.text}
            </p>
          ))}
        </div>

        <div>
          <p className="text-[9px] text-slate-500 mb-1">Pattern Matches</p>
          {patternMatches.map((pm) => (
            <div key={pm.symbol + pm.date} className="flex items-center justify-between text-[10px]">
              <span className="text-slate-400">{pm.similarity}% similar to {pm.symbol}</span>
              <span className="text-slate-600">{pm.date}</span>
            </div>
          ))}
        </div>

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
