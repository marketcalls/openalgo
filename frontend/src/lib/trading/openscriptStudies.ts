/**
 * Compiles the trader's OpenScript sources and registers each one as a study.
 *
 * Called from `terminal.ts:loadIndicators` beside `loadCustomIndicators`, so
 * every path that can reach `chart.addIndicator` sees a compiled study before
 * it looks anything up, exactly as a custom indicator module is seen.
 *
 * **The difference from `customIndicators.ts` is what arrives over the wire.** A
 * custom indicator is a JavaScript module the page imports, so the page runs it
 * and it has the page's own authority. A source here is text. It is compiled to
 * a list of instructions, an engine walks that list, and a script can only name
 * what the instruction set gives it. There is no spelling for a network call, a
 * file or a reach into the page, so a study from a stranger can draw a wrong
 * line and cannot place an order.
 *
 * That is also why nothing here uses `import()` on a fetched URL and why the
 * route serves `text/plain`: a response the page could import would hand the
 * file the page's authority and undo the whole reason for the format. It is
 * what lets this run under a content security policy with no `unsafe-eval`,
 * which is the policy this application already sets.
 *
 * **Compiling is the trader's only feedback, so a failure has to be a sentence.**
 * There is no build step between saving a script and running it. A diagnostic
 * carries a code, a line, a column and a fix, and all four reach the caller
 * rather than a console nobody has open.
 *
 * **What is registered is a study hosted per chart, not the adapter's
 * descriptor as it comes.** A descriptor is registered once and globally, and
 * the terminal can show a different instrument in every pane. The engine reads
 * the instrument's facts (exchange, lot size, the trading session) from the
 * adapter's static `instrument` option, which one descriptor can only state
 * once. `hostedStudy` below is what lets each chart's copy of a study run on that
 * chart's instrument, and it is also where a bar-close alert is announced,
 * because the chart only ever judges an alert on a bar's first tick.
 */

import type { IndicatorAttachContext } from 'openalgo-charts'
import type {
  ChartAdapterOptions,
  ChartAlertContext,
  ChartAlertSpec,
  ChartBar,
  ChartCalcContext,
  ChartDescriptor,
  ChartSettings,
  ChartStore,
  ChartValues,
} from 'openalgo-script/adapters/charts'
import { cachedFacts, type InstrumentFacts, subscribeFacts } from './instrumentFacts'
import { idForScript } from './openscriptFiles'

/** One source the server is offering. `mtime` is what makes an edit reappear. */
interface StoredScript {
  file: string
  mtime: number
  bytes: number
}

export interface OpenScriptLoad {
  /** Scripts that compiled and registered, this call only. */
  loaded: string[]
  /** Per-script failures, already written for a trader to read. */
  errors: { file: string; message: string }[]
}

const INDEX_URL = '/openscript/index.json'

/**
 * Scripts already compiled, keyed by name and modification time.
 *
 * Module scope rather than per call, because `loadIndicators` runs on every
 * picker open, every layout restore and every symbol change. Keying on the
 * modification time is what makes an edited script recompile and an untouched
 * one cost nothing.
 */
const compiled = new Set<string>()

/** What a trader should read when something fails, never a status code. */
function messageOf(error: unknown): string {
  if (error instanceof Error && error.message) return error.message
  return String(error)
}

/**
 * Whether this program places orders, read off the program not off the file.
 *
 * **This used to decide whether to register the script at all, and now decides
 * how.** A program needing `orders` is registered like any study and run
 * against the language's own simulated venue, which is what `simulateOrders`
 * turns on at the call below; without it the engine refuses such a program at
 * load with OS6006, a message about capability tags shown to somebody who had
 * only pressed a button in a list.
 *
 * Read from the program's own `requires` rather than from whether the source
 * says `study` or `strategy`, because `requires` is the same fact the engine
 * tests. A strategy that placed no orders would need no simulation and a study
 * that somehow placed them would, and both would be right.
 */
function placesOrders(program: unknown): string | null {
  const requires = (program as { requires?: unknown })?.requires
  if (!Array.isArray(requires)) return null
  const beyond = requires.filter((tag) => tag === 'orders')
  return beyond.length > 0 ? String(beyond[0]) : null
}

/**
 * Compiles one source into the program an engine is handed.
 *
 * Throws with every diagnostic the compiler produced rather than the first.
 * A script usually has one mistake and sometimes has four, and reporting one
 * at a time turns a single read-through into four saves.
 */
