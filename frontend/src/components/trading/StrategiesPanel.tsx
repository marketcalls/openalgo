/**
 * The strategies this server is running, and the ones it could.
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

import { useCallback, useEffect, useRef, useState } from 'react'
import {
  type RunningStrategy,
  type RunSettings,
  clearSettings,
  overview,
  saveSettings,
  startStrategy,
  stopStrategy,
} from '@/api/openscriptRunner'
import { compileSource, kindOf, listScripts, readScript } from '@/lib/trading/openscriptFiles'
import {
  type InputDeclaration,
  inputsOf,
  settingsFromForm,
} from '@/lib/trading/backtestInputs'
import { quantityNote, quantityOf } from '@/lib/trading/strategyQuantity'
import { useThemeStore } from '@/stores/themeStore'
import { cn } from '@/lib/utils'
import { StrategyBooks } from './StrategyBooks'
import { StrategyInputs } from './StrategyInputs'
import { PANEL_HEADER, PanelShell } from './panelShell'

interface Props {
  /** The chart, for filling new settings from what the trader is looking at. */
  getChartContext(): { symbol: string; exchange: string; interval: string } | null
}

/**
 * How often the list is refreshed.
 *
 * A run is started and stopped from here and by the scheduler, and a child can
 * also stop itself: a diagnostic, a refused order, the destination changing
 * underneath it. Nothing pushes that to the browser, so the panel asks. Four
 * seconds is under the time it takes to wonder and costs one small request.
 */
const REFRESH_MS = 4000

const PRODUCTS = ['MIS', 'NRML', 'CNC'] as const

