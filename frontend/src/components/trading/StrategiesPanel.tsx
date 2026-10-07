/**
 * The strategies this server is deployed to run, and what each of them is doing.
 *
 * **A row is a deployment and not a file.** One strategy is deployed on several
 * instruments, and on one instrument at several timeframes, all at once: each
 * has its own position, its own book, its own log and its own decision to stop.
 * The list used to be one row per file, so deploying a strategy a second time
 * silently replaced the first and the two shared a book. A trader looking at a
 * run on a commodity future saw the stock orders the same file had placed that
 * morning, with nothing to say which position they were reading.
 *
 * Every row here is a process on the server, not a thing in this tab. A run
 * outlives the page: closing the browser stops nothing, and this panel is a
 * view of what is already happening rather than the thing making it happen.
 * That is the whole reason live execution is server side.
 *
 * **It is modelled on the alerts panel and differs in one place on purpose.**
 * An alert that misfires costs a notification; a strategy that misfires costs a
 * position. So a row shows what an alert row does not: what the run is trading,
 * since when, and a stop that is always reachable. A run is never represented
 * by a spinner alone, because a trader looking at this panel is asking whether
 * something is holding a position, and "working on it" is not an answer to that.
 *
 * **Where the orders go is stated, not implied.** A run sends through the
 * platform's own order path, so it trades live while the platform is live and
 * sandbox while it is in analyzer mode. That is the intended behaviour and it
 * is also the thing a trader must not have to infer: the same button, pressed
 * on the same strategy, either simulates or spends money depending on a setting
 * made somewhere else on the site. So the mode is on the header, and the start
 * button says which destination it is about to use.
 *
 * **Refusals are shown in the server's own words.** The runner refuses a start
 * for reasons a trader can act on, naming the script and what is missing.
 * Rewording them here would lose the part that says what to do.
 */

import { Trash2 } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  clearSettings,
  closeStrategy,
  overview,
  pauseStrategy,
  type RunningStrategy,
  type RunSettings,
  saveSettings,
  startStrategy,
  strategyPositions,
} from '@/api/openscriptRunner'
import { type PriceableItem, useLivePrice } from '@/hooks/useLivePrice'
import { useOrderEventRefresh } from '@/hooks/useOrderEventRefresh'
import { type InputDeclaration, inputsOf, settingsFromForm } from '@/lib/trading/backtestInputs'
import { deploymentsOf, matches } from '@/lib/trading/deployments'
import { compileSource, kindOf, listScripts, readScript } from '@/lib/trading/openscriptFiles'
import { type PositionSummary, summaryOf } from '@/lib/trading/strategyPosition'
import { quantityNote, quantityOf } from '@/lib/trading/strategyQuantity'
import { cn } from '@/lib/utils'
import { useThemeStore } from '@/stores/themeStore'
import { ConfirmStop } from './ConfirmStop'
import { InstrumentPicker } from './InstrumentPicker'
import { PANEL_HEADER, PanelShell } from './panelShell'
import { StrategyBooks } from './StrategyBooks'
import { StrategyInputs } from './StrategyInputs'

interface Props {
  /** The chart, for filling new settings from what the trader is looking at. */
  getChartContext(): { symbol: string; exchange: string; interval: string } | null
}

/**
 * How often the list is refreshed.
 *
 * **It is a safety net and not the mechanism.** What a trader watches, the
 * position and the books, arrives on the platform's own order events: an order
 * moving is the only thing that changes either, and every surface that places
 * one broadcasts it. This sweep exists for the one thing no event covers, a
 * child that ended on its own, on a diagnostic or a refused order or the
 * destination changing underneath it. Nothing pushes that to the browser.
 *
 * So it is slow on purpose. Fifteen seconds is well inside the time it takes to
 * wonder whether something is still running, and it costs one small request in
 * between events that are already doing the work.
 */
const REFRESH_MS = 15000

function since(started: string | null): string {
  if (!started) return ''
  const at = Date.parse(started)
  if (!Number.isFinite(at)) return started
  const mins = Math.max(0, Math.round((Date.now() - at) / 60000))
  if (mins < 60) return `${mins}m`
  const hours = Math.floor(mins / 60)
  return `${hours}h ${mins % 60}m`
}

