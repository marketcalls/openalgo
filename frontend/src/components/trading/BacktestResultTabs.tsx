/**
 * A backtest's equity curve, its drawdown and its trades, one tab at a time.
 *
 * Inline tabs rather than a stack, because the panel is narrow and each of the
 * three wants its full height: an equity curve squeezed into half of a small
 * box beside its drawdown was easy to miss entirely. The tab last chosen is
 * remembered in this browser, so a trader who reads drawdown first gets it
 * first on the next run.
 */

import { type ReactNode, useState } from 'react'
import type { BacktestOutcome } from '@/lib/trading/backtestRun'
import { cn } from '@/lib/utils'
import { BacktestChart, type CurvePoint, seriesFrom } from './BacktestChart'

type Tab = 'equity' | 'drawdown' | 'trades'

const TABS: { id: Tab; label: string }[] = [
  { id: 'equity', label: 'Equity' },
  { id: 'drawdown', label: 'Drawdown' },
  { id: 'trades', label: 'Trades' },
]

const TAB_KEY = 'trading.panel.backtest.tab'

function storedTab(): Tab {
  try {
    const value = window.localStorage.getItem(TAB_KEY)
    return value === 'drawdown' || value === 'trades' ? value : 'equity'
  } catch {
    return 'equity'
  }
}

function rememberTab(tab: Tab): void {
  try {
    window.localStorage.setItem(TAB_KEY, tab)
  } catch {
    // Not remembered; the choice still applies now.
  }
}

interface Props {
  outcome: BacktestOutcome
  /** How the panel writes money, so the trades read as the figures above do. */
  money: (value: unknown) => string
}

export function BacktestResultTabs({ outcome, money }: Props) {
  const [tab, setTab] = useState<Tab>(storedTab)
  const points = (outcome.equity ?? []) as readonly CurvePoint[]
  const trades = outcome.trades ?? []

  const choose = (next: Tab) => {
    setTab(next)
    rememberTab(next)
  }

  let body: ReactNode
  if (tab === 'trades') {
    body =
      trades.length === 0 ? (
        <Empty>This run took no trades.</Empty>
      ) : (
        <div className="max-h-60 overflow-y-auto rounded border border-border">
          <table className="w-full text-[10px]">
            <thead className="sticky top-0 bg-muted/60 text-muted-foreground">
              <tr>
                <th className="px-1.5 py-1 text-left font-normal">Side</th>
                <th className="px-1.5 py-1 text-right font-normal">Entry</th>
                <th className="px-1.5 py-1 text-right font-normal">Exit</th>
                <th className="px-1.5 py-1 text-right font-normal">Net</th>
              </tr>
            </thead>
            <tbody className="font-mono tabular-nums">
              {trades.map((t) => (
                <tr key={String(t.index)} className="border-t border-border">
                  <td className="px-1.5 py-1">{String(t.side)}</td>
                  <td className="px-1.5 py-1 text-right">{money(t.entryPrice)}</td>
                  <td className="px-1.5 py-1 text-right">
                    {t.isOpen ? 'open' : money(t.exitPrice)}
                  </td>
                  <td
                    className={cn(
                      'px-1.5 py-1 text-right',
                      Number(t.netProfit) >= 0 ? 'text-emerald-500' : 'text-destructive'
                    )}
                  >
                    {money(t.netProfit)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )
  } else if (seriesFrom(points)[tab].length < 2) {
    body = (
      <Empty>
        {tab === 'equity'
          ? 'This run has too few bars to draw an equity curve.'
          : 'This run has too few bars to draw its drawdown.'}
      </Empty>
    )
  } else {
    // Keyed by tab, so switching builds the chart afresh for the series shown.
    body = <BacktestChart key={tab} points={points} show={tab} />
  }

  return (
    <div className="flex flex-col gap-1.5">
      <div role="tablist" aria-label="Backtest results" className="flex gap-1">
        {TABS.map(({ id, label }) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={tab === id}
            onClick={() => choose(id)}
            className={cn(
              'h-6 rounded px-2 text-[11px] transition-colors',
              tab === id
                ? 'bg-accent font-medium text-foreground'
                : 'text-muted-foreground hover:bg-accent/50 hover:text-foreground'
            )}
          >
            {label}
            {id === 'trades' && trades.length > 0 ? ` (${trades.length})` : ''}
          </button>
        ))}
      </div>
      <div role="tabpanel" aria-label={TABS.find((t) => t.id === tab)?.label}>
        {body}
      </div>
    </div>
  )
}

function Empty({ children }: { children: ReactNode }) {
  return (
    <p className="flex h-24 items-center justify-center rounded border border-dashed border-border px-3 text-center text-[11px] text-muted-foreground">
      {children}
    </p>
  )
}