function since(started: string | null): string {
  if (!started) return ''
  const at = Date.parse(started)
  if (!Number.isFinite(at)) return started
  const mins = Math.max(0, Math.round((Date.now() - at) / 60000))
  if (mins < 60) return `${mins}m`
  const hours = Math.floor(mins / 60)
  return `${hours}h ${mins % 60}m`
}

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
  /** Which strategy's books are open. One at a time: a panel of open tables is unreadable. */
  const [opened, setOpened] = useState<string | null>(null)
  /** Bumped when a run starts or stops, so an open book refetches rather than going stale. */
  const [revision, setRevision] = useState(0)
  const [search, setSearch] = useState('')
  const live = useRef(true)

  const refresh = useCallback(async (signal?: AbortSignal) => {
    try {
      const found = await overview(signal)
      if (!live.current) return
      setRunning(found.running)
      setSettings(found.settings)
      setUnreachable(false)
    } catch {
      // Shown rather than swallowed: a panel that silently stops refreshing
      // reads as "nothing is running", which is the one wrong answer here.
      if (live.current) setUnreachable(true)
    }
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

  const openEditor = useCallback(
    (file: string) => {
      const held = settings.find((one) => one.file === file)
      const chart = getChartContext()
      setEditing(file)
      setDraft(
        held ?? {
          file,
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
          const source = await readScript(file)
          const built = await compileSource(file, source)
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

  const runningFor = (file: string) => running.find((one) => one.file === file) ?? null

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

      <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto p-2">
        {unreachable && (
          <p className="rounded border border-amber-500/40 px-2 py-1.5 text-[11px] text-amber-600 dark:text-amber-400">
            The runner cannot be reached, so this list may be out of date. Anything already
            running on the server is still running.
          </p>
        )}

        {problem && (
          <p className="rounded border border-destructive/40 px-2 py-1.5 text-[11px] text-destructive">
            {problem}
          </p>
        )}

        {strategies.length > 6 && (
          <input
            type="search"
            className="h-7 rounded border border-border bg-background px-2 text-[11px]"
            placeholder={`Search ${strategies.length} strategies`}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        )}

        {strategies.length === 0 && (
          <p className="text-[11px] text-muted-foreground">
            No strategies saved. A study plots and places no orders, so only a script that
            declares itself a strategy can be run.
          </p>
        )}

        {strategies
          .filter((file) => file.toLowerCase().includes(search.trim().toLowerCase()))
          .sort((a, b) => Number(Boolean(runningFor(b))) - Number(Boolean(runningFor(a))))
          .map((file) => {
          const run = runningFor(file)
          const held = settings.find((one) => one.file === file) ?? null
          const isEditing = editing === file

          return (
            <div key={file} className="flex flex-col gap-1.5 rounded border border-border p-2">
              <div className="flex items-center gap-1.5">
                <span
                  className={cn(
                    'h-1.5 w-1.5 shrink-0 rounded-full',
                    run ? 'bg-emerald-500' : 'bg-muted-foreground/40'
                  )}
                  aria-hidden
                />
                <span className="truncate text-xs font-medium" title={file}>
                  {file}
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

              {isEditing && draft && (
                <div className="flex flex-col gap-1.5 rounded bg-muted/40 p-1.5">
                  <div className="grid grid-cols-2 gap-1.5">
                    <input
                      className="h-7 rounded border border-border bg-background px-1.5 text-[11px]"
                      placeholder="Instrument"
                      value={draft.symbol}
                      onChange={(e) => setDraft({ ...draft, symbol: e.target.value })}
                    />
                    <input
                      className="h-7 rounded border border-border bg-background px-1.5 text-[11px]"
                      placeholder="Exchange"
                      value={draft.exchange}
                      onChange={(e) => setDraft({ ...draft, exchange: e.target.value })}
                    />
                    <input
                      className="h-7 rounded border border-border bg-background px-1.5 text-[11px]"
                      placeholder="Interval"
                      value={draft.interval}
                      onChange={(e) => setDraft({ ...draft, interval: e.target.value })}
                    />
                    <select
                      className="h-7 rounded border border-border bg-background px-1.5 text-[11px]"
                      value={draft.product}
                      onChange={(e) => setDraft({ ...draft, product: e.target.value })}
                    >
                      {PRODUCTS.map((one) => (
                        <option key={one} value={one}>
                          {one}
                        </option>
                      ))}
                    </select>
                  </div>

                  <StrategyInputs
                    declarations={declarations}
                    edited={typed}
                    onChange={(key, value) => setTyped((held) => ({ ...held, [key]: value }))}
                    note="A box left empty uses the script's own default. A running strategy reads these when it starts, so stop it and start it again to apply a change."
                  />

                  {sizeNote && (
                    <p className="text-[10px] leading-relaxed text-muted-foreground">{sizeNote}</p>
                  )}

                  <div className="flex gap-1.5">
                    <button
                      type="button"
                      className="h-7 flex-1 rounded border border-border text-[11px] hover:bg-accent"
                      onClick={() =>
                        void act(file, async () => {
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
                    >
                      Save
                    </button>
                    <button
                      type="button"
                      className="h-7 rounded border border-border px-2 text-[11px] hover:bg-accent"
                      onClick={() => setEditing(null)}
                    >
                      Cancel
                    </button>
                    {held && (
                      <button
                        type="button"
                        className="h-7 rounded border border-border px-2 text-[11px] text-muted-foreground hover:border-destructive/50 hover:text-destructive"
                        onClick={() =>
                          void act(file, async () => {
                            await clearSettings(file)
                            setEditing(null)
                          })
                        }
                      >
                        Clear
                      </button>
                    )}
                  </div>
                </div>
              )}

              <div className="flex gap-1.5">
                {run ? (
                  <button
                    type="button"
                    className="h-7 flex-1 rounded border border-border text-[11px] hover:border-destructive/50 hover:text-destructive disabled:opacity-50"
                    disabled={busy === file}
                    onClick={() => void act(file, () => stopStrategy(file))}
                  >
                    {busy === file ? 'Stopping' : 'Stop'}
                  </button>
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
              </div>

              {opened === file && <StrategyBooks file={file} revision={revision} />}
            </div>
          )
        })}

        <p className="mt-auto text-[10px] leading-relaxed text-muted-foreground">
          A run is a process on the server and outlives this page: closing the browser stops
          nothing. Orders go through this platform's own order path, so a run trades with your
          broker while the platform is in live mode and against the sandbox while it is in
          analyzer mode, the same as every other surface here. That setting is made elsewhere
          on the site and is shown above. A run stops itself if it changes while the run is
          holding a position, because an exit sent somewhere the entry never went would leave a
          position nothing is managing.
        </p>
      </div>
    </PanelShell>
  )
}