/** Money, as a trader reads it. Two places, and a sign that is always shown. */
function money(value: number): string {
  const shown = Math.abs(value).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })
  return `${value < 0 ? '-' : '+'}${shown}`
}

/**
 * What one running strategy is holding, on its row.
 *
 * **It is always rendered for a running strategy, including when flat.** A row
 * that shows a position only when there is one leaves a trader unable to tell
 * "this strategy is flat" from "this panel has not told me yet", and those two
 * want opposite reactions. Flat is stated.
 *
 * **What is shown is the platform's own answer, not a calculation.** The
 * strategy sent orders, they filled, and the platform folds them into a
 * position with a profit attached. A panel that worked one out from the order
 * list would be a second opinion about money.
 *
 * The profit is the platform's total where it gave one, which counts profit
 * already taken on a position that has since been closed. That is why it can be
 * a number beside no open position at all, and why the note says so rather than
 * leaving a reader to think the two disagree.
 */
function Holding({
  summary,
  live,
  isLive,
}: {
  summary: PositionSummary | null | undefined
  /** The live figure per instrument, by `symbol|exchange`. */
  live: Record<string, { profit: number | null; price: number | null }>
  isLive: boolean
}) {
  if (summary === undefined) {
    return <div className="text-[10px] text-muted-foreground">Reading what it holds...</div>
  }
  if (summary === null) {
    // Said rather than left blank. A silent row is read as flat.
    return (
      <div className="text-[10px] text-muted-foreground">
        What this is holding could not be read just now.
      </div>
    )
  }

  const { positions, profit, profitIsPlatforms } = summary

  return (
    <div className="flex flex-col gap-0.5">
      {positions.length === 0 ? (
        <div className="flex items-baseline gap-1.5 text-[10px]">
          <span className="text-muted-foreground">Flat</span>
          {profit !== null && profit !== 0 && (
            <span
              className={cn(
                'ml-auto font-mono tabular-nums',
                profit >= 0 ? 'text-emerald-500' : 'text-destructive'
              )}
            >
              {money(profit)}
            </span>
          )}
        </div>
      ) : (
        positions.map((one) => {
          // **The live figure where there is one, the platform's otherwise.**
          // The size and the average came from the server and do not move
          // between orders; what a position is worth moves on every tick, and
          // that is the number being watched.
          const marked = live[`${one.symbol}|${one.exchange}`]
          const profit = marked?.profit ?? one.profit
          return (
            <div
              key={`${one.symbol}-${one.exchange}`}
              className="flex items-baseline gap-1.5 font-mono text-[10px] tabular-nums"
            >
              <span className={one.side === 'short' ? 'text-destructive' : 'text-emerald-500'}>
                {one.side === 'short' ? 'SHORT' : 'LONG'} {one.quantity}
              </span>
              <span className="truncate text-muted-foreground">{one.symbol}</span>
              {one.averagePrice !== null && (
                <span className="text-muted-foreground">@{one.averagePrice.toFixed(2)}</span>
              )}
              {profit !== null && (
                <span
                  className={cn('ml-auto', profit >= 0 ? 'text-emerald-500' : 'text-destructive')}
                >
                  {money(profit)}
                </span>
              )}
            </div>
          )
        })
      )}

      {profitIsPlatforms && positions.length === 0 && profit !== null && profit !== 0 && (
        <span className="text-[9px] leading-tight text-muted-foreground">
          Taken on positions this strategy has already closed today.
        </span>
      )}

      {/* **Said when it is not live, not when it is.** A figure that is moving
          needs no label; one that has stopped looks exactly the same and is the
          one a trader would act on believing it current. */}
      {positions.length > 0 && !isLive && (
        <span className="text-[9px] leading-tight text-muted-foreground">
          Not marked to a live price just now: this is what the platform last said, and it moves
          again when prices arrive.
        </span>
      )}
    </div>
  )
}

