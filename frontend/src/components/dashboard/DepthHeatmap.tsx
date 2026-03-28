import { BookOpen } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useDashboardStore } from '@/stores/dashboardStore'

// ---------------------------------------------------------------------------
// DepthHeatmap -- Quiet by default. PULSES when imbalance > 1.5x.
// Execution: compact imbalance indicator + top bid/ask.
// Research: full depth ladder.
// ---------------------------------------------------------------------------

export function DepthHeatmap() {
  const mode = useDashboardStore((s) => s.mode)
  const symbol = useDashboardStore((s) => s.selectedSymbol)
  const depthData = useDashboardStore((s) => s.depth[symbol])
  const bids = depthData?.bids ?? []
  const asks = depthData?.asks ?? []
  const totalBid = bids.reduce((s, b) => s + b.qty, 0)
  const totalAsk = asks.reduce((s, a) => s + a.qty, 0)
  const maxQty = bids.length > 0 || asks.length > 0
    ? Math.max(...bids.map((b) => b.qty), ...asks.map((a) => a.qty), 1)
    : 1
  const imbalance = totalBid + totalAsk > 0 ? totalBid / (totalBid + totalAsk) : 0.5
  const isSignificant = imbalance > 0.6 || imbalance < 0.4

  // Execution compact
  if (mode === 'execution') {
    return (
      <div
        className={cn(
          'flex h-full flex-col rounded-lg border backdrop-blur-sm overflow-hidden transition-all duration-700',
          isSignificant
            ? imbalance > 0.6
              ? 'border-emerald-500/40 bg-emerald-950/20 shadow-[0_0_15px_rgba(16,185,129,0.1)]'
              : 'border-rose-500/40 bg-rose-950/20 shadow-[0_0_15px_rgba(244,63,94,0.1)]'
            : 'border-slate-800/50 bg-slate-900/80',
        )}
      >
        <div className="flex items-center justify-between px-3 py-2 border-b border-slate-800/50">
          <div className="flex items-center gap-2">
            <BookOpen size={12} className="text-slate-400" />
            <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">Depth</span>
          </div>
          <span
            className={cn(
              'text-[10px] font-bold',
              imbalance > 0.55 ? 'text-emerald-400' : imbalance < 0.45 ? 'text-rose-400' : 'text-amber-400',
            )}
          >
            {(imbalance * 100).toFixed(0)}% bid
          </span>
        </div>

        <div className="flex-1 min-h-0 p-3 space-y-2">
          {/* Imbalance bar */}
          <div>
            <div className="flex h-3 w-full overflow-hidden rounded-full bg-slate-800">
              <div
                className={cn(
                  'transition-all duration-500',
                  imbalance > 0.55 ? 'bg-emerald-500' : imbalance < 0.45 ? 'bg-rose-500' : 'bg-amber-500',
                )}
                style={{ width: `${imbalance * 100}%` }}
              />
              <div
                className="bg-rose-500/60 transition-all duration-500"
                style={{ width: `${(1 - imbalance) * 100}%` }}
              />
            </div>
            <div className="flex justify-between text-[10px] mt-0.5">
              <span className="text-emerald-400">{totalBid.toLocaleString()}</span>
              <span className="text-rose-400">{totalAsk.toLocaleString()}</span>
            </div>
          </div>

          {/* Top bid/ask only */}
          <div className="grid grid-cols-2 gap-2 text-center text-[10px]">
            <div className="rounded bg-emerald-950/20 border border-emerald-800/20 p-1.5">
              <p className="text-slate-500">Best Bid</p>
              <p className="font-bold text-emerald-400">{bids[0]?.price ?? '-'}</p>
              <p className="text-[9px] text-slate-500">{bids[0]?.qty?.toLocaleString() ?? 0} qty</p>
            </div>
            <div className="rounded bg-rose-950/20 border border-rose-800/20 p-1.5">
              <p className="text-slate-500">Best Ask</p>
              <p className="font-bold text-rose-400">{asks[0]?.price ?? '-'}</p>
              <p className="text-[9px] text-slate-500">{asks[0]?.qty?.toLocaleString() ?? 0} qty</p>
            </div>
          </div>

          {isSignificant && (
            <div
              className={cn(
                'rounded px-2 py-1 text-[10px] text-center font-bold animate-pulse',
                imbalance > 0.6
                  ? 'bg-emerald-950/30 border border-emerald-800/30 text-emerald-400'
                  : 'bg-rose-950/30 border border-rose-800/30 text-rose-400',
              )}
            >
              {imbalance > 0.6 ? 'BID HEAVY - Buyers in control' : 'ASK HEAVY - Sellers in control'}
            </div>
          )}
        </div>
      </div>
    )
  }

  // Research: full depth ladder
  return (
    <div className="flex h-full flex-col rounded-lg border border-slate-800/50 bg-slate-900/80 backdrop-blur-sm overflow-hidden">
      <div className="flex items-center justify-between px-3 py-2 border-b border-slate-800/50">
        <div className="flex items-center gap-2">
          <BookOpen size={12} className="text-slate-400" />
          <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">Depth Heatmap</span>
        </div>
        <span
          className={cn(
            'text-[10px] font-bold',
            imbalance > 0.55 ? 'text-emerald-400' : imbalance < 0.45 ? 'text-rose-400' : 'text-amber-400',
          )}
        >
          {(imbalance * 100).toFixed(1)}% bid
        </span>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto p-3 space-y-2">
        <div className="flex items-center justify-between text-[10px]">
          <span className="text-emerald-400 font-bold">Bid: {totalBid.toLocaleString()}</span>
          <span className="text-rose-400 font-bold">Ask: {totalAsk.toLocaleString()}</span>
        </div>
        <div className="space-y-0.5">
          {bids.map((bid, i) => {
            const ask = asks[i]
            const bidPct = (bid.qty / maxQty) * 100
            const askPct = ask ? (ask.qty / maxQty) * 100 : 0
            return (
              <div key={bid.price} className="flex items-center gap-1 text-[10px]">
                <div className="flex-1 flex justify-end">
                  <div
                    className="h-4 rounded-l bg-emerald-600/40 border-r-2 border-emerald-500 flex items-center justify-end px-1"
                    style={{ width: `${bidPct}%` }}
                  >
                    <span className="text-[9px] text-emerald-300 font-mono">{bid.qty.toLocaleString()}</span>
                  </div>
                </div>
                <div className="w-14 text-center font-mono font-bold text-slate-300 shrink-0">{bid.price}</div>
                <div className="flex-1">
                  {ask && (
                    <div
                      className="h-4 rounded-r bg-rose-600/40 border-l-2 border-rose-500 flex items-center px-1"
                      style={{ width: `${askPct}%` }}
                    >
                      <span className="text-[9px] text-rose-300 font-mono">{ask.qty.toLocaleString()}</span>
                    </div>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