async function programFor(file: string, text: string): Promise<unknown> {
  const { sourceFile, lex, parseTokens, check, emit, DiagnosticBag, renderDiagnostics } =
    await import('openalgo-script')

  const source = sourceFile(file, text)
  const bag = new DiagnosticBag()
  const tokens = lex(source, bag)
  const tree = parseTokens(source, tokens, bag)
  const checked = check(source, tree, bag)
  const result = emit(source, checked, bag, {})

  if (result.program === undefined) {
    const rendered = renderDiagnostics(source, bag.ordered())
    throw new Error(rendered || 'the script did not compile')
  }
  return result.program
}

/** The two conversions a `"time"` input needs, both the chart's own. */
export interface ChartClock {
  zonedWallClockToUtcSeconds(
    year: number,
    month: number,
    day: number,
    hour?: number,
    minute?: number,
    second?: number,
    zone?: string
  ): number
  isValidTimezone(zone: string): boolean
}

/** The spelling a `"time"` input is stored in, the same one the engine's own reader takes. */
const STAMP = /^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2})(?::(\d{2}))?)?$/

/**
 * A `"time"` input's wall clock string, read in the chart's zone, as UTC seconds.
 *
 * The settings dialog stores `YYYY-MM-DD HH:MM` as the trader typed it, because a
 * saved layout has to restore to the same reading in another zone. Without a
 * reader the adapter falls back to treating the string as UTC, so 09:15 typed on
 * an IST chart landed at 14:45 IST. The conversion is the chart's own, which asks
 * `Intl` for the zone's offset at that instant rather than assuming one, so it
 * is right in a zone with a seasonal clock change as well.
 *
 * A date that does not exist (the 30th of February) is refused rather than
 * rolled into the next month: the input's validation turns the throw into a
 * refusal naming the key and the value, which is the answer the trader can act
 * on. No zone at all is the engine's own reading, UTC.
 */
export function wallClockReader(clock: ChartClock): (text: string, zone: string) => number {
  return (text, zone) => {
    const parsed = STAMP.exec(text.trim())
    if (parsed === null) throw new Error('a time is written as YYYY-MM-DD HH:MM')
    const [year, month, day, hour, minute, second] = parsed
      .slice(1)
      .map((part) => Number(part ?? '0'))
    const probe = new Date(Date.UTC(year, month - 1, day, hour, minute, second))
    if (
      probe.getUTCFullYear() !== year ||
      probe.getUTCMonth() !== month - 1 ||
      probe.getUTCDate() !== day ||
      probe.getUTCHours() !== hour ||
      probe.getUTCMinutes() !== minute ||
      probe.getUTCSeconds() !== second
    ) {
      throw new Error('that date and time does not exist')
    }
    if (zone === '') return probe.getTime() / 1000
    if (!clock.isValidTimezone(zone)) throw new Error('the chart timezone could not be read')
    return clock.zonedWallClockToUtcSeconds(year, month, day, hour, minute, second, zone)
  }
}

/**
 * The event a study's bar-close alert is announced on, on the chart's own bus.
 *
 * Not `indicator:alert`, which is the chart's own and carries the instance id: a
 * descriptor is never told which instance it is running for, so an event under
 * that name without one would be a payload a listener keyed on the id could not
 * place. The terminal delivers both through the same path.
 */
export const SCRIPT_ALERT_EVENT = 'openscript:alert'

/** What that event carries: the chart's alert payload less the instance id. */
export interface ScriptAlertPayload {
  indicatorId: string
  alertId: string
  title: string
  message: string
  /** The bar that closed, not the one whose arrival closed it. */
  time: number
  index: number
}

/** The store key this host keeps its per-instance state under. */
const HOST = 'openalgo:host'

/** The instrument a chart is showing, as its data context states it. */
interface Identity {
  readonly symbol: string
  readonly exchange: string
}

/** Which of a study's descriptors a calculation ran on, and on which facts. */
interface Choice {
  readonly descriptor: ChartDescriptor
  readonly facts: InstrumentFacts | undefined
}

/** What a full calculation built its engine from: the choice, and the chart's zone. */
interface Ran extends Choice {
  readonly zone: string | undefined
}