/**
 * The instrument, the interval, the product and the script's own parameters.
 *
 * One component, used by the form that creates a deployment and by the form
 * that edits one. Two copies would be two places a field could be added, and
 * the one nobody remembered would be the one a trader could not set.
 */
function DeploymentForm({
  draft,
  setDraft,
  declarations,
  typed,
  setTyped,
  sizeNote,
  onSave,
  onCancel,
  onRemove,
  busy,
  saveLabel,
}: {
  draft: RunSettings
  setDraft(next: RunSettings): void
  declarations: InputDeclaration[]
  typed: Record<string, string>
  setTyped(next: (held: Record<string, string>) => Record<string, string>): void
  sizeNote: string
  onSave(): void
  onCancel(): void
  onRemove: (() => void) | null
  busy: boolean
  saveLabel: string
}) {
  const ready = Boolean(
    draft.file && draft.symbol.trim() && draft.exchange.trim() && draft.interval.trim()
  )
  return (
    <>
      <InstrumentPicker
        symbol={draft.symbol}
        exchange={draft.exchange}
        interval={draft.interval}
        product={draft.product}
        onChange={(next) => setDraft({ ...draft, ...next })}
      />

      <StrategyInputs
        declarations={declarations}
        edited={typed}
        onChange={(key, value) => setTyped((held) => ({ ...held, [key]: value }))}
        note="A box left empty uses the script's own default. A running strategy reads these when it starts, so stop it and start it again to apply a change."
      />

      {sizeNote && <p className="text-[10px] leading-relaxed text-muted-foreground">{sizeNote}</p>}

      <p className="text-[10px] leading-relaxed text-muted-foreground">
        The instrument and the interval are part of what this deployment is. Changing either one
        makes a second deployment rather than moving this one, so the strategy you are already
        running is left exactly where it is.
      </p>

      <div className="flex gap-1.5">
        <button
          type="button"
          className="h-7 flex-1 rounded border border-border text-[11px] hover:bg-accent disabled:opacity-50"
          disabled={busy || !ready}
          title={ready ? undefined : 'An instrument, an exchange and an interval are needed'}
          onClick={onSave}
        >
          {saveLabel}
        </button>
        <button
          type="button"
          className="h-7 rounded border border-border px-2 text-[11px] hover:bg-accent"
          onClick={onCancel}
        >
          Cancel
        </button>
        {onRemove && (
          <button
            type="button"
            className="h-7 rounded border border-border px-2 text-[11px] text-muted-foreground hover:border-destructive/50 hover:text-destructive"
            onClick={onRemove}
          >
            Remove
          </button>
        )}
      </div>
    </>
  )
}

/**
 * The sentinel `editing` holds while a deployment is being created.
 *
 * Not a deployment id and never mistakable for one: a server id begins with a
 * letter or a digit, so nothing it mints can collide with this.
 */
const NEW = '+new'

