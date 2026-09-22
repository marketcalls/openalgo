/**
 * Backtesting a saved strategy, beside the chart it will trade.
 *
 * Sits on the same rail as the script editor and wears the same clothes,
 * because the two are one activity seen twice: a trader writes a strategy in
 * one panel and asks what it would have done in the other, over the instrument
 * the chart is already showing.
 *
 * **The instrument and the interval are the chart's, not this panel's.** A
 * backtest of something other than what the trader is looking at is the one
 * result they will misread, so there is no symbol box here. Changing the chart
 * changes what runs.
 *
 * **Only strategies are offered.** A study plots and places no orders, so it
 * has no trades, no equity curve and no report. Listing studies here would be
 * offering a button that can only ever answer with a refusal.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { cn } from '@/lib/utils'
import {
  type BacktestOutcome,
  MAX_BARS,
  runBacktest,
} from '@/lib/trading/backtestRun'
import { kindOf, listScripts, readScript, type StoredScript } from '@/lib/trading/openscriptFiles'
import { BacktestChart } from './BacktestChart'
import { PANEL_HEADER, PanelShell } from './panelShell'

/** The three chart facts a run is of. */
export interface RunTarget {
  symbol: string
  exchange: string
  interval: string
}

interface Props {
  apiKey: string
  /**
   * The chart this run is of, read fresh rather than held.
   *
   * A function and not three props, because the instrument, the exchange and
   * the interval are the chart's and change under this panel without it
   * re-rendering. Read at the moment Run is pressed, a backtest is always of
   * what the trader is looking at; held as props, it is of whatever the page
   * last happened to pass down.
   */
  getChartContext(): { symbol: string; exchange: string; interval: string } | null
}

/** How far back a run reaches when the panel is first opened. */
const DEFAULT_DAYS = 180

function isoDaysAgo(days: number): string {
  const at = new Date()
  at.setDate(at.getDate() - days)
  return at.toISOString().slice(0, 10)
}

function today(): string {
  return new Date().toISOString().slice(0, 10)
}

function money(value: unknown, digits = 2): string {
  const n = Number(value)
  if (!Number.isFinite(n)) return '-'
  return n.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits })
}

function percent(value: unknown): string {
  const n = Number(value)
  if (!Number.isFinite(n)) return '-'
  return `${(n * 100).toFixed(2)}%`
}

/** A figure that is absent rather than zero is shown as absent, never as 0. */
function orDash(value: unknown, render: (v: unknown) => string): string {
  return value === null || value === undefined ? '-' : render(value)
}

function Figure({
  label,
  value,
  tone = 'plain',
}: {
  label: string
  value: string
  tone?: 'plain' | 'good' | 'bad'
}) {
  return (
    <div className="flex flex-col gap-0.5 rounded border border-border px-2 py-1.5">
      <span className="text-[10px] uppercase leading-none tracking-wide text-muted-foreground">
        {label}
      </span>
      <span
        className={cn(
          'font-mono text-[13px] leading-none tabular-nums',
          tone === 'good' && 'text-emerald-500',
          tone === 'bad' && 'text-destructive'
        )}
      >
        {value}
      </span>
    </div>
  )
}