/** One instance's state, kept in the store the chart gives that instance. */
interface HostState {
  /** The chart's data context, read at call time. Set by `attach`. */
  context?: () => { readonly symbol?: string; readonly exchange?: string } | undefined
  /** The chart's event bus. Set by `attach`. */
  emit?: (event: string, payload: unknown) => void
  /** What the last full calculation ran on, which the held engine was built by. */
  ran?: Ran
  /** The newest bar the last live pass computed, by time. */
  live?: number
}

function stateIn(store: ChartStore): HostState {
  const held = store[HOST] as HostState | undefined
  if (held !== undefined) return held
  const made: HostState = {}
  store[HOST] = made
  return made
}

function normalised(symbol: unknown, exchange: unknown): Identity | undefined {
  if (typeof symbol !== 'string' || typeof exchange !== 'string') return undefined
  const s = symbol.trim()
  const x = exchange.trim().toUpperCase()
  return s && x ? { symbol: s, exchange: x } : undefined
}

/**
 * The exchange each symbol was last shown on, by any chart.
 *
 * Only a first guess. The chart builds a study and calculates it once before it
 * runs the study's `attach`, which is the one place the chart's data context
 * (and so the exchange) reaches a descriptor; the calculation context carries the
 * symbol alone. Guessing from the last chart that showed the symbol makes that
 * first calculation right in the ordinary case, so a chart rebuilt on an interval
 * change does not calculate every study twice. `attach` then reads the real
 * context and calculates again only where the guess was wrong, which takes the
 * same symbol open on two exchanges in two panes.
 */
const exchangeGuess = new Map<string, string>()
const GUESSES_KEPT = 256

function rememberExchange(identity: Identity): void {
  exchangeGuess.delete(identity.symbol)
  exchangeGuess.set(identity.symbol, identity.exchange)
  if (exchangeGuess.size > GUESSES_KEPT) {
    const oldest = exchangeGuess.keys().next().value
    if (oldest !== undefined) exchangeGuess.delete(oldest)
  }
}

/** The instrument an instance is on: its chart's context once attached, else the guess. */
function identityOf(store: ChartStore, symbol: string | undefined): Identity | undefined {
  const state = store[HOST] as HostState | undefined
  if (state?.context !== undefined) {
    const context = state.context()
    return normalised(context?.symbol, context?.exchange)
  }
  if (symbol === undefined) return undefined
  return normalised(symbol, exchangeGuess.get(symbol.trim()))
}

const canonicalZones = new Map<string, string>()

/** A zone's canonical spelling, so `Asia/Calcutta` and `Asia/Kolkata` compare equal. */
function canonicalZone(zone: string): string {
  let known = canonicalZones.get(zone)
  if (known === undefined) {
    try {
      known = new Intl.DateTimeFormat('en-US', { timeZone: zone }).resolvedOptions().timeZone
    } catch {
      known = zone
    }
    canonicalZones.set(zone, known)
  }
  return known
}

/**
 * Whether the facts' session can be read in the zone the engine will use.
 *
 * A session is wall clock in the exchange's zone (`host-interface.md` 4.3). The
 * adapter hands the engine the chart's zone instead of the record's, because
 * every calendar call has to agree with the axis beside it, so on a chart whose
 * zone a trader changed to their own, 09:15 to 15:30 would be read in that zone
 * and every session fact would land hours away from the session. Leaving the
 * session out there gives the honest answer, absent, rather than a wrong one.
 */
function sessionFits(facts: InstrumentFacts, chartZone: string | undefined): boolean {
  if (facts.session === undefined || !chartZone) return true
  if (!facts.timezone) return false
  return chartZone === facts.timezone || canonicalZone(chartZone) === canonicalZone(facts.timezone)
}

/** The previous values with a tail laid over them, the same splice the chart makes. */
function spliced(previous: ChartValues, tail: ChartValues, from: number, n: number): ChartValues {
  const out: Record<string, (number | null)[]> = {}
  for (const key of Object.keys(tail)) {
    const before = previous[key]
    const after = tail[key]
    const column = new Array<number | null>(n)
    for (let index = 0; index < from; index += 1) column[index] = before?.[index] ?? null
    for (let index = from; index < n; index += 1) column[index] = after?.[index - from] ?? null
    out[key] = column
  }
  return out
}

/** A study as registered: the adapter's descriptor, with an `attach` the chart's own type describes. */
export type HostedStudy = Omit<ChartDescriptor, 'attach'> & {
  attach(ctx: IndicatorAttachContext): () => void
}