export function StrategiesPanel({ getChartContext }: Props) {
  const appMode = useThemeStore((state) => state.appMode)
  const isLive = appMode === 'live'
  const [running, setRunning] = useState<RunningStrategy[]>([])
  const [settings, setSettings] = useState<RunSettings[]>([])
  const [strategies, setStrategies] = useState<string[]>([])
  const [problem, setProblem] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [editing, setEditing] = useState<string | null>(null)
  const [draft, setDraft] = useState<RunSettings | null>(null)
  /**
   * What the script being edited declares, and what the trader has typed.
   *
   * Read by compiling the script when the editor opens, because the
   * declarations are the script's own and nothing else on the server knows
   * them. `typed` holds text rather than values: a form field holds text
   * whatever it declares, and turning it into a value is the one job
   * `settingsFromForm` has.
   */
  const [declarations, setDeclarations] = useState<InputDeclaration[]>([])
  const [typed, setTyped] = useState<Record<string, string>>({})
  const [sizeNote, setSizeNote] = useState('')
  const [unreachable, setUnreachable] = useState(false)
  /**
   * Which deployment has been asked to stop and is waiting to be confirmed.
   *
   * Stop closes a position, which spends a spread and cannot be taken back, so
   * it is never one press. Pause costs nothing and is one press, which is the
   * right way round: the button that is safe is the quick one.
   */
  const [confirming, setConfirming] = useState<string | null>(null)
  /**
   * Which deployment is being removed, and is waiting to be confirmed.
   *
   * Removing costs nothing that cannot be done again: the strategy stays in the
   * editor and its trades stay in the books. It is asked about anyway, because
   * a deployment is a instrument, an interval and a set of parameters somebody
   * chose, and re-entering them is a nuisance nobody should meet by misclick.
   */
  const [removing, setRemoving] = useState<string | null>(null)
  /** Which strategy's books are open. One at a time: a panel of open tables is unreadable. */
  const [opened, setOpened] = useState<string | null>(null)
  /** Bumped when a run starts or stops, so an open book refetches rather than going stale. */
  const [revision, setRevision] = useState(0)
  const [search, setSearch] = useState('')
  /** What each running strategy is holding, by file. Refreshed with the list. */
  const [holdings, setHoldings] = useState<Record<string, PositionSummary | null>>({})
  const live = useRef(true)

  const refresh = useCallback(async (signal?: AbortSignal) => {
    let found: Awaited<ReturnType<typeof overview>>
    try {
      found = await overview(signal)
      if (!live.current) return
      setRunning(found.running)
      setSettings(found.settings)
      setUnreachable(false)
    } catch {
      // Shown rather than swallowed: a panel that silently stops refreshing
      // reads as "nothing is running", which is the one wrong answer here.
      if (live.current) setUnreachable(true)
      return
    }

    // -- what each running strategy is holding ------------------------------
    //
    // **Asked for only where something is running.** A stopped strategy holds
    // nothing this could report, and a trader may have hundreds saved: one
    // request per saved strategy every few seconds would be a panel that costs
    // more than it tells anybody.
    //
    // **On the same timer as the list, deliberately.** The position and the run
    // it belongs to are read together, so a row never shows a live position
    // beside a strategy the same refresh has just found stopped.
    //
    // Each is asked for on its own and a failure is that strategy's alone: one
    // instrument the broker will not answer about must not blank the positions
    // of every other strategy on the page.
    const holdings = await Promise.all(
      found.running.map(async (run) => {
        // By the deployment, because that is what an order carries and what
        // the position book is filtered on. Asked for by file, two deployments
        // of one script would each be shown the sum of both positions.
        const id = run.deployment || run.id
        try {
          const answered = await strategyPositions(id, signal)
          return [id, summaryOf(answered.raw)] as const
        } catch {
          return [id, null] as const
        }
      })
    )
    if (!live.current) return
    setHoldings(Object.fromEntries(holdings))
  }, [])

  useEffect(() => {
    live.current = true
    const controller = new AbortController()
    void refresh(controller.signal)
    const timer = window.setInterval(() => void refresh(), REFRESH_MS)
    return () => {
      live.current = false
      controller.abort()
      window.clearInterval(timer)
    }
  }, [refresh])

  // **An order moving is what changes a position, so that is what reads it
  // again.** The timer above still runs and is deliberately slow: it is not how
  // a position reaches this panel, it is the only thing that notices a run that
  // stopped without being asked to. A child can end on its own, on a diagnostic
  // or a refused order, and nothing tells the browser when it does. Between
  // those two, everything a trader watches arrives on the event and the sweep
  // is a safety net rather than the mechanism.
  useOrderEventRefresh(
    useCallback(() => {
      void refresh()
    }, [refresh]),
    {
      events: [
        'order_event',
        'close_position_event',
        'cancel_order_event',
        'modify_order_event',
        // Where orders go decides which book a position is read from, so a
        // change of destination is a change to what this panel is showing.
        'analyzer_update',
      ],
    }
  )

  // -- marking what is held to the price it is trading at -------------------
  //
  // **The size and the average are the server's; the profit moves with the
  // price.** An order event says when a position changed, and between those
  // events nothing about the position changes except what it is worth, which
  // moves on every tick. Refreshing on orders alone leaves a profit figure that
  // is right at the moment of a fill and stale for every minute after it, which
  // on the number a trader is watching is the wrong half to be exact about.
  //
  // The same hook the positions page and the dock use, so this panel's figure
  // and theirs are one calculation rather than two that drift. One list across
  // every strategy, because the subscription is per instrument and two
  // strategies on one symbol should not be two of them.
  const watching = useMemo<(PriceableItem & { file: string })[]>(() => {
    const out: (PriceableItem & { file: string })[] = []
    for (const [file, summary] of Object.entries(holdings)) {
      for (const one of summary?.positions ?? []) {
        out.push({
          file,
          symbol: one.symbol,
          exchange: one.exchange,
          // Signed, because the hook reads the direction off the sign and a
          // short handed over positive is marked as though it were long: the
          // profit then moves the wrong way on every tick.
          quantity: one.side === 'short' ? -one.quantity : one.quantity,
          average_price: one.averagePrice ?? 0,
          pnl: one.profit ?? 0,
        })
      }
    }
    return out
  }, [holdings])

  const { data: priced, isLive: pricesAreLive } = useLivePrice(watching, {
    enabled: watching.length > 0,
  })

  /** The live figure for one strategy's instrument, by file and instrument. */
  const marked = useMemo(() => {
    const out: Record<string, { profit: number | null; price: number | null }> = {}
    for (const one of priced) {
      const key = `${(one as { file: string }).file}|${one.symbol}|${one.exchange}`
      out[key] = { profit: one.pnl ?? null, price: one.ltp ?? null }
    }
    return out
  }, [priced])

  // Only strategies can be run, so only strategies are listed.
  useEffect(() => {
    const controller = new AbortController()
    void (async () => {
      try {
        const found = await listScripts(controller.signal)
        const names: string[] = []
        for (const one of found) {
          const source = await readScript(one.file, controller.signal)
          if ((await kindOf(source)) === 'strategy') names.push(one.file)
        }
        if (live.current) setStrategies(names)
      } catch {
        if (live.current) setStrategies([])
      }
    })()
    return () => controller.abort()
  }, [])

  /** Every deployment, running first. See `deployments`, where it is tested. */
  const deployments = useMemo(() => deploymentsOf(settings, running), [settings, running])

  const act = useCallback(
    async (file: string, what: () => Promise<unknown>) => {
      setBusy(file)
      setProblem(null)
      try {
        await what()
        await refresh()
        setRevision((n) => n + 1)
      } catch (error) {
        setProblem(error instanceof Error ? error.message : String(error))
      } finally {
        setBusy(null)
      }
    },
    [refresh]
  )

  /**
   * Open the form, on an existing deployment or on a new one.
   *
   * `at` is a deployment id, or `NEW` for one being created. A new one starts
   * on the chart's own instrument and on the first strategy saved, because a
   * trader deploying a strategy is almost always looking at the instrument they
   * mean and typing the whole of it again is the part they would not thank
   * anybody for.
   */
  const openEditor = useCallback(
    (at: string, file?: string) => {
      const held = at === NEW ? null : (settings.find((one) => one.deployment === at) ?? null)
      const script = held?.file ?? file ?? ''
      const chart = getChartContext()
      setEditing(at)
      setDraft(
        held ?? {
          file: script,
          // Filled from the chart, because a trader configuring a strategy is
          // almost always looking at the instrument they mean.
          symbol: chart?.symbol ?? '',
          exchange: chart?.exchange ?? '',
          interval: chart?.interval ?? '',
          product: 'MIS',
        }
      )

      // The boxes start from what is saved, so opening the editor shows what
      // this strategy will actually run on rather than an empty form beside a
      // strategy that is already tuned. Text, because that is what a field
      // holds; the values go back through the same reader either panel uses.
      setTyped(
        Object.fromEntries(
          Object.entries(held?.inputs ?? {}).map(([key, value]) => [key, String(value)])
        )
      )

      // Compiled here because the declarations are the script's own and the
      // server stores only the values. A script that will not compile has no
      // declarations to show, which is the honest answer: there is nothing to
      // set until it does, and the editor where it is fixed says why.
      setDeclarations([])
      setSizeNote('')
      void (async () => {
        try {
          const source = await readScript(script)
          const built = await compileSource(script, source)
          if (!built.ok || built.program === undefined) return
          const program = JSON.parse(built.program)
          setDeclarations(inputsOf(program))
          setSizeNote(quantityNote(quantityOf(program)))
        } catch {
          // Left empty. A strategy whose parameters could not be read is still
          // one a trader may want to point at an instrument and start, and
          // taking the whole editor down over the parameters would stop that.
        }
      })()
    },
    [getChartContext, settings]
  )

  return (
    <PanelShell
      id="trading-strategies-panel"
      label="Strategies"
      storageKey="trading.panel.strategies.width"
      defaultWidth={400}
      minWidth={320}
    >
      <div className={PANEL_HEADER}>
        <span className="text-xs font-medium">Strategies</span>
        <span
          className={cn(
            'ml-auto shrink-0 rounded px-1.5 py-px text-[10px] font-medium uppercase tracking-wide',
            isLive
              ? 'bg-destructive/15 text-destructive'
              : 'bg-amber-500/15 text-amber-600 dark:text-amber-400'
          )}
          title={
            isLive
              ? 'Orders from a running strategy go to your broker'
              : 'Orders from a running strategy go to the sandbox'
          }
        >
          {isLive ? 'Live' : 'Analyzer'}
        </span>
        <span className="shrink-0 text-[11px] text-muted-foreground">{running.length} running</span>
      </div>

      <div className="flex items-center gap-1.5 border-b border-border px-2 py-1.5">
        <button
          type="button"
          className="h-7 rounded border border-border bg-accent/40 px-2 text-[11px] hover:bg-accent disabled:opacity-50"
          disabled={strategies.length === 0}
          title={
            strategies.length === 0
              ? 'Save a strategy first. A study plots and places no orders.'
              : 'Run a strategy on an instrument'
          }
          onClick={() => (editing === NEW ? setEditing(null) : openEditor(NEW, strategies[0]))}
        >
          {editing === NEW ? 'Cancel' : 'Deploy a strategy'}
        </button>
        <span className="text-[10px] text-muted-foreground">
          {deployments.length === 1 ? '1 deployment' : `${deployments.length} deployments`}
        </span>
      </div>

      {editing === NEW && draft && (
        <div className="flex flex-col gap-1.5 border-b border-border bg-muted/40 p-2">
          <label className="text-[10px] font-medium text-muted-foreground" htmlFor="deploy-script">
            Strategy
          </label>
          <select
            id="deploy-script"
            className="h-7 rounded border border-border bg-background px-1.5 text-[11px]"
            value={draft.file}
            onChange={(e) => openEditor(NEW, e.target.value)}
          >
            {strategies.map((one) => (
              <option key={one} value={one}>
                {one}
              </option>
            ))}
          </select>
          <DeploymentForm
            draft={draft}
            setDraft={setDraft}
            declarations={declarations}
            typed={typed}
            setTyped={setTyped}
            sizeNote={sizeNote}
            onSave={() =>
              void act(NEW, async () => {
                await saveSettings({ ...draft, inputs: settingsFromForm(declarations, typed) })
                setEditing(null)
              })
            }
            onCancel={() => setEditing(null)}
            onRemove={null}
            busy={busy === NEW}
            saveLabel="Deploy"
          />
        </div>
      )}

      <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto p-2">
        {unreachable && (
          <p className="rounded border border-amber-500/40 px-2 py-1.5 text-[11px] text-amber-600 dark:text-amber-400">
            The runner cannot be reached, so this list may be out of date. Anything already running
            on the server is still running.
          </p>
        )}

        {problem && (
          <p className="rounded border border-destructive/40 px-2 py-1.5 text-[11px] text-destructive">
            {problem}
          </p>
        )}

        {deployments.length > 6 && (
          <input
            type="search"
            className="h-7 rounded border border-border bg-background px-2 text-[11px]"
            placeholder="Search by strategy or instrument"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        )}

        {strategies.length === 0 && (
          <p className="text-[11px] text-muted-foreground">
            No strategies saved. A study plots and places no orders, so only a script that declares
            itself a strategy can be run.
          </p>
        )}

        {strategies.length > 0 && deployments.length === 0 && (
          <p className="text-[11px] text-muted-foreground">
            Nothing deployed yet. Deploy a strategy on an instrument to run it. The same strategy
            can be deployed on as many instruments and timeframes as you like, and each one runs,
            holds and reports on its own.
          </p>
        )}

        {deployments
          .filter((one) => matches(one, search))
          .map((one) => {
            const file = one.id
            const run = one.run
            const held = one.settings
            const where = run ?? held
            const holding = holdings[one.id]
            const isEditing = editing === one.id

            return (
              <div key={one.id} className="flex flex-col gap-1.5 rounded border border-border p-2">
                <div className="flex items-center gap-1.5">
                  <span
                    className={cn(
                      'h-1.5 w-1.5 shrink-0 rounded-full',
                      run ? 'bg-emerald-500' : 'bg-muted-foreground/40'
                    )}
                    aria-hidden
                  />
                  <span className="truncate text-xs font-medium" title={one.file}>
                    {one.file}
                  </span>
                  <span className="ml-auto shrink-0 text-[10px] text-muted-foreground">
                    {run ? `running ${since(run.started_at)}` : 'stopped'}
                  </span>
                </div>

                <div className="font-mono text-[10px] text-muted-foreground">
                  {run
                    ? `${run.symbol} ${run.exchange} ${run.interval} ${run.product} · pid ${run.pid}`
                    : held
                      ? `${held.symbol} ${held.exchange} ${held.interval} ${held.product}`
                      : 'No instrument set. Set one before this can start.'}
                </div>

                {run && (
                  <Holding
                    summary={holding}
                    live={Object.fromEntries(
                      Object.entries(marked)
                        .filter(([key]) => key.startsWith(`${file}|`))
                        .map(([key, value]) => [key.slice(file.length + 1), value])
                    )}
                    isLive={pricesAreLive}
                  />
                )}

                {isEditing && draft && (
                  <div className="flex flex-col gap-1.5 rounded bg-muted/40 p-1.5">
                    <DeploymentForm
                      draft={draft}
                      setDraft={setDraft}
                      declarations={declarations}
                      typed={typed}
                      setTyped={setTyped}
                      sizeNote={sizeNote}
                      onSave={() =>
                        void act(one.id, async () => {
                          // The same reader the backtest panel uses, so a value
                          // this accepts is one that panel accepted: a strategy
                          // must not trade live on a number its own backtest
                          // would have refused.
                          await saveSettings({
                            ...draft,
                            inputs: settingsFromForm(declarations, typed),
                          })
                          setEditing(null)
                        })
                      }
                      onCancel={() => setEditing(null)}
                      onRemove={
                        held
                          ? () =>
                              void act(one.id, async () => {
                                await clearSettings(one.id)
                                setEditing(null)
                              })
                          : null
                      }
                      busy={busy === one.id}
                      saveLabel="Save"
                    />
                  </div>
                )}

                <div className="flex gap-1.5">
                  {run ? (
                    <>
                      <button
                        type="button"
                        className="h-7 flex-1 rounded border border-border text-[11px] hover:bg-accent disabled:opacity-50"
                        disabled={busy === file}
                        title="End this strategy and leave its position exactly where it is"
                        onClick={() => void act(file, () => pauseStrategy(file))}
                      >
                        {busy === file ? 'Working' : 'Pause'}
                      </button>
                      <button
                        type="button"
                        className="h-7 flex-1 rounded border border-border text-[11px] hover:border-destructive/50 hover:text-destructive disabled:opacity-50"
                        disabled={busy === file}
                        title="Close what this strategy is holding, then end it"
                        onClick={() => setConfirming(one.id)}
                      >
                        Stop
                      </button>
                    </>
                  ) : (
                    <button
                      type="button"
                      className="h-7 flex-1 rounded border border-border bg-accent/40 text-[11px] hover:bg-accent disabled:opacity-50"
                      disabled={busy === file || !held}
                      title={held ? undefined : 'Set an instrument first'}
                      onClick={() => void act(file, () => startStrategy(file))}
                    >
                      {busy === file ? 'Starting' : isLive ? 'Start live' : 'Start in sandbox'}
                    </button>
                  )}
                  <button
                    type="button"
                    className="h-7 rounded border border-border px-2 text-[11px] text-muted-foreground hover:bg-accent hover:text-foreground"
                    onClick={() => (isEditing ? setEditing(null) : openEditor(file))}
                  >
                    Settings
                  </button>
                  <button
                    type="button"
                    className="h-7 rounded border border-border px-2 text-[11px] text-muted-foreground hover:bg-accent hover:text-foreground"
                    aria-expanded={opened === file}
                    onClick={() => setOpened((held) => (held === file ? null : file))}
                  >
                    {opened === file ? 'Hide' : 'Activity'}
                  </button>
                  {held && (
                    <button
                      type="button"
                      aria-label={`Remove ${one.file} on ${where?.symbol ?? ''}`}
                      className="h-7 rounded border border-border px-2 text-[11px] text-muted-foreground hover:border-destructive/50 hover:text-destructive disabled:opacity-40"
                      disabled={Boolean(run)}
                      title={
                        run
                          ? 'Pause or stop this strategy before removing it'
                          : 'Remove this deployment'
                      }
                      onClick={() => setRemoving(one.id)}
                    >
                      <Trash2 className="h-3 w-3" aria-hidden />
                    </button>
                  )}
                </div>

                {removing === one.id && (
                  <div className="flex flex-col gap-1.5 rounded border border-border p-2">
                    <p className="text-[11px] leading-relaxed">
                      Remove {one.file} on{' '}
                      {[where?.symbol, where?.exchange, where?.interval].filter(Boolean).join(' ')}?
                    </p>
                    <p className="text-[10px] leading-relaxed text-muted-foreground">
                      This removes the deployment and its schedule. The strategy itself is not
                      deleted: it stays in the editor and can be deployed again. Anything it has
                      already traded stays in your books.
                    </p>
                    <div className="flex gap-1.5">
                      <button
                        type="button"
                        className="h-7 flex-1 rounded border border-destructive/60 text-[11px] text-destructive hover:bg-destructive/10 disabled:opacity-50"
                        disabled={busy === file}
                        onClick={() =>
                          void act(file, async () => {
                            await clearSettings(file)
                            setRemoving(null)
                          })
                        }
                      >
                        {busy === file ? 'Removing' : 'Remove'}
                      </button>
                      <button
                        type="button"
                        className="h-7 rounded border border-border px-2 text-[11px] hover:bg-accent"
                        onClick={() => setRemoving(null)}
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                )}

                {confirming === one.id && (
                  <ConfirmStop
                    file={one.file}
                    where={[where?.symbol, where?.exchange, where?.interval]
                      .filter(Boolean)
                      .join(' ')}
                    holding={holding}
                    busy={busy === file}
                    onCancel={() => setConfirming(null)}
                    onPause={() =>
                      void act(file, async () => {
                        await pauseStrategy(file)
                        setConfirming(null)
                      })
                    }
                    onStop={() =>
                      void act(file, async () => {
                        await closeStrategy(file)
                        setConfirming(null)
                      })
                    }
                  />
                )}

                {opened === one.id && <StrategyBooks deployment={one.id} revision={revision} />}
              </div>
            )
          })}

        <p className="mt-auto text-[10px] leading-relaxed text-muted-foreground">
          Pause ends a strategy and leaves its position for you to manage. Stop closes what it is
          holding first, which spends a spread and cannot be taken back, so it asks before it does.
          A run is a process on the server and outlives this page: closing the browser stops
          nothing. Orders go through this platform's own order path, so a run trades with your
          broker while the platform is in live mode and against the sandbox while it is in analyzer
          mode, the same as every other surface here. That setting is made elsewhere on the site and
          is shown above. A run stops itself if it changes while the run is holding a position,
          because an exit sent somewhere the entry never went would leave a position nothing is
          managing.
        </p>
      </div>
    </PanelShell>
  )
}
