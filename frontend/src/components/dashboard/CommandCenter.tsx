import { useState } from 'react'
import { Target, TrendingUp, TrendingDown, Clock, ChevronDown, ChevronUp, AlertTriangle, Loader2 } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useDashboardStore } from '@/stores/dashboardStore'
import { useCommandCenter } from '@/api/dashboardApi'
import type { Signal } from '@/types/dashboard'

// ---------------------------------------------------------------------------
// CommandCenter -- THE dominant panel. A trader sees:
//   1. Signal (BUY/SELL/HOLD) in 48px -- impossible to miss
//   2. Entry / SL / Target / R:R immediately below
//   3. Top 3 reasons with strength bars
//   4. Primary risk warning
//   5. Collapsible: all reasons + similar trades
// ---------------------------------------------------------------------------

const signalGlow: Record<Signal, string> = {
  BUY: 'shadow-[0_0_40px_rgba(16,185,129,0.15)] border-emerald-500/40 bg-emerald-500/5',
  SELL: 'shadow-[0_0_40px_rgba(244,63,94,0.15)] border-rose-500/40 bg-rose-500/5',
  HOLD: 'shadow-[0_0_20px_rgba(245,158,11,0.1)] border-amber-500/30 bg-amber-500/5',
}

const signalText: Record<Signal, string> = {
  BUY: 'text-emerald-400',
  SELL: 'text-rose-400',
  HOLD: 'text-amber-400',
}

const signalBg: Record<Signal, string> = {
  BUY: 'bg-emerald-500',
  SELL: 'bg-rose-500',
  HOLD: 'bg-amber-500',
}