/**
 * One registered study that runs each chart's copy on that chart's instrument.
 *
 * `build` makes the adapter's descriptor for the program, with or without
 * instrument facts. The adapter merges its static `instrument` option with what
 * the chart states per calculation (symbol, interval, tick size, zone), so the
 * only way to give two charts two instruments is two descriptors. This keeps one
 * built without facts, for every static field and hook and for a chart whose
 * facts have not arrived, and builds one per facts record on first use.
 *
 * **Which descriptor runs is decided per call, and a tail only ever continues
 * the one that ran the full calculation.** The adapter holds the engine in the
 * instance's store between calculations, and a tail extends that engine rather
 * than building another. So `calcTail` answers null whenever the descriptor it
 * would choose now is not the one the held engine was built by, and the chart
 * falls back to a full calculation on the right one. Splicing a tail computed
 * with a lot size onto a history computed without one would draw a study that
 * looks entirely plausible and is wrong. The chart's zone is held to the same
 * rule: the engine reads its calendar, its session and every `"time"` input in
 * the zone it was loaded with, and the adapter's own tail check compares the
 * settings and the bar times but not the zone, so a trader switching the chart
 * to another zone kept the old one's readings until the next history load.
 *
 * **The chart is asked to recompute when facts arrive.** `attach` is the one
 * place a descriptor sees the chart's data context, which is where the exchange
 * lives, and it subscribes to the facts helper for that instrument and calls the
 * chart's own `requestRecompute`. While facts load, or when they cannot be had,
 * the study runs exactly as it did before there were any.
 *
 * **The regular session, never today's.** The facts helper also knows today's
 * window, which on a special day (Muhurat on a Sunday evening, an evening-only
 * session on a holiday) differs from the rest. The engine holds one session for a
 * whole run, and a chart's run is its entire history, so stating today's window
 * would put every other day on the chart outside its own session. The regular
 * window is what history is read against.
 *
 * **A bar-close alert is announced here, when the bar closes.** The chart judges
 * a study's alerts once per bar, when the bar first reaches it, and an OpenScript
 * alert waits for the bar to be confirmed (`stdlib.md` 16.2): on its first tick
 * the condition is still withheld, and when the next bar arrives and the engine
 * decides it, the chart has already moved on. So a default alert never fired on
 * a live chart. The tail calculation that appends a bar is also the one that
 * re-executes the bar it closed, so that is where the closed bar is judged, with
 * the study's own conditions and the settings the chart handed the calculation
 * (which the message is keyed by). Two rules keep it honest:
 *
 * - **Only a bar this chart saw live.** A bar is judged only when the previous
 *   live pass had it as the newest bar. After a history load the first bar to
 *   close is the load's last one, which may be yesterday's, and announcing it
 *   would be announcing history.
 * - **Never a second time.** A study written with `onUnconfirmed = true` can be
 *   true on a bar's first tick, and the chart has then already fired it. The
 *   conditions the chart is given are wrapped to note each one it accepts, and
 *   a bar and alert it has fired are not announced again.
 */
