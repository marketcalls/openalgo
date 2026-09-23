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

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { type PriceableItem, useLivePrice } from '@/hooks/useLivePrice'
import { cn } from '@/lib/utils'
import {
  type BacktestOutcome,
  MAX_BARS,
  type RunStop,
  runBacktest,
} from '@/lib/trading/backtestRun'
import {
  declaredOf,
  inputsOf,
  settingsFromForm,
} from '@/lib/trading/backtestInputs'
import { chartMarkersFrom } from '@/lib/trading/backtestMarkers'
import {
  markToPrice,
  openCountOf,
  openPositionOf,
  type ReportTrade,
} from '@/lib/trading/openPosition'
import { quantityNote, quantityOf, unitsFor } from '@/lib/trading/strategyQuantity'
import { backtestLookbackDays } from '@/lib/trading/intervals'
import {
  compileSource,
  kindOf,
  listScripts,
  readScript,
  type StoredScript,
} from '@/lib/trading/openscriptFiles'
import { BacktestChart } from './BacktestChart'
import { StrategyInputs } from './StrategyInputs'
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
  /**
   * Put this run's fills on the price, or clear them with an empty list.
   *
   * Answers false when there is no price series to mark, which a pane still
   * loading its history reaches, so the panel can say the chart was not marked
   * rather than leaving a reader to wonder where the arrows are.
   */
  onMarkChart?(markers: readonly unknown[]): boolean
  /**
   * A strategy another panel wants run, or null.
   *
   * The editor's apply button hands one over rather than refusing: applying a
   * strategy to a chart means testing it over that chart's history and marking
   * what it did, which is the only thing "apply" can honestly mean for a script
   * that trades. Cleared through `onRan` so the same file can be sent twice.
   */
  /**
   * Bumped by the page when what `getChartContext` would answer has changed.
   *
   * The chart is not a value this can depend on, so this stands in for one.
   */
  chartRevision?: number
  runFile?: string | null
  onRan?(): void
}

/**
 * How far back a run reaches when the panel is first opened.
 *
 * **Coupled to `MAX_BARS`, which is why the number is written down here rather
 * than chosen.** A hundred and eighty days is about a hundred and twenty three
 * trading sessions, and an Indian equity session is 375 minutes, so the default
 * range at the finest interval asks for roughly forty six thousand bars. That
 * sits just under the ceiling on purpose: the panel's own default has to be a
 * range the panel will actually run, and before the ceiling was raised this
 * default was refused outright at one minute.
 *
 * Raising this without raising `MAX_BARS` puts the panel back in that state,
 * where the first thing a trader sees on opening it is a refusal.
 */
export const DEFAULT_DAYS = 180

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

/**
 * A bar's time as the chart would label it: in the instrument's own zone.
 *
 * The zone is the one the run read its clock in. Without one, or with one this
 * browser cannot read, it is this browser's own clock, which is still a time a
 * trader can find on the chart.
 */
function barClock(time: number, zone: string | undefined): string {
  const shape: Intl.DateTimeFormatOptions = {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }
  try {
    return new Intl.DateTimeFormat(undefined, { ...shape, timeZone: zone }).format(time)
  } catch {
    return new Intl.DateTimeFormat(undefined, shape).format(time)
  }
}