export function CommandCenter() {
  const mode = useDashboardStore((s) => s.mode)
  const symbol = useDashboardStore((s) => s.selectedSymbol)
  const alerts = useDashboardStore((s) => s.alerts)
  const { data: d, isLoading, isError } = useCommandCenter(symbol)
  const [showAllReasons, setShowAllReasons] = useState(false)
  const [showTrades, setShowTrades] = useState(false)

  if (isLoading || !d) {
    return (
      <div className="flex h-full items-center justify-center rounded-lg border border-slate-800/50 bg-slate-900/80">
        <Loader2 size={24} className="animate-spin text-slate-500" />
      </div>
    )
  }

  // Derive risk/reward
  const risk = Math.abs(d.entry - d.stopLoss)
  const reward = Math.abs(d.target - d.entry)
  const rrRatio = risk > 0 ? (reward / risk).toFixed(1) : '0'

  // Find the most important warning from store alerts
  const topWarning = alerts.find(
    (a) => !a.dismissed && (a.priority === 'critical' || a.priority === 'high'),
  )

  // Build reasons from reasoning text
  const reasons = d.reasoning
    ? [{ text: d.reasoning, strength: d.confidence }]
    : []
  const trades: Array<{ symbol: string; date: string; signal: Signal; outcome: 'WIN' | 'LOSS'; returnPct: number }> = []
  const visibleReasons = showAllReasons ? reasons : reasons.slice(0, 3)

  return (
    <div
      className={cn(
        'flex h-full flex-col rounded-lg border backdrop-blur-sm overflow-hidden',
        signalGlow[d.signal],
      )}
    >
      {/* Header strip */}
      <div className="flex items-center justify-between border-b border-slate-800/50 px-4 py-2">
        <div className="flex items-center gap-2">
          <Target size={14} className="text-slate-400" />
          <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">
            Command Center
          </span>
        </div>
        <span className="text-[10px] font-medium text-slate-500 tabular-nums">
          Conf: {d.confidence}%
        </span>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto p-4 space-y-4">
        {/* ── SIGNAL BLOCK ── */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            {/* Giant signal badge */}
            <div
              className={cn(
                'flex items-center justify-center rounded-lg px-5 py-2',
                signalBg[d.signal],
              )}
            >
              <span className="text-4xl font-black tracking-tight text-white leading-none">
                {d.signal}
              </span>
            </div>
            <div>
              <p className="text-lg font-bold text-slate-200">{d.symbol}</p>
              <p className="text-xs text-slate-500">
                Conf: <span className={cn('font-bold', signalText[d.signal])}>{d.confidence}%</span>
              </p>
            </div>
          </div>
        </div>

        {/* ── ENTRY / SL / TARGETS ── */}
        <div className="grid grid-cols-2 gap-2">
          {/* Entry */}
          <div className="rounded-lg bg-slate-800/50 border border-slate-700/50 p-3">
            <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">Entry</p>
            <p className={cn('text-xl font-black tabular-nums', signalText[d.signal])}>
              {'\u20B9'}{d.entry.toLocaleString('en-IN', { minimumFractionDigits: 1 })}
            </p>
          </div>
          {/* Stop Loss */}
          <div className="rounded-lg bg-rose-950/30 border border-rose-800/30 p-3">
            <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">Stop Loss</p>
            <p className="text-xl font-black tabular-nums text-rose-400">
              {'\u20B9'}{d.stopLoss.toLocaleString('en-IN', { minimumFractionDigits: 1 })}
            </p>
            <p className="text-[10px] text-rose-400/70 tabular-nums">
              Risk: {'\u20B9'}{risk.toFixed(1)}/share
            </p>
          </div>
          {/* T1 */}
          <div className="rounded-lg bg-emerald-950/30 border border-emerald-800/30 p-3">
            <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">Target 1</p>
            <p className="text-xl font-black tabular-nums text-emerald-400">
              {'\u20B9'}{d.target.toLocaleString('en-IN', { minimumFractionDigits: 1 })}
            </p>
          </div>
          {/* T2 */}
          <div className="rounded-lg bg-emerald-950/20 border border-emerald-800/20 p-3">
            <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">Target 2</p>
            <p className="text-lg font-bold tabular-nums text-emerald-400/80">
              {'\u20B9'}{(d.target + 50).toLocaleString('en-IN', { minimumFractionDigits: 1 })}
            </p>
          </div>
        </div>

        {/* R:R ratio strip */}
        <div className="flex items-center justify-between rounded-lg bg-slate-800/40 border border-slate-700/30 px-4 py-2">
          <span className="text-xs text-slate-400">Risk : Reward</span>
          <span className="text-lg font-black text-slate-100 tabular-nums">{rrRatio} : 1</span>
        </div>

        {/* ── TOP REASONS (why) ── */}
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-500 mb-2">
            Why {d.signal}? (top {showAllReasons ? reasons.length : 3})
          </p>
          <div className="space-y-1.5">
            {visibleReasons.map((r, i) => (
              <div key={i} className="flex items-center gap-2">
                <span className="text-emerald-500 text-xs">{'\u25CF'}</span>
                <span className="flex-1 text-xs text-slate-300 leading-snug">{r.text}</span>
                <div className="w-16 h-2 rounded-full bg-slate-800 overflow-hidden shrink-0">
                  <div
                    className={cn(
                      'h-full rounded-full',
                      r.strength >= 80
                        ? 'bg-emerald-500'
                        : r.strength >= 60
                          ? 'bg-sky-500'
                          : 'bg-slate-500',
                    )}
                    style={{ width: `${r.strength}%` }}
                  />
                </div>
                <span className="w-8 text-right text-[10px] font-bold text-slate-400 tabular-nums">
                  {r.strength}%
                </span>
              </div>
            ))}
          </div>

          {reasons.length > 3 && (
            <button
              onClick={() => setShowAllReasons(!showAllReasons)}
              className="mt-2 flex items-center gap-1 text-[10px] text-sky-400 hover:text-sky-300 transition-colors"
            >
              {showAllReasons ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
              {showAllReasons ? 'Show less' : `All ${reasons.length} reasons`}
            </button>
          )}
        </div>

        {/* ── RISK WARNING ── */}
        {topWarning && (
          <div className="flex items-start gap-2 rounded-lg border border-amber-500/30 bg-amber-950/20 p-3">
            <AlertTriangle size={14} className="text-amber-400 shrink-0 mt-0.5" />
            <div>
              <p className="text-xs font-semibold text-amber-300">{topWarning.title}</p>
              <p className="text-[10px] text-amber-400/70">{topWarning.message}</p>
            </div>
          </div>
        )}

        {/* ── SIMILAR TRADES (collapsed) ── */}
        {mode === 'execution' && (
          <div>
            <button
              onClick={() => setShowTrades(!showTrades)}
              className="flex items-center gap-1 text-[10px] text-slate-500 hover:text-slate-300 transition-colors"
            >
              {showTrades ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
              Similar trades ({trades.length})
            </button>
            {showTrades && (
              <div className="mt-1.5 space-y-1">
                {trades.map((t, i) => (
                  <div
                    key={i}
                    className="flex items-center justify-between rounded bg-slate-900/50 px-2 py-1"
                  >
                    <div className="flex items-center gap-2">
                      {t.outcome === 'WIN' ? (
                        <TrendingUp size={10} className="text-emerald-400" />
                      ) : (
                        <TrendingDown size={10} className="text-rose-400" />
                      )}
                      <span className="text-[10px] text-slate-400">{t.symbol}</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <Clock size={9} className="text-slate-600" />
                      <span className="text-[10px] text-slate-500">{t.date}</span>
                      <span
                        className={cn(
                          'text-[10px] font-bold',
                          t.returnPct >= 0 ? 'text-emerald-400' : 'text-rose-400',
                        )}
                      >
                        {t.returnPct > 0 ? '+' : ''}
                        {t.returnPct}%
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* ── RESEARCH MODE: Show full details ── */}
        {mode === 'research' && (
          <div className="space-y-2">
            <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">
              Similar Trades
            </p>
            {trades.map((t, i) => (
              <div
                key={i}
                className="flex items-center justify-between rounded bg-slate-900/50 px-2 py-1"
              >
                <div className="flex items-center gap-2">
                  {t.outcome === 'WIN' ? (
                    <TrendingUp size={10} className="text-emerald-400" />
                  ) : (
                    <TrendingDown size={10} className="text-rose-400" />
                  )}
                  <span className="text-[10px] text-slate-400">{t.symbol}</span>
                </div>
                <div className="flex items-center gap-2">
                  <Clock size={9} className="text-slate-600" />
                  <span className="text-[10px] text-slate-500">{t.date}</span>
                  <span
                    className={cn(
                      'text-[10px] font-bold',
                      t.returnPct >= 0 ? 'text-emerald-400' : 'text-rose-400',
                    )}
                  >
                    {t.returnPct > 0 ? '+' : ''}
                    {t.returnPct}%
                  </span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