export function hostedStudy(
  indicatorId: string,
  build: (instrument?: InstrumentFacts) => ChartDescriptor
): HostedStudy {
  const base = build()
  const specs: readonly ChartAlertSpec[] = base.alerts ?? []

  const withFacts = new WeakMap<
    InstrumentFacts,
    { whole?: ChartDescriptor; sessionless?: ChartDescriptor }
  >()
  const descriptorWith = (facts: InstrumentFacts, keepSession: boolean): ChartDescriptor => {
    let pair = withFacts.get(facts)
    if (pair === undefined) {
      pair = {}
      withFacts.set(facts, pair)
    }
    if (keepSession) {
      pair.whole ??= build(facts)
      return pair.whole
    }
    if (pair.sessionless === undefined) {
      const { session: _unread, ...rest } = facts
      pair.sessionless = build(rest)
    }
    return pair.sessionless
  }

  const choose = (
    store: ChartStore,
    symbol: string | undefined,
    zone: string | undefined
  ): Choice => {
    const identity = identityOf(store, symbol)
    const facts = identity ? cachedFacts(identity.symbol, identity.exchange) : undefined
    if (facts === undefined) return { descriptor: base, facts: undefined }
    return { descriptor: descriptorWith(facts, sessionFits(facts, zone)), facts }
  }

  // Per instance, by the settings object the chart hands every hook of one
  // instance: which bars and alerts the chart has already fired itself.
  const firedByChart = new WeakMap<object, Map<number, Set<string>>>()
  const noteFired = (settings: object, alertId: string, time: number) => {
    let byTime = firedByChart.get(settings)
    if (byTime === undefined) {
      byTime = new Map()
      firedByChart.set(settings, byTime)
    }
    const ids = byTime.get(time) ?? new Set<string>()
    ids.add(alertId)
    byTime.set(time, ids)
  }

  const announceClosed = (
    bars: readonly ChartBar[],
    settings: ChartSettings,
    from: number,
    previous: ChartValues,
    tail: ChartValues,
    state: HostState
  ) => {
    const closed = bars[from]
    // A pass that replaced the newest bar closed nothing, and a bar the last
    // live pass did not have as its newest was never live on this chart.
    if (closed === undefined || bars.length !== from + 2 || state.live !== closed.time) return
    const emit = state.emit
    if (emit === undefined || specs.length === 0) return
    const byTime = firedByChart.get(settings)
    const ctx: ChartAlertContext = {
      bars,
      values: spliced(previous, tail, from, bars.length),
      settings,
      index: from,
    }
    for (const spec of specs) {
      if (!spec.when(ctx)) continue
      if (byTime?.get(closed.time)?.has(spec.id)) continue
      const payload: ScriptAlertPayload = {
        indicatorId,
        alertId: spec.id,
        title: spec.title,
        message: spec.message?.(ctx) ?? spec.title,
        time: closed.time,
        index: from,
      }
      emit(SCRIPT_ALERT_EVENT, payload)
    }
    // Nothing at or before the closed bar can be judged again.
    for (const time of [...(byTime?.keys() ?? [])]) if (time <= closed.time) byTime?.delete(time)
  }

  return {
    ...base,
    ...(base.alerts === undefined
      ? {}
      : {
          alerts: base.alerts.map((spec) => ({
            ...spec,
            when: (ctx: ChartAlertContext) => {
              const accepted = spec.when(ctx)
              const time = ctx.bars[ctx.index]?.time
              if (accepted && time !== undefined) noteFired(ctx.settings, spec.id, time)
              return accepted
            },
          })),
        }),
    calc(bars, settings, store, ctx) {
      const choice = choose(store, ctx?.symbol, ctx?.timezone)
      const values = choice.descriptor.calc(bars, settings, store, ctx)
      const state = stateIn(store)
      state.ran = { ...choice, zone: ctx?.timezone }
      // A full calculation is a history load, a settings change or facts
      // arriving, and none of those is a live bar.
      state.live = undefined
      return values
    },
    calcTail(bars, settings, fromIndex, previous, store, ctx?: ChartCalcContext) {
      const state = stateIn(store)
      const choice = choose(store, ctx?.symbol, ctx?.timezone)
      const ran = state.ran
      if (ran?.descriptor !== choice.descriptor || ran.zone !== ctx?.timezone) return null
      const tail = choice.descriptor.calcTail?.(bars, settings, fromIndex, previous, store, ctx)
      if (tail === undefined || tail === null) return null
      announceClosed(bars, settings, fromIndex, previous, tail, state)
      state.live = bars[bars.length - 1]?.time
      return tail
    },
    attach(ctx: IndicatorAttachContext) {
      const state = stateIn(ctx.store)
      state.context = () => ctx.dataContext?.()
      state.emit =
        ctx.emit === undefined ? undefined : (event, payload) => ctx.emit?.(event, payload)
      const identity = identityOf(ctx.store, undefined)
      if (identity !== undefined) rememberExchange(identity)

      // Calculate again when what the chart should be running on is not what
      // it ran on: facts that were already here, or a first guess that named
      // the wrong exchange. Nothing calculated yet is nothing to redo.
      const settle = () => {
        if (ctx.signal?.aborted || state.ran === undefined) return
        const wanted = choose(ctx.store, undefined, ctx.timezone?.())
        if (wanted.descriptor !== state.ran.descriptor) ctx.requestRecompute()
      }
      const unsubscribe = subscribeFacts((symbol, exchange) => {
        const current = identityOf(ctx.store, undefined)
        if (current?.symbol === symbol && current.exchange === exchange) settle()
      })
      settle()

      // A study that reads another instrument has a lifecycle of its own, and
      // it runs on the same store whichever descriptor calculated.
      const inner = base.attach?.(ctx as never)
      return () => {
        unsubscribe()
        if (typeof inner === 'function') inner()
        state.context = undefined
        state.emit = undefined
      }
    },
  }
}