/** Where a stopped run stopped: the bar, counted as a trader counts, and its time. */
export function stoppedAt(
  stop: RunStop,
  barCount: number | undefined,
  zone: string | undefined
): string {
  if (stop.barIndex === null) return 'This run stopped part way through'
  const bar = (stop.barIndex + 1).toLocaleString()
  const of = barCount ? ` of ${barCount.toLocaleString()}` : ''
  const when = stop.barTime === null ? '' : `, ${barClock(stop.barTime, zone)}`
  return `This run stopped on bar ${bar}${of}${when}`
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

export function BacktestPanel({
  apiKey,
  getChartContext,
  onMarkChart,
  chartRevision = 0,
  runFile = null,
  onRan,
}: Props) {
  const [marked, setMarked] = useState<number | null>(null)
  /** What the trader typed into an input box, by key. Only what they changed. */
  const [edited, setEdited] = useState<Record<string, string>>({})
  /**
   * Whether the settings section is open.
   *
   * It opens itself for a script that declares inputs, because a collapsed
   * section is indistinguishable from a strategy that has no parameters, and a
   * trader looking for the ones they wrote finds neither them nor a reason.
   * `controlsAreTheirs` records a trader closing it by hand, after which it
   * stays as they left it.
   */
  const [showControls, setShowControls] = useState(false)
  const [controlsAreTheirs, setControlsAreTheirs] = useState(false)
  // Only for the header. The run reads its own, fresh, at the moment it starts.
  const [target, setTarget] = useState<RunTarget | null>(null)
  const [scripts, setScripts] = useState<StoredScript[]>([])
  const [file, setFile] = useState<string>('')
  const [from, setFrom] = useState(() => isoDaysAgo(DEFAULT_DAYS))
  const [to, setTo] = useState(() => today())
  /**
   * Whether the trader has set the dates themselves.
   *
   * Once they have, the range stops following the interval. Somebody who typed
   * a range meant it, and rewriting it underneath them on the next timeframe
   * change would be this panel overruling a decision they made on purpose.
   */
  const [datesAreTheirs, setDatesAreTheirs] = useState(false)
  const [running, setRunning] = useState(false)
  const [outcome, setOutcome] = useState<BacktestOutcome | null>(null)
  const inflight = useRef<AbortController | null>(null)
  /** The strategy and instrument the automatic run last covered. See below. */
  const ranAutomatically = useRef('')

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

  // **The chart is not a React value, so the page says when it has changed.**
  // It is a library holding its own state and there is nothing here to depend
  // on, which is why this used to be read on a one second timer: a question
  // asked constantly and answered differently a few times a day.
  //
  // `chartRevision` is bumped by the page when the focused pane, its instrument
  // or its timeframe changes, which is the whole of what this reads. The run
  // does not rely on any of it: it reads its own, fresh, at the moment it
  // starts.
  // biome-ignore lint/correctness/useExhaustiveDependencies: the revision is the signal to re-read, not a value read here
  useEffect(() => {
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
  }, [getChartContext, chartRevision])

  useEffect(() => () => inflight.current?.abort(), [])

  // -- the range follows the timeframe --------------------------------------
  //
  // **A range that is right for one interval is wrong for another.** Two months
  // of one minute bars is forty sessions of trading; two months of daily bars is
  // forty bars, which answers nothing. So the default reaches back by interval
  // rather than by a single number: months on an intraday frame, years on a
  // daily one. `backtestLookbackDays` holds the rule and the bar counts it rests
  // on.
  //
  // It is also what keeps an ordinary run cheap. A run starts on its own
  // whenever the instrument or the interval changes, so the default range is
  // paid on every symbol switch: a year of one minute bars would be tens of
  // megabytes fetched and seconds of folding, each time.
  //
  // Only while the dates are still this panel's. See `datesAreTheirs`.
  const interval = target?.interval ?? ''
  useEffect(() => {
    if (!interval || datesAreTheirs) return
    setFrom(isoDaysAgo(backtestLookbackDays(interval)))
    setTo(today())
  }, [interval, datesAreTheirs])

  // A file handed over from another panel: select it. The run follows from the
  // selection, below, rather than being started here as well, because two paths
  // that both start a run are two paths that both start the same run.
  //
  // Kept as an effect on the prop rather than a method, because the panel may
  // not be mounted at the moment the button is pressed and the request has to
  // survive until it is.
  //
  // The request is `runFile` and only `runFile`: `onRan` is rebuilt by its
  // owner, and listing it would re-select the handed-over strategy over a
  // choice the trader had since made.
  // biome-ignore lint/correctness/useExhaustiveDependencies: runFile is the request; the rest would re-fire it
  useEffect(() => {
    if (!runFile) return
    setFile(runFile)
    // Handing over the strategy already selected must still run it: that press
    // is a trader asking for this strategy on this chart, and answering it with
    // nothing because the name matched reads as the button being broken.
    ranAutomatically.current = ''
    onRan?.()
  }, [runFile])

  // Read off the last run's program: what this script takes as inputs, and what
  // it declares about itself. Both are the program's own, so nothing here is a
  // second opinion about a default or a capital.
  // -- the controls, which exist before the first run ----------------------
  //
  // **Read by compiling the chosen script, not by waiting for a report.** These
  // all used to come off the last run's program, so a strategy that had not run
  // yet had no controls at all: the trader picked it, saw an empty panel, and
  // had nothing to change. Worse, a run refused for any reason left the panel
  // permanently bare, which is what a ceiling that was too low did.
  //
  // The run's own program still wins once there is one. It is the program that
  // actually produced the figures on screen, so the settings shown beside them
  // are the settings they were computed under.
  const [chosen, setChosen] = useState<unknown>(null)

  useEffect(() => {
    if (!file) {
      setChosen(null)
      return
    }
    let live = true
    void (async () => {
      try {
        const source = await readScript(file)
        const built = await compileSource(file, source)
        if (!live) return
        setChosen(built.ok && built.program !== undefined ? JSON.parse(built.program) : null)
      } catch {
        // A script that will not compile has no controls to offer, which the
        // run itself reports properly when it is pressed.
        if (live) setChosen(null)
      }
    })()
    return () => {
      live = false
    }
  }, [file])

  const shown = outcome?.program ?? chosen
  const declaredInputs = useMemo(() => inputsOf(shown), [shown])

  useEffect(() => {
    if (controlsAreTheirs) return
    setShowControls(declaredInputs.length > 0)
  }, [declaredInputs, controlsAreTheirs])

  const declarations = useMemo(() => inputsOf(shown), [shown])
  const declared = useMemo(() => declaredOf(shown), [shown])

  // Where the order size comes from, which the language decides and this only
  // reports. See `strategyQuantity.ts`: what the script states, runs.
  const quantity = useMemo(() => quantityOf(shown), [shown])
  const sending = useMemo(() => unitsFor(quantity, edited), [quantity, edited])

  // -- the position the strategy is still in --------------------------------
  //
  // A strategy applied to the chart draws and does not trade, so the question
  // in front of a trader watching one is where it would have them right now.
  // The run already answers it: the trade it never closed. What is added here
  // is the price, which the report cannot know because it ended at the last
  // bar and the instrument has gone on trading since.
  const trades = outcome?.trades as readonly ReportTrade[] | undefined
  const holding = useMemo(() => openPositionOf(trades), [trades])
  const alsoOpen = useMemo(() => Math.max(0, openCountOf(trades) - 1), [trades])

  // The platform's own live price and not a second feed. It already holds the
  // socket, decides when a tick has gone stale, falls back to quotes when the
  // socket is not there and stops work while the tab is hidden. All that is
  // wanted from it is the last price of the instrument this position is in.
  const watching = useMemo<PriceableItem[]>(
    () => (holding && target ? [{ symbol: target.symbol, exchange: target.exchange }] : []),
    [holding, target]
  )
  const { data: quoted, isLive } = useLivePrice(watching, { enabled: watching.length > 0 })
  const livePrice = quoted[0]?.ltp ?? null

  // Valued only against a price that actually arrived. Falling back to the
  // entry would show a profit of exactly zero, which reads as a position that
  // has not moved rather than as one nobody has priced.
  const valued = useMemo(
    () =>
      holding === null || livePrice === null
        ? null
        : markToPrice(holding, livePrice, outcome?.contract?.pointValue ?? 1),
    [holding, livePrice, outcome?.contract?.pointValue]
  )

  const runNamed = useCallback(
    async (which: string) => {
    const chart = getChartContext()
    if (!which || !chart) return

    inflight.current?.abort()
    const controller = new AbortController()
    inflight.current = controller

    setRunning(true)
    setOutcome(null)
    try {
      const source = await readScript(which, controller.signal)
      const result = await runBacktest({
        file: which,
        source,
        symbol: chart.symbol,
        exchange: chart.exchange,
        interval: chart.interval,
        startDate: from,
        endDate: to,
        apiKey,
        inputs: settingsFromForm(declarations, edited),
        signal: controller.signal,
      })
      if (controller.signal.aborted) return
      setOutcome(result)

      // The fills go on the price as soon as they exist. A previous run's marks
      // are replaced rather than added to, and a run that produced none clears
      // them, so what is on the chart is always this run and only this run.
      if (onMarkChart) {
        const marks = result.ok ? chartMarkersFrom(result.markers ?? []) : []
        setMarked(onMarkChart(marks) ? marks.length : null)
      }
    } catch {
      if (!controller.signal.aborted) {
        setOutcome({ ok: false, problem: 'The script could not be read.' })
      }
    } finally {
      if (!controller.signal.aborted) setRunning(false)
    }
    },
    [apiKey, declarations, edited, from, getChartContext, onMarkChart, to]
  )

  const run = useCallback(() => runNamed(file), [file, runNamed])

  // -- the automatic run ----------------------------------------------------
  //
  // **Three things start a run on their own: choosing a strategy, changing the
  // instrument, changing the interval.** Those are the three that change what a
  // run is *of*, so the report on screen would otherwise describe something the
  // chart is no longer showing, which is the one failure here a trader cannot
  // see: the figures are real, they are just about a different instrument.
  //
  // **Nothing else does, and that is deliberate.** A date box and an input box
  // are edits somebody makes several of before they mean any of them, and
  // re-running per keystroke would freeze the workspace answering questions
  // nobody asked, over a range half-typed. Those changes wait for the button.
  //
  // `runNamed` is rebuilt whenever a date or an input changes, so it cannot be a
  // dependency here: listing it would make every keystroke a trigger and undo
  // the paragraph above. It is read through a ref that is kept current by the
  // effect above this one, which runs first because effects run in the order
  // they are declared.
  const latestRun = useRef(runNamed)
  useEffect(() => {
    latestRun.current = runNamed
  }, [runNamed])

  // One string for the three things, so a chart poll that answered the same
  // instrument does not count as a change. The separator is a pipe because a
  // script name, an instrument, an exchange and an interval are each letters,
  // digits and a few punctuation marks that do not include one, so no two
  // different triples can spell the same key. `target` is already only rebuilt
  // when one of them differs, and this is the second guard: a run in flight
  // that was started for exactly this must not be started again beside itself.
  const automatic =
    file && target ? `${file}|${target.symbol}|${target.exchange}|${target.interval}` : ''

  // biome-ignore lint/correctness/useExhaustiveDependencies: the key is the trigger; runNamed is read through a ref on purpose
  useEffect(() => {
    if (!automatic || ranAutomatically.current === automatic) return
    ranAutomatically.current = automatic
    void latestRun.current(file)
  }, [automatic])

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
            onChange={(e) => {
              setFile(e.target.value)
              // The boxes belong to the script that declared them. Carrying
              // them across would set one script's input from another's.
              setEdited({})
            }}
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
              onChange={(e) => {
                setDatesAreTheirs(true)
                setFrom(e.target.value)
              }}
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-[10px] uppercase tracking-wide text-muted-foreground">To</span>
            <input
              type="date"
              className="h-8 rounded border border-border bg-background px-2 text-xs"
              value={to}
              min={from}
              onChange={(e) => {
                setDatesAreTheirs(true)
                setTo(e.target.value)
              }}
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

        {file !== '' && (declarations.length > 0 || declared) && (
          <div className="rounded border border-border">
            <button
              type="button"
              className="flex h-7 w-full items-center px-2 text-[10px] uppercase tracking-wide text-muted-foreground hover:bg-accent/50"
              onClick={() => {
                setControlsAreTheirs(true)
                setShowControls((open) => !open)
              }}
              aria-expanded={showControls}
            >
              Settings
              <span className="ml-auto">{showControls ? 'hide' : 'show'}</span>
            </button>

            {showControls && (
              <div className="flex flex-col gap-2 border-t border-border p-2">
                {declarations.length === 0 ? (
                  <p className="text-[10px] leading-relaxed text-muted-foreground">
                    This script declares no settings, so there is nothing to change here. Its
                    numbers are written into it: to make one adjustable, give it a name with
                    input(), as in length = input(9, "Fast length", min = 1).
                  </p>
                ) : (
                  <StrategyInputs
                    declarations={declarations}
                    edited={edited}
                    onChange={(key, value) => setEdited((held) => ({ ...held, [key]: value }))}
                    note="A box left empty uses the script's own default. Run again to apply a change. These are for testing on this chart only and never reach a strategy that is running live: set those under Strategies."
                  />
                )}

                {declared && (
                  <div className="flex flex-col gap-1">
                    <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
                      Declared by the script
                    </span>
                    <dl className="grid grid-cols-2 gap-x-2 gap-y-0.5 font-mono text-[10px] text-muted-foreground">
                      <dt>Capital</dt>
                      <dd className="text-right">
                        {declared.capital.toLocaleString()} {declared.currency}
                      </dd>
                      <dt>Order size</dt>
                      <dd className="text-right">
                        {sending === null ? `${declared.qty} ${declared.qtyType}` : `${sending} ${declared.qtyType}`}
                        {quantity.kind === 'input' && ' (yours)'}
                      </dd>
                      <dt>Pyramiding</dt>
                      <dd className="text-right">{declared.pyramiding}</dd>
                      <dt>Commission</dt>
                      <dd className="text-right">
                        {declared.commission} {declared.commissionType}
                      </dd>
                      <dt>Slippage</dt>
                      <dd className="text-right">{declared.slippage} ticks</dd>
                      <dt>Fills on</dt>
                      <dd className="text-right">{declared.fillOn}</dd>
                    </dl>
                    <p className="text-[10px] leading-relaxed text-muted-foreground">
                      These are the script's own, set in its `strategy()` line, and are shown
                      rather than offered: a commission supplied here beside a declared one
                      describes the same money twice and is refused before the first bar. Edit
                      the script to change them.
                    </p>
                  </div>
                )}
              </div>
            )}
          </div>
        )}

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

        {/* A run the script stopped part way. It is not a refusal: the run
            happened up to that bar and the figures below are of that part, so
            without this the report reads as the whole range and a strategy that
            failed on its first order reads as one that never traded. */}
        {outcome?.stopped && (
          <div className="flex flex-col gap-1 rounded border border-destructive/40 p-2">
            <span className="text-[11px] font-medium text-destructive">
              {stoppedAt(outcome.stopped, outcome.barCount, outcome.instrument?.timezone)}
            </span>
            {outcome.stopped.title && (
              <span className="text-[11px] leading-relaxed">
                {outcome.stopped.title}.{outcome.stopped.fix ? ` ${outcome.stopped.fix}` : ''}
              </span>
            )}
            <span className="font-mono text-[10px] text-muted-foreground">
              {outcome.stopped.line}:{outcome.stopped.column} {outcome.stopped.code}
            </span>
            <span className="text-[10px] leading-relaxed text-muted-foreground">
              The figures below are of the run up to that bar. Correct the script and run it again
              to test the whole range.
            </span>
          </div>
        )}

        {quantity.kind !== 'unknown' && (
          <p className="rounded border border-border px-2 py-1.5 text-[10px] leading-relaxed text-muted-foreground">
            <span className="font-medium text-foreground">
              Order size {sending === null ? '' : sending}
            </span>
            {' - '}
            {quantityNote(quantity)}
          </p>
        )}

        {holding && (
          <div className="flex flex-col gap-1 rounded border border-border p-2">
            <div className="flex items-baseline gap-1.5">
              <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
                Position now
              </span>
              <span
                className={cn(
                  'ml-auto text-[9px] uppercase tracking-wide',
                  isLive && livePrice !== null ? 'text-emerald-500' : 'text-muted-foreground'
                )}
              >
                {livePrice === null ? 'No price yet' : isLive ? 'Live' : 'Last known'}
              </span>
            </div>

            <div className="flex items-baseline gap-2 font-mono text-[12px] tabular-nums">
              <span className={holding.side === 'short' ? 'text-destructive' : 'text-emerald-500'}>
                {holding.side === 'short' ? 'Short' : 'Long'} {holding.units}
              </span>
              <span className="text-muted-foreground">at {holding.entryPrice.toFixed(2)}</span>
              {valued && (
                <span
                  className={cn(
                    'ml-auto',
                    valued.profit >= 0 ? 'text-emerald-500' : 'text-destructive'
                  )}
                >
                  {money(valued.profit)}
                  {valued.profitPercent !== null && ` (${percent(valued.profitPercent)})`}
                </span>
              )}
            </div>

            <p className="text-[10px] leading-relaxed text-muted-foreground">
              {valued
                ? `Marked at ${valued.price.toFixed(2)}. `
                : 'No price has arrived for this instrument yet, so it is not valued. '}
              {alsoOpen > 0 && `${alsoOpen} more open ${alsoOpen === 1 ? 'trade' : 'trades'}. `}
              This strategy is on the chart, which draws and does not trade. Nothing is held at
              your broker because of it. Add it under Strategies to trade it.
            </p>
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
              {/* Shown only when the engine reports it. The run-up is a newer
                  figure than the pinned engine computes, so on that engine this
                  tile was a dash on every run: an empty box beside real numbers
                  reads as data that failed to arrive rather than as a figure
                  this version does not have. Rendering it conditionally means it
                  appears on its own the day the engine supplies it. */}
              {summary.maxRunUp !== undefined && summary.maxRunUp !== null && (
                <Figure label="Max run-up" value={money(summary.maxRunUp)} tone="good" />
              )}
            </div>

            <BacktestChart points={outcome?.equity ?? []} />

            <p className="text-[10px] text-muted-foreground">
              {marked !== null && marked > 0
                ? `${marked} fills marked on the chart. `
                : marked === null && onMarkChart
                  ? 'The chart has no price series to mark yet. '
                  : ''}
              {outcome?.barCount?.toLocaleString()} bars, {Math.round(outcome?.ranMs ?? 0)}ms
              {outcome?.contract?.usedFallback
                ? '. This instrument has no stored tick or lot size, so the run used a tick of ' +
                  `${outcome.contract.tickSize} and a lot of ${outcome.contract.lotSize}. Every figure in money rests on those.`
                : `. Tick ${outcome?.contract?.tickSize}, lot ${outcome?.contract?.lotSize}.`}
              {/* Said because the absence is otherwise invisible: a session
                  strategy with no hours to read never trades, and its report
                  looks like a strategy that found nothing to do. */}
              {outcome?.instrument && !outcome.instrument.session
                ? ' No trading hours were available for this instrument, so everything the script reads from its session was empty in this run.'
                : ''}
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
