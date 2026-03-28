import { Activity, Loader2 } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useDashboardStore } from '@/stores/dashboardStore'
import { useOIIntelligence } from '@/api/dashboardApi'

// ---------------------------------------------------------------------------
// OIIntelligence -- Execution: compact single line summary.
// "PCR 0.85 up | MaxPain 2850 | Long Buildup | GEX support 2820"
// Research: full OI table + PCR chart.
// ---------------------------------------------------------------------------

export function OIIntelligence() {
  const mode = useDashboardStore((s) => s.mode)
  const symbol = useDashboardStore((s) => s.selectedSymbol)
  const { data: oiData, isLoading } = useOIIntelligence(symbol)

  if (isLoading || !oiData) {
    return (
      <div className="flex h-full items-center justify-center rounded-lg border border-slate-800/50 bg-slate-900/80">
        <Loader2 size={20} className="animate-spin text-slate-500" />
      </div>
    )
  }

  const levels = oiData.levels ?? []
  const latestPCR = oiData.pcr ?? 1.0
  const prevPCR = latestPCR // No history from API yet
  const pcrDir = latestPCR > 1.0 ? '\u25B2' : latestPCR < 1.0 ? '\u25BC' : '\u25C6'
  const maxPain = oiData.maxPain ?? 0
  const spotPrice = maxPain // Best approximation
  const gexFlip = oiData.gexFlip ?? 0

  // Execution compact
  if (mode === 'execution') {
    return (
      <div className="flex h-full flex-col rounded-lg border border-slate-800/50 bg-slate-900/80 backdrop-blur-sm overflow-hidden">
        <div className="flex items-center justify-between px-3 py-2 border-b border-slate-800/50">
          <div className="flex items-center gap-2">
            <Activity size={12} className="text-slate-400" />
            <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">OI Intel</span>
          </div>
        </div>

        <div className="flex-1 min-h-0 p-3 space-y-2">
          {/* Single line summary */}
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
            <div className="flex items-center gap-1">
              <span className="text-slate-400">PCR</span>
              <span className={cn('font-bold', latestPCR > 1 ? 'text-emerald-400' : 'text-rose-400')}>
                {latestPCR.toFixed(2)}
              </span>
              <span className={cn('text-[10px]', latestPCR > prevPCR ? 'text-emerald-400' : 'text-rose-400')}>
                {pcrDir}
              </span>
            </div>
            <span className="text-slate-700">|</span>
            <div className="flex items-center gap-1">
              <span className="text-slate-400">MaxPain</span>
              <span className="font-bold text-amber-400">{maxPain}</span>
            </div>
            <span className="text-slate-700">|</span>
            <span className="font-bold text-emerald-400">Long Buildup</span>
            <span className="text-slate-700">|</span>
            <div className="flex items-center gap-1">
              <span className="text-slate-400">GEX</span>
              <span className="font-bold text-sky-400">{gexFlip}</span>
            </div>
          </div>

          {/* Key walls */}
          {levels.length > 0 && (
          <div className="grid grid-cols-2 gap-2 text-center text-[10px]">
            <div className="rounded bg-emerald-950/20 border border-emerald-800/20 p-1.5">
              <p className="text-slate-500">Put Wall (support)</p>
              <p className="font-bold text-emerald-400">{oiData.putWall || levels[0]?.strike || 0}</p>
            </div>
            <div className="rounded bg-rose-950/20 border border-rose-800/20 p-1.5">
              <p className="text-slate-500">Call Wall (resist)</p>
              <p className="font-bold text-rose-400">{oiData.callWall || levels[levels.length - 1]?.strike || 0}</p>
            </div>
          </div>
          )}

          {/* PCR indicator */}
          <div>
            <p className="text-[9px] text-slate-500 mb-1">PCR</p>
            <div className="flex items-center gap-2">
              <div className="flex-1 h-3 rounded-full bg-slate-800 overflow-hidden">
                <div
                  className={cn('h-full rounded-full', latestPCR >= 1 ? 'bg-emerald-500/60' : 'bg-rose-500/60')}
                  style={{ width: `${Math.min(latestPCR / 2, 1) * 100}%` }}
                />
              </div>
              <span className={cn('text-[10px] font-bold', latestPCR >= 1 ? 'text-emerald-400' : 'text-rose-400')}>
                {latestPCR.toFixed(2)}
              </span>
            </div>
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
          <Activity size={12} className="text-slate-400" />
          <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">OI Intelligence</span>
        </div>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto p-3 space-y-2">
        <div className="grid grid-cols-3 gap-2">
          <div className="flex flex-col items-center rounded bg-slate-900/50 p-1.5">
            <span className="text-[9px] text-slate-500">PCR</span>
            <span className={cn('text-lg font-black', latestPCR > 1 ? 'text-emerald-400' : 'text-rose-400')}>
              {latestPCR.toFixed(2)}
            </span>
            <span className="text-[9px] text-slate-500">{latestPCR > 1 ? 'Bullish' : 'Bearish'}</span>
          </div>
          <div className="flex flex-col items-center rounded bg-slate-900/50 p-1.5">
            <span className="text-[9px] text-slate-500">Max Pain</span>
            <span className="text-lg font-black text-amber-400">{maxPain}</span>
            <span className="text-[9px] text-slate-500">+{spotPrice - maxPain} pts</span>
          </div>
          <div className="flex flex-col items-center rounded bg-slate-900/50 p-1.5">
            <span className="text-[9px] text-slate-500">GEX Flip</span>
            <span className="text-lg font-black text-sky-400">{gexFlip}</span>
            <span className="text-[9px] text-slate-500">{gexFlip - spotPrice} pts away</span>
          </div>
        </div>

        <div className="flex items-center justify-between rounded bg-emerald-950/30 border border-emerald-800/30 px-2 py-1">
          <span className="text-[10px] text-slate-400">Build-up</span>
          <span className="text-[10px] font-bold text-emerald-400">LONG BUILD-UP</span>
          <span className="text-[10px] text-emerald-400">+2.4L OI</span>
        </div>

        {levels.length > 0 && (
        <div className="grid grid-cols-2 gap-2 text-center text-[10px]">
          <div className="rounded bg-rose-950/30 border border-rose-800/20 p-1.5">
            <p className="text-slate-500">Call Wall</p>
            <p className="font-bold text-rose-400">{oiData.callWall || levels[levels.length - 1]?.strike || 0}</p>
            <p className="text-[9px] text-slate-500">{((levels[levels.length - 1]?.callOI ?? 0) / 100000).toFixed(1)}L OI</p>
          </div>
          <div className="rounded bg-emerald-950/30 border border-emerald-800/20 p-1.5">
            <p className="text-slate-500">Put Wall</p>
            <p className="font-bold text-emerald-400">{oiData.putWall || levels[0]?.strike || 0}</p>
            <p className="text-[9px] text-slate-500">{((levels[0]?.putOI ?? 0) / 100000).toFixed(1)}L OI</p>
          </div>
        </div>
        )}

        <div>
          <p className="text-[9px] text-slate-500 mb-1">PCR</p>
          <div className="flex items-center gap-2">
            <div className="flex-1 h-3 rounded-full bg-slate-800 overflow-hidden">
              <div
                className={cn('h-full rounded-full', latestPCR >= 1 ? 'bg-emerald-500/60' : 'bg-rose-500/60')}
                style={{ width: `${Math.min(latestPCR / 2, 1) * 100}%` }}
              />
            </div>
            <span className={cn('text-[10px] font-bold', latestPCR >= 1 ? 'text-emerald-400' : 'text-rose-400')}>
              {latestPCR.toFixed(2)}
            </span>
          </div>
        </div>
      </div>
    </div>
  )
}