/**
 * Fetches, compiles and registers every stored script that has changed.
 *
 * One script failing takes nothing else down: each is caught on its own and
 * reported by name, because a trader with four studies and one typo should
 * still see the other three.
 *
 * **There is no reporter for a problem found while a study runs**, which is the
 * one thing `customIndicators` needs and this does not. That reporter exists
 * there because a hand written `calc` returning a column one element short
 * draws nothing and throws nothing, so nothing else would ever say so. Here the
 * columns are built from the engine's own channels, and a study that stops on a
 * bar throws a named error carrying the catalogue's sentence, its code and its
 * fix, which the chart already puts in front of the trader.
 */
export async function loadOpenScriptStudies(): Promise<OpenScriptLoad> {
  const result: OpenScriptLoad = { loaded: [], errors: [] }

  let stored: StoredScript[]
  try {
    const response = await fetch(INDEX_URL, { headers: { Accept: 'application/json' } })
    if (!response.ok) return result
    stored = (await response.json()) as StoredScript[]
  } catch {
    // No scripts folder, or no session. Neither is a problem to report: the
    // trader did not ask for anything here.
    return result
  }
  if (!Array.isArray(stored) || stored.length === 0) return result

  const fresh = stored.filter((one) => !compiled.has(`${one.file}@${one.mtime}`))
  if (fresh.length === 0) return result

  const charts = await import('openalgo-charts')
  const { descriptorFor } = await import('openalgo-script/adapters/charts')
  const resolveTime = wallClockReader(charts)

  for (const script of fresh) {
    compiled.add(`${script.file}@${script.mtime}`)
    try {
      const url = `/openscript/${encodeURIComponent(script.file)}?v=${script.mtime}`
      const response = await fetch(url)
      if (!response.ok) throw new Error('this script could not be read back from the server')
      const text = await response.text()

      const program = await programFor(script.file, text)

      // **A strategy is registered like a study, and draws like one.** It has
      // plots, a title and settings exactly as a study does, and until now none
      // of them reached the chart: a trader who saved a strategy opened the
      // indicator list and could not find it, so its lines came from a separate
      // study they had to keep in step by hand.
      //
      // `simulateOrders` is what makes that safe. Without it the engine refuses
      // a program that places orders, and with a destination that answered
      // nothing it would run while never learning it holds a position: every
      // close closing nothing, every entry allowed again on the next signal,
      // and the plots wrong wherever they read the position. The language runs
      // it against the venue its own backtest uses instead, so what is drawn
      // here and what a report of the same script says are one answer.
      //
      // **It places nothing.** The venue is a simulation inside the browser;
      // the chart has no route to the platform and is given none. Trading is
      // what the strategies panel is for, and the panel says so on screen.
      const trades = placesOrders(program) !== null

      const id = idForScript(script.file)
      const options: ChartAdapterOptions = {
        id,
        category: 'OpenScript',
        ...(trades ? { simulateOrders: true } : {}),
        resolveTime,
      }
      const descriptor = hostedStudy(id, (instrument) =>
        descriptorFor(program as never, instrument ? { ...options, instrument } : options)
      )
      // `hasSource` puts a braces button on this study's legend row, which the
      // chart turns into an `indicatorSource` event and the terminal turns back
      // into this file. Set here rather than by the language's adapter: the
      // adapter compiles a program and has no opinion about whether the host
      // can show anybody a file, and this host can, because it is the one
      // serving them.
      // `markerAnchor` decides what a signal's "above" and "below" are measured
      // against. A script writes `at = "below"` meaning below the candle, and
      // the chart's default is the study's own first plot: a study that
      // declares an invisible mid-body column first, so its marks have a
      // series with a point on every bar, then draws every mark through the
      // middle of the candle it is about. Price is what the author meant.
      charts.registerIndicator({
        ...(descriptor as object),
        hasSource: true,
        markerAnchor: 'price',
      } as never)
      result.loaded.push(script.file)
    } catch (error) {
      // Forget the key so the next call tries again. A compile that failed
      // because the server was briefly unreachable should not stay failed for
      // the life of the page.
      compiled.delete(`${script.file}@${script.mtime}`)
      result.errors.push({ file: script.file, message: messageOf(error) })
    }
  }

  return result
}

/** Drops the compiled record, so the next call recompiles every script. */
export function forgetOpenScriptStudies(): void {
  compiled.clear()
}
