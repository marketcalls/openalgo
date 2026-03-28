import { cn } from '@/lib/utils'
import { useDashboardStore } from '@/stores/dashboardStore'
import {
  useCommandCenter,
  useAgentConsensus,
  useInstitutionalScore,
  useTimeframeMatrix,
  useRiskSnapshot,
} from '@/api/dashboardApi'
import type { Signal } from '@/types/dashboard'

// ---------------------------------------------------------------------------
// MarketRibbon -- Single-line always-visible summary bar.
// A trader glances here and knows: trend, pullback status, agent consensus,
// institutional score, risk state, and current P&L in under 2 seconds.
// ---------------------------------------------------------------------------

const signalArrow: Record<string, string> = {
  bullish: '\u25B2',
  bearish: '\u25BC',
  neutral: '\u25C6',
}

const signalColor: Record<string, string> = {
  bullish: 'text-emerald-400',
  bearish: 'text-rose-400',
  neutral: 'text-amber-400',
}

const signalBgGlow: Record<Signal, string> = {
  BUY: 'bg-emerald-500/5 border-emerald-500/20',
  SELL: 'bg-rose-500/5 border-rose-500/20',
  HOLD: 'bg-amber-500/5 border-amber-500/20',
}

export function MarketRibbon() {
  const symbol = useDashboardStore((s) => s.selectedSymbol)
  const { data: cmd } = useCommandCenter(symbol)
  const { data: agentData } = useAgentConsensus(symbol)
  const { data: inst } = useInstitutionalScore(symbol)
  const { data: tfData } = useTimeframeMatrix(symbol)
  const { data: riskData } = useRiskSnapshot()

  const tfCells = tfData?.cells ?? []
  const agents = agentData?.votes ?? []
  const riskMetrics = (riskData?.metrics ?? []) as Array<{ label: string; value: number; max: number; unit: string; status: 'safe' | 'warning' | 'danger' }>
  const pnl = (riskData as any)?._todayPnl ?? 0

  // Derive timeframe summary
  const primaryTf = tfCells.find((c) => c.timeframe === '15m')
  const pullbackTf = tfCells.find((c) => c.timeframe === '5m')
  const primaryBias = primaryTf?.bias ?? 'neutral'
  const pullbackBias = pullbackTf?.bias ?? 'neutral'

  // Agent count
  const buyCount = agents.filter((a) => a.signal === 'BUY').length
  const totalAgents = agents.length || 1

  // Risk status
  const worstRisk = riskMetrics.reduce((worst, m) => {
    if (m.status === 'danger') return 'danger'
    if (m.status === 'warning' && worst !== 'danger') return 'warning'
    return worst
  }, 'safe' as 'safe' | 'warning' | 'danger')

  const riskLabel =
    worstRisk === 'safe' ? 'OK' : worstRisk === 'warning' ? 'WARN' : 'DANGER'
  const riskColor =
    worstRisk === 'safe'
      ? 'text-emerald-400'
      : worstRisk === 'warning'
        ? 'text-amber-400'
        : 'text-rose-400'

  // Pullback label
  const pullbackLabel =
    pullbackBias === primaryBias
      ? 'Aligned'
      : pullbackBias === 'neutral'
        ? 'Pullback'
        : 'Counter-trend'

  const cmdSignal = cmd?.signal ?? 'HOLD'

  return (
    <div
      className={cn(
        'flex items-center gap-4 border-b px-4 py-1.5 text-xs font-medium',
        'backdrop-blur-sm',
        signalBgGlow[cmdSignal],
      )}
    >
      {/* Primary Trend */}
      <div className="flex items-center gap-1.5">
        <span className={cn('text-sm font-black', signalColor[primaryBias])}>
          {signalArrow[primaryBias]}
        </span>
        <span className="text-slate-400">15m</span>
        <span className={cn('font-bold uppercase', signalColor[primaryBias])}>
          {primaryBias}
        </span>
      </div>

      <span className="text-slate-700">|</span>

      {/* Pullback Status */}
      <div className="flex items-center gap-1">
        <span className="text-slate-400">5m</span>
        <span className={cn('font-semibold', signalColor[pullbackBias])}>
          {pullbackLabel}
        </span>
      </div>

      <span className="text-slate-700">|</span>

      {/* Agent Consensus */}
      <div className="flex items-center gap-1">
        <span className="font-bold text-slate-200">
          {buyCount}/{totalAgents}
        </span>
        <span className="text-slate-400">Agents</span>
        <span className="font-bold text-emerald-400">{agentData?.consensusSignal ?? 'HOLD'}</span>
      </div>

      <span className="text-slate-700">|</span>

      {/* Institutional Score */}
      <div className="flex items-center gap-1">
        <span className="text-slate-400">Inst.</span>
        <span className="font-bold text-slate-200">{inst?.overallScore ?? 0}</span>
      </div>

      <span className="text-slate-700">|</span>

      {/* Risk */}
      <div className="flex items-center gap-1">
        <span className="text-slate-400">Risk</span>
        <span className={cn('font-bold', riskColor)}>{riskLabel}</span>
      </div>

      {/* Spacer */}
      <div className="flex-1" />

      {/* Symbol + Price + Change */}
      <div className="flex items-center gap-2">
        <span className="font-black text-slate-100 tracking-wide">
          {cmd?.symbol ?? symbol}
        </span>
        <span className="font-black text-lg tabular-nums text-slate-100">
          {'\u20B9'}
          {(cmd?.entry ?? 0).toLocaleString('en-IN', { minimumFractionDigits: 1 })}
        </span>
        <span
          className={cn(
            'font-bold tabular-nums',
            pnl >= 0 ? 'text-emerald-400' : 'text-rose-400',
          )}
        >
          {pnl >= 0 ? '+' : ''}
          {'\u20B9'}
          {Math.abs(pnl).toLocaleString('en-IN')}
        </span>
      </div>
    </div>
  )
}