export function BacktestPanel({ apiKey, getChartContext }: Props) {
  // Only for the header. The run reads its own, fresh, at the moment it starts.
  const [target, setTarget] = useState<RunTarget | null>(null)
  const [scripts, setScripts] = useState<StoredScript[]>([])
  const [file, setFile] = useState<string>('')
  const [from, setFrom] = useState(() => isoDaysAgo(DEFAULT_DAYS))
  const [to, setTo] = useState(() => today())
  const [running, setRunning] = useState(false)
  const [outcome, setOutcome] = useState<BacktestOutcome | null>(null)
  const inflight = useRef<AbortController | null>(null)

  // Only strategies, which means reading each script to ask what it declares
  // itself to be. The list is small and this happens once per panel open.
  useEffect(() => {
    let live = true
    const controller = new AbortController()

    void (async () => {
      try {
        const found = await listScripts(controller.signal)
        const strategies: StoredScript[] = []
        for (const one of found) {
          const source = await readScript(one.file, controller.signal)
          if ((await kindOf(source)) === 'strategy') strategies.push(one)
        }
        if (!live) return
        setScripts(strategies)
        setFile((held) => held || (strategies[0]?.file ?? ''))
      } catch {
        if (live) setScripts([])
      }
    })()

    return () => {
      live = false
      controller.abort()
    }
  }, [])

  // The chart is not ours and does not tell us when it changes, so the header
  // is refreshed on a timer. One second is below noticing and costs a property
  // read. The run does not rely on this: it reads its own.
  useEffect(() => {
    const read = () => {
      const now = getChartContext()
      setTarget((held) =>
        now &&
        (held?.symbol !== now.symbol ||
          held?.exchange !== now.exchange ||
          held?.interval !== now.interval)
          ? { symbol: now.symbol, exchange: now.exchange, interval: now.interval }
          : now
            ? held
            : null
      )
    }
    read()
    const timer = window.setInterval(read, 1000)
    return () => window.clearInterval(timer)
  }, [getChartContext])

  useEffect(() => () => inflight.current?.abort(), [])

  const run = useCallback(async () => {
    const chart = getChartContext()
    if (!file || !chart) return

    inflight.current?.abort()
    const controller = new AbortController()
    inflight.current = controller

    setRunning(true)
    setOutcome(null)
    try {
      const source = await readScript(file, controller.signal)
      const result = await runBacktest({
        file,
        source,
        symbol: chart.symbol,
        exchange: chart.exchange,
        interval: chart.interval,
        startDate: from,
        endDate: to,
        apiKey,
        signal: controller.signal,
      })
      if (!controller.signal.aborted) setOutcome(result)
    } catch {
      if (!controller.signal.aborted) {
        setOutcome({ ok: false, problem: 'The script could not be read.' })
      }
    } finally {
      if (!controller.signal.aborted) setRunning(false)
    }
  }, [apiKey, file, from, getChartContext, to])

  const summary = outcome?.summary
  const ready = Boolean(file && target) && !running

  return (
    <PanelShell
      id="trading-backtest-panel"
      label="Backtest"
      storageKey="trading.panel.backtest.width"
      defaultWidth={400}
      minWidth={320}
    >
      <div className={PANEL_HEADER}>
        <span className="text-xs font-medium">Backtest</span>
        <span className="ml-auto truncate font-mono text-[11px] text-muted-foreground">
          {target ? `${target.symbol} ${target.interval}` : 'No chart'}
        </span>
      </div>

      <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto p-2">
        <label className="flex flex-col gap-1">
          <span className="text-[10px] uppercase tracking-wide text-muted-foreground">Strategy</span>
          <select
            className="h-8 rounded border border-border bg-background px-2 text-xs"
            value={file}
            onChange={(e) => setFile(e.target.value)}
            disabled={scripts.length === 0}
          >
            {scripts.length === 0 && <option value="">No strategies saved</option>}
            {scripts.map((one) => (
              <option key={one.file} value={one.file}>
                {one.file}
              </option>
            ))}
          </select>
        </label>

        <div className="grid grid-cols-2 gap-2">
          <label className="flex flex-col gap-1">
            <span className="text-[10px] uppercase tracking-wide text-muted-foreground">From</span>
            <input
              type="date"
              className="h-8 rounded border border-border bg-background px-2 text-xs"
              value={from}
              max={to}
              onChange={(e) => setFrom(e.target.value)}
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-[10px] uppercase tracking-wide text-muted-foreground">To</span>
            <input
              type="date"
              className="h-8 rounded border border-border bg-background px-2 text-xs"
              value={to}
              min={from}
              onChange={(e) => setTo(e.target.value)}
            />
          </label>
        </div>

        <button
          type="button"
          className="h-8 rounded border border-border bg-accent/40 text-xs font-medium hover:bg-accent disabled:opacity-50"
          onClick={() => void run()}
          disabled={!ready}
        >
          {running ? 'Running' : 'Run backtest'}
        </button>

        {!target && (
          <p className="text-[11px] text-muted-foreground">
            Open a chart first. A run is of the instrument and interval on the chart beside it.
          </p>
        )}

        {outcome?.problem && (
          <p className="rounded border border-destructive/40 px-2 py-1.5 text-[11px] text-destructive">
            {outcome.problem}
          </p>
        )}

        {outcome?.diagnostics && outcome.diagnostics.length > 0 && (
          <div className="flex flex-col gap-1 rounded border border-destructive/40 p-2">
            <span className="text-[11px] font-medium text-destructive">
              This script does not compile
            </span>
            {outcome.diagnostics.slice(0, 5).map((d) => (
              <span key={`${d.code}-${d.line}-${d.column}`} className="font-mono text-[10px] text-muted-foreground">
                {d.line}:{d.column} {d.code} {d.message}
              </span>
            ))}
          </div>
        )}

        {summary && (
          <>
            <div className="grid grid-cols-2 gap-1.5">
              <Figure
                label="Net profit"
                value={money(summary.netProfit)}
                tone={Number(summary.netProfit) >= 0 ? 'good' : 'bad'}
              />
              <Figure label="Return" value={percent(summary.returnPercent)} />
              <Figure label="Trades" value={String(summary.tradeCount ?? '-')} />
              <Figure label="Win rate" value={orDash(summary.winRate, percent)} />
              <Figure label="Profit factor" value={orDash(summary.profitFactor, (v) => money(v))} />
              <Figure label="Expectancy" value={money(summary.expectancy)} />
              <Figure label="Max drawdown" value={money(summary.maxDrawdown)} tone="bad" />
              <Figure label="Max run-up" value={money(summary.maxRunUp)} tone="good" />
            </div>

            <BacktestChart points={outcome?.equity ?? []} />

            <p className="text-[10px] text-muted-foreground">
              {outcome?.barCount?.toLocaleString()} bars, {Math.round(outcome?.ranMs ?? 0)}ms
              {outcome?.contract?.usedFallback
                ? '. This instrument has no stored tick or lot size, so the run used a tick of ' +
                  `${outcome.contract.tickSize} and a lot of ${outcome.contract.lotSize}. Every figure in money rests on those.`
                : `. Tick ${outcome?.contract?.tickSize}, lot ${outcome?.contract?.lotSize}.`}
            </p>

            {Number(summary.openTradeCount) > 0 && (
              <p className="text-[10px] text-muted-foreground">
                {String(summary.openTradeCount)} trade(s) were still open at the last bar. Their
                charges are counted and their profit is not, because it has not been realised.
              </p>
            )}

            {outcome?.trades && outcome.trades.length > 0 && (
              <div className="flex flex-col gap-1">
                <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
                  Trades
                </span>
                <div className="max-h-56 overflow-y-auto rounded border border-border">
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
                      {outcome.trades.map((t) => (
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
              </div>
            )}
          </>
        )}

        <p className="mt-auto text-[10px] leading-relaxed text-muted-foreground">
          A run covers up to {MAX_BARS.toLocaleString()} bars and happens here in the browser, on
          the same engine the platform runs a strategy with. Nothing is sent to a broker.
        </p>
      </div>
    </PanelShell>
  )
}
