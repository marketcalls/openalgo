import { useState } from 'react'
import { Users, ChevronDown, ChevronUp, Loader2 } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useDashboardStore } from '@/stores/dashboardStore'
import { useAgentConsensus } from '@/api/dashboardApi'
import type { Signal } from '@/types/dashboard'

// ---------------------------------------------------------------------------
// AgentConsensus -- Compact: weighted bar + top 3 + dissenters only.
// Full 9-agent grid only in Research mode or on expand.
// ---------------------------------------------------------------------------

const signalColor: Record<Signal, string> = {
  BUY: 'text-emerald-400',
  SELL: 'text-rose-400',
  HOLD: 'text-amber-400',
}
const borderColor: Record<Signal, string> = {
  BUY: 'border-emerald-600/40',
  SELL: 'border-rose-600/40',
  HOLD: 'border-amber-600/40',
}

export function AgentConsensus() {
  const mode = useDashboardStore((s) => s.mode)
  const symbol = useDashboardStore((s) => s.selectedSymbol)
  const { data, isLoading } = useAgentConsensus(symbol)
  const agents = data?.votes ?? []
  const [expanded, setExpanded] = useState(false)

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center rounded-lg border border-slate-800/50 bg-slate-900/80">
        <Loader2 size={20} className="animate-spin text-slate-500" />
      </div>
    )
  }

  const buyCount = agents.filter((a) => a.signal === 'BUY').length
  const sellCount = agents.filter((a) => a.signal === 'SELL').length
  const holdCount = agents.filter((a) => a.signal === 'HOLD').length
  const total = agents.length

  // Weighted confidence
  const totalConf = agents.reduce((s, a) => s + a.confidence, 0)
  const buyConf = agents.filter((a) => a.signal === 'BUY').reduce((s, a) => s + a.confidence, 0)
  const weightedBuyPct = totalConf > 0 ? Math.round((buyConf / totalConf) * 100) : 0

  // Sort by confidence for top 3
  const sorted = [...agents].sort((a, b) => b.confidence - a.confidence)
  const top3 = sorted.slice(0, 3)

  // Find dissenters (agents NOT matching majority)
  const majority = buyCount >= sellCount && buyCount >= holdCount ? 'BUY' : sellCount > holdCount ? 'SELL' : 'HOLD'
  const dissenters = agents.filter((a) => a.signal !== majority)

  // Execution mode: compact
  if (mode === 'execution' && !expanded) {
    return (
      <div className="flex h-full flex-col rounded-lg border border-slate-800/50 bg-slate-900/80 backdrop-blur-sm overflow-hidden">
        <div className="flex items-center justify-between px-3 py-2 border-b border-slate-800/50">
          <div className="flex items-center gap-2">
            <Users size={12} className="text-slate-400" />
            <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">Agents</span>
          </div>
          <span className="text-xs font-bold text-slate-200">{buyCount}/{total} BUY</span>
        </div>

        <div className="flex-1 min-h-0 p-3 space-y-2">
          {/* Weighted consensus bar */}
          <div>
            <div className="flex items-center justify-between text-[10px] mb-1">
              <span className="text-emerald-400 font-bold">BUY {weightedBuyPct}%</span>
              <span className="text-slate-500">(weighted)</span>
            </div>
            <div className="flex h-2.5 w-full overflow-hidden rounded-full bg-slate-800">
              <div className="bg-emerald-500 transition-all duration-500" style={{ width: `${weightedBuyPct}%` }} />
              <div className="bg-amber-500 transition-all duration-500" style={{ width: `${Math.round((holdCount / total) * 100)}%` }} />
              <div className="bg-rose-500 transition-all duration-500" style={{ width: `${Math.round((sellCount / total) * 100)}%` }} />
            </div>
          </div>

          {/* Top 3 strongest */}
          <div className="space-y-1">
            {top3.map((a) => (
              <div key={a.agentId} className="flex items-center justify-between text-[10px]">
                <span className="text-slate-300 font-medium">{a.agentName}</span>
                <div className="flex items-center gap-2">
                  <span className={cn('font-bold', signalColor[a.signal])}>{a.signal}</span>
                  <span className="text-slate-400 tabular-nums">{a.confidence}%</span>
                </div>
              </div>
            ))}
          </div>

          {/* Dissenters */}
          {dissenters.length > 0 && (
            <div className="rounded bg-amber-950/20 border border-amber-800/20 px-2 py-1.5">
              <p className="text-[9px] text-amber-400/70 font-semibold uppercase tracking-wider mb-1">Disagree</p>
              {dissenters.map((a) => (
                <div key={a.agentId} className="flex items-center justify-between text-[10px]">
                  <span className="text-slate-400">{a.agentName}</span>
                  <span className={cn('font-bold', signalColor[a.signal])}>{a.signal} {a.confidence}%</span>
                </div>
              ))}
            </div>
          )}

          <button
            onClick={() => setExpanded(true)}
            className="flex items-center gap-1 text-[10px] text-sky-400 hover:text-sky-300 transition-colors"
          >
            <ChevronDown size={10} /> All {total} agents
          </button>
        </div>
      </div>
    )
  }

  // Research mode or expanded: full grid
  return (
    <div className="flex h-full flex-col rounded-lg border border-slate-800/50 bg-slate-900/80 backdrop-blur-sm overflow-hidden">
      <div className="flex items-center justify-between px-3 py-2 border-b border-slate-800/50">
        <div className="flex items-center gap-2">
          <Users size={12} className="text-slate-400" />
          <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">Agent Consensus</span>
        </div>
        <span className="text-xs font-bold text-slate-200">{buyCount}/{total} BUY</span>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto p-3 space-y-2">
        {/* Bar */}
        <div className="flex h-2.5 w-full overflow-hidden rounded-full bg-slate-800">
          <div className="bg-emerald-500 transition-all" style={{ width: `${Math.round((buyCount / total) * 100)}%` }} />
          <div className="bg-amber-500 transition-all" style={{ width: `${Math.round((holdCount / total) * 100)}%` }} />
          <div className="bg-rose-500 transition-all" style={{ width: `${Math.round((sellCount / total) * 100)}%` }} />
        </div>
        <div className="flex justify-between text-[10px] text-slate-500">
          <span className="text-emerald-400">{buyCount} BUY ({Math.round((buyCount / total) * 100)}%)</span>
          <span className="text-amber-400">{holdCount} HOLD</span>
          <span className="text-rose-400">{sellCount} SELL</span>
        </div>

        {/* Full agent grid */}
        <div className="grid grid-cols-3 gap-1.5">
          {agents.map((a) => (
            <div
              key={a.agentId}
              className={cn(
                'rounded border bg-slate-900/50 p-1.5 text-center',
                borderColor[a.signal],
              )}
            >
              <p className="text-[10px] font-bold text-slate-300 truncate">{a.agentName}</p>
              <p className={cn('text-[10px] font-bold', signalColor[a.signal])}>{a.signal}</p>
              <p className="text-[10px] font-mono text-slate-400">{a.confidence}%</p>
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
