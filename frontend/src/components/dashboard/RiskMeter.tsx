import { ShieldCheck, AlertTriangle, CircleOff, Loader2 } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useDashboardStore } from '@/stores/dashboardStore'
import { useRiskSnapshot } from '@/api/dashboardApi'
import type { RiskMetric } from '@/types/dashboard'

// ---------------------------------------------------------------------------
// RiskMeter -- Execution: compact strip with P&L, Drawdown%, Heat% in one row.
// Research: full positions list + all risk bars.
// ---------------------------------------------------------------------------

const statusColor: Record<RiskMetric['status'], string> = {
  safe: 'bg-emerald-500',
  warning: 'bg-amber-500',
  danger: 'bg-rose-500',
}

const statusText: Record<RiskMetric['status'], string> = {
  safe: 'text-emerald-400',
  warning: 'text-amber-400',
  danger: 'text-rose-400',
}

export function RiskMeter() {
  const mode = useDashboardStore((s) => s.mode)
  const { data: riskData, isLoading } = useRiskSnapshot()

  if (isLoading || !riskData) {
    return (
      <div className="flex h-full items-center justify-center rounded-lg border border-slate-800/50 bg-slate-900/80">
        <Loader2 size={20} className="animate-spin text-slate-500" />
      </div>
    )
  }

  const pnl = (riskData as any)._todayPnl ?? 0
  const positions = (riskData as any)._positions ?? []
  const metrics = riskData.metrics ?? []

  const drawdown = metrics.find((m) => m.label === 'Max Drawdown')
  const heat = metrics.find((m) => m.label === 'Portfolio Heat')
  const leverage = metrics.find((m) => m.label === 'Leverage')

  const worstStatus = metrics.reduce((worst, m) => {
    if (m.status === 'danger') return 'danger'
    if (m.status === 'warning' && worst !== 'danger') return 'warning'
    return worst
  }, 'safe' as RiskMetric['status'])

  const StatusIcon = worstStatus === 'safe' ? ShieldCheck : worstStatus === 'warning' ? AlertTriangle : CircleOff

  // Execution compact
  if (mode === 'execution') {
    return (
      <div className="flex h-full flex-col rounded-lg border border-slate-800/50 bg-slate-900/80 backdrop-blur-sm overflow-hidden">
        <div className="flex items-center justify-between px-3 py-2 border-b border-slate-800/50">
          <div className="flex items-center gap-2">
            <StatusIcon size={12} className={statusText[worstStatus]} />
            <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">Risk</span>
          </div>
          <span className={cn('text-[10px] font-bold', statusText[worstStatus])}>
            {worstStatus.toUpperCase()}
          </span>
        </div>

        <div className="flex-1 min-h-0 p-3 space-y-2">
          {/* P&L big */}
          <div className="flex items-center justify-between">
            <span className="text-[10px] text-slate-500">P&L Today</span>
            <span className={cn('text-lg font-black tabular-nums', pnl >= 0 ? 'text-emerald-400' : 'text-rose-400')}>
              {pnl >= 0 ? '+' : ''}{'\u20B9'}{Math.abs(pnl).toLocaleString('en-IN')}
            </span>
          </div>

          {/* Key metrics row */}
          <div className="grid grid-cols-3 gap-2 text-center">
            <div className="rounded bg-slate-800/50 p-2">
              <p className="text-[9px] text-slate-500">Drawdown</p>
              <p className={cn('text-sm font-bold', drawdown?.status === 'safe' ? 'text-emerald-400' : 'text-amber-400')}>
                {drawdown?.value ?? 0}{drawdown?.unit}
              </p>
            </div>
            <div className="rounded bg-slate-800/50 p-2">
              <p className="text-[9px] text-slate-500">Heat</p>
              <p className={cn('text-sm font-bold', heat?.status === 'safe' ? 'text-emerald-400' : 'text-amber-400')}>
                {heat?.value ?? 0}{heat?.unit}
              </p>
            </div>
            <div className="rounded bg-slate-800/50 p-2">
              <p className="text-[9px] text-slate-500">Leverage</p>
              <p className={cn('text-sm font-bold', leverage?.status === 'safe' ? 'text-emerald-400' : 'text-amber-400')}>
                {leverage?.value ?? 0}{leverage?.unit}
              </p>
            </div>
          </div>

          {/* Positions compact */}
          <div className="space-y-0.5">
            {positions.map((pos) => (
              <div key={pos.symbol} className="flex items-center justify-between text-[10px]">
                <div className="flex items-center gap-1.5">
                  <span className={cn('font-bold', pos.side === 'LONG' ? 'text-emerald-400' : 'text-rose-400')}>
                    {pos.side === 'LONG' ? 'L' : 'S'}
                  </span>
                  <span className="text-slate-300">{pos.symbol}</span>
                </div>
                <span className={cn('font-bold tabular-nums', pos.mtm >= 0 ? 'text-emerald-400' : 'text-rose-400')}>
                  {pos.mtm >= 0 ? '+' : ''}{pos.mtm.toLocaleString()}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    )
  }

  // Research: full detail
  return (
    <div className="flex h-full flex-col rounded-lg border border-slate-800/50 bg-slate-900/80 backdrop-blur-sm overflow-hidden">
      <div className="flex items-center justify-between px-3 py-2 border-b border-slate-800/50">
        <div className="flex items-center gap-2">
          <ShieldCheck size={12} className="text-slate-400" />
          <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">Risk Meter</span>
        </div>
        <span className={cn('flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-bold border',
          worstStatus === 'safe' ? 'bg-emerald-950/50 text-emerald-400 border-emerald-800/30' :
          worstStatus === 'warning' ? 'bg-amber-950/50 text-amber-400 border-amber-800/30' :
          'bg-rose-950/50 text-rose-400 border-rose-800/30')}>
          <StatusIcon size={10} />
          {worstStatus.toUpperCase()}
        </span>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto p-3 space-y-2">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-[10px] text-slate-500">Today P&L</p>
            <p className={cn('text-2xl font-black tabular-nums', pnl >= 0 ? 'text-emerald-400' : 'text-rose-400')}>
              {pnl >= 0 ? '+' : ''}{'\u20B9'}{Math.abs(pnl).toLocaleString('en-IN')}
            </p>
          </div>
        </div>

        <div className="space-y-0.5">
          {positions.map((pos) => (
            <div key={pos.symbol} className="flex items-center justify-between rounded bg-slate-900/50 px-2 py-1 text-[10px]">
              <div className="flex items-center gap-2">
                <span className={cn('font-bold', pos.side === 'LONG' ? 'text-emerald-400' : 'text-rose-400')}>
                  {pos.side === 'LONG' ? 'L' : 'S'}
                </span>
                <span className="text-slate-300 font-medium">{pos.symbol}</span>
                <span className="text-slate-600">x{Math.abs(pos.qty)}</span>
              </div>
              <span className={cn('font-bold font-mono', pos.mtm >= 0 ? 'text-emerald-400' : 'text-rose-400')}>
                {pos.mtm >= 0 ? '+' : ''}{pos.mtm.toLocaleString()}
              </span>
            </div>
          ))}
        </div>

        <div className="space-y-1">
          {metrics.map((m) => (
            <div key={m.label} className="flex items-center gap-2">
              <span className="w-20 text-[10px] text-slate-500 truncate">{m.label}</span>
              <div className="flex-1 h-1.5 rounded-full bg-slate-800 overflow-hidden">
                <div
                  className={cn('h-full rounded-full transition-all duration-500', statusColor[m.status])}
                  style={{ width: `${(m.value / m.max) * 100}%` }}
                />
              </div>
              <span className="w-10 text-right text-[10px] font-bold text-slate-300">{m.value}{m.unit}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
