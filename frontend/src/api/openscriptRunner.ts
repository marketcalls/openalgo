/**
 * The OpenScript strategy runner, as the browser talks to it.
 *
 * A run is a process on the server, not a thing in this tab. Starting one
 * answers an identifier and never an outcome, because the deployment has a
 * request ceiling and buffers responses: a route that waited for a run would
 * time out with the run still going. So every call here is about a process that
 * outlives the page, and the page's job is to show what is there rather than to
 * hold it.
 *
 * These routes are served under the application's own origin, so nothing here
 * names a host.
 */

import { webClient } from './client'

const BASE = '/openscript/runner'

// `webClient` and not `apiClient`. The runner is a session blueprint registered
// at /openscript/runner, while apiClient prefixes /api/v1 onto everything it
// sends: every call reached /api/v1/openscript/runner/... and answered 404, so
// the panel showed "the runner cannot be reached" and every strategy read as
// having no instrument set. webClient is the client for exactly this: a
// session route, with the CSRF token a POST here needs.

/** One process the server is running. `state` is always running: see below. */
export interface RunningStrategy {
  id: string
  /**
   * The deployment this run is of, which is what everything else addresses.
   *
   * One script is deployed on several instruments, and on one instrument at
   * several intervals, at the same time. Each is a separate run with its own
   * position, its own book and its own decision to stop, so a call naming only
   * the file would not say which of them it meant. Same value as `id`.
   */
  deployment: string
  /** The script this deployment runs, which is what a trader reads. */
  file: string
  /**
   * Always `running`.
   *
   * The service drops a run whose process has gone before it copies anything
   * out, so a finished run is absent from these answers entirely rather than
   * present and marked finished. The field is here because a row shows a state,
   * and a reader should not have to infer one from a list's membership.
   */
  state: string
  symbol: string | null
  exchange: string | null
  interval: string | null
  product: string
  pid: number | null
  started_at: string | null
  log: string | null
}

/** One deployment: a script, what it runs on, and how it is configured. */
export interface RunSettings {
  /**
   * The id this deployment is known by, absent on one being created.
   *
   * Sending it is what makes a save an **edit**. Without it the server creates
   * a deployment with an id of its own, which is what keeps a deployment made
   * where another was removed from inheriting that one's orders, fills and
   * position.
   */
  deployment?: string
  /** The script this deployment runs. */
  file: string
  symbol: string
  exchange: string
  interval: string
  product: string
  /**
   * The script's own parameters, as the values its `input()` declarations are
   * resolved against.
   *
   * Plain values, never the language's tagged form: an engine validates a
   * supplied setting against the declaration it belongs to, which already
   * states the kind, and refuses a tagged one outright.
   *
   * Only what the trader actually set. A parameter absent here runs on the
   * default written in the script, which is the one value guaranteed to be the
   * right type and inside the declared bounds.
   */
  inputs?: Record<string, boolean | number | string>
  updated_at?: string | null
}

/** When a deployment starts and stops, on the platform's own scheduler. */
export interface Schedule {
  /** The deployment this belongs to, or the script for one saved before these. */
  deployment?: string
  file: string
  start_time: string | null
  stop_time: string | null
  days: string[]
}

export interface RunnerOverview {
  running: RunningStrategy[]
  scheduled: Schedule[]
  settings: RunSettings[]
  log_dir: string | null
}

/**
 * A refusal the server wrote for a person to read, or a sentence about the
 * server itself.
 *
 * The message is passed through rather than replaced: the runner refuses a
 * start for reasons a trader can act on, naming the script and what is missing,
 * and rewording that here would lose the part that says what to do.
 */
export class RunnerError extends Error {
  readonly status: number
  constructor(message: string, status: number) {
    super(message)
    this.name = 'RunnerError'
    this.status = status
  }
}

function problemFrom(error: unknown, fallback: string): RunnerError {
  const answered = (error as { response?: { status?: number; data?: { message?: string } } })
    ?.response
  return new RunnerError(answered?.data?.message || fallback, answered?.status ?? 0)
}

export async function overview(signal?: AbortSignal): Promise<RunnerOverview> {
  try {
    const res = await webClient.get<{
      status: string
      running?: RunningStrategy[]
      scheduled?: Schedule[]
      settings?: RunSettings[]
      log_dir?: string
    }>(`${BASE}/status`, { signal })
    return {
      running: res.data?.running ?? [],
      scheduled: res.data?.scheduled ?? [],
      settings: res.data?.settings ?? [],
      log_dir: res.data?.log_dir ?? null,
    }
  } catch (error) {
    throw problemFrom(error, 'The runner could not be reached.')
  }
}

/**
 * Start one deployment. Answers the run it created, never an outcome.
 *
 * It takes no body: what a run is of comes from the settings saved against the
 * deployment, so a start that carried an instrument would be a second place the
 * same fact is stated. A deployment with no settings is refused by name.
 *
 * `name` is a deployment id. A script name still works while that script is
 * deployed once, and is refused rather than guessed when it is deployed twice:
 * starting whichever of two happened to be looked at first would put a position
 * on an instrument nobody named.
 */
export async function startStrategy(file: string): Promise<RunningStrategy> {
  try {
    const res = await webClient.post<{ status: string; run: RunningStrategy }>(
      `${BASE}/start/${encodeURIComponent(file)}`
    )
    return res.data.run
  } catch (error) {
    throw problemFrom(error, `${file} could not be started.`)
  }
}

/**
 * End a run and leave its position exactly where it is.
 *
 * **This is a pause and not a stop**, and the difference is the position. A
 * trader pauses to change a parameter, to look at what a strategy is doing, or
 * before restarting the server: the position becomes theirs to manage and the
 * strategy stops deciding about it. `closeStrategy` is the one that spends
 * money, and it is a separate call for exactly that reason.
 */
export async function pauseStrategy(name: string): Promise<void> {
  try {
    await webClient.post(`${BASE}/pause/${encodeURIComponent(name)}`)
  } catch (error) {
    throw problemFrom(error, `${name} could not be paused.`)
  }
}

/**
 * Close what a run is holding, then end it.
 *
 * **This one spends money and cannot be taken back**, so nothing here calls it
 * without the trader having been asked. A close that did not happen comes back
 * as a refusal with the reason, and the run is still running and still holding:
 * the message is passed through rather than replaced, because it says what to
 * do next.
 */
export async function closeStrategy(name: string): Promise<void> {
  try {
    await webClient.post(`${BASE}/close/${encodeURIComponent(name)}`)
  } catch (error) {
    throw problemFrom(error, `${name} could not be closed and stopped.`)
  }
}

/**
 * Save a deployment: the script, the instrument, the interval and the rest.
 *
 * Addressed by the **script**, because the script is what is being deployed.
 * Whether this edits or creates is `settings.deployment`: with it the
 * deployment keeps the id its orders are tagged with, and without it the server
 * mints a new one.
 *
 * Creating a second deployment on the same script, instrument and interval is
 * refused by the server, because that is one strategy running twice on one
 * instrument. The refusal comes back in its own words and says what to do.
 */
export async function saveSettings(settings: RunSettings): Promise<void> {
  try {
    await webClient.post(`${BASE}/config/${encodeURIComponent(settings.file)}`, {
      symbol: settings.symbol,
      exchange: settings.exchange,
      interval: settings.interval,
      product: settings.product,
      // Always sent, including when empty. A save replaces what was stored, so
      // leaving the field off on a save that cleared every parameter would keep
      // the previous ones and run the strategy on settings the trader has just
      // removed from the screen in front of them.
      inputs: settings.inputs ?? {},
      // Absent on a new deployment, which is what tells the server to mint an
      // id rather than take over the one a removed deployment had.
      ...(settings.deployment ? { deployment: settings.deployment } : {}),
    })
  } catch (error) {
    throw problemFrom(error, `The settings for ${settings.file} could not be saved.`)
  }
}

/** Remove one deployment, addressed by its id. */
export async function clearSettings(file: string): Promise<void> {
  try {
    await webClient.delete(`${BASE}/config/${encodeURIComponent(file)}`)
  } catch (error) {
    throw problemFrom(error, `The settings for ${file} could not be cleared.`)
  }
}

export async function saveSchedule(schedule: Schedule): Promise<void> {
  try {
    // The deployment, because a schedule starts a run and a run is of a
    // deployment. The file is the fallback for a script deployed once.
    const at = schedule.deployment || schedule.file
    await webClient.post(`${BASE}/schedule/${encodeURIComponent(at)}`, {
      start_time: schedule.start_time,
      stop_time: schedule.stop_time,
      days: schedule.days,
    })
  } catch (error) {
    throw problemFrom(error, `The schedule for ${schedule.file} could not be saved.`)
  }
}

export async function clearSchedule(file: string): Promise<void> {
  try {
    await webClient.delete(`${BASE}/schedule/${encodeURIComponent(file)}`)
  } catch (error) {
    throw problemFrom(error, `The schedule for ${file} could not be cleared.`)
  }
}

// ---------------------------------------------------------------------------
// What a trader picks a deployment from, rather than typing
// ---------------------------------------------------------------------------

/** One instrument, as the platform's own instrument master holds it. */
export interface Instrument {
  symbol: string
  exchange: string
  name?: string
  lotsize?: number | string
}

/**
 * Instruments matching what is being typed, on one exchange.
 *
 * A symbol is the one string a broker mapping matches on, so a character wrong
 * is a start refused a minute later in a log, or an instrument that exists and
 * is not the one meant. Nothing is invented here: this is the master the rest of
 * the platform trades from.
 *
 * An empty answer on a failure rather than a thrown error, because this runs on
 * a keystroke: a form that threw while somebody was still typing would be a form
 * they could not fill in.
 */
export async function instrumentsOn(query: string, exchange: string): Promise<Instrument[]> {
  if (query.trim().length < 2) return []
  try {
    const params = new URLSearchParams({ q: query.trim() })
    if (exchange) params.set('exchange', exchange)
    const res = await webClient.get<{ status: string; data?: Instrument[] }>(
      `${BASE}/instruments?${params.toString()}`
    )
    return res.data?.data ?? []
  } catch {
    return []
  }
}

/**
 * The bars this broker serves, newest first as it lists them.
 *
 * The broker's own answer rather than a list kept in the page. Offering a
 * timeframe the broker does not serve is a deployment that saves, starts, and
 * fetches no history at all.
 */
export async function intervalsAvailable(): Promise<string[]> {
  try {
    const res = await webClient.get<{ status: string; data?: Record<string, string[]> }>(
      `${BASE}/intervals`
    )
    const held = res.data?.data
    if (Array.isArray(held)) return held as string[]
    if (!held || typeof held !== 'object') return []
    // The platform answers these grouped by kind: seconds, minutes, hours,
    // days. A page offering one list flattens them, keeping the order the
    // broker stated rather than sorting text that is not sorted as text.
    return Object.values(held).flatMap((one) => (Array.isArray(one) ? one : []))
  } catch {
    return []
  }
}

// ---------------------------------------------------------------------------
// What one strategy has done
// ---------------------------------------------------------------------------

/**
 * A book comes back in the platform's own envelope, rows and all.
 *
 * Typed loosely on purpose. These are the global orderbook's own rows, whatever
 * fields the broker in use puts on them, and narrowing them here would mean
 * this file deciding which of a broker's columns a trader is allowed to see.
 */
export interface StrategyBook {
  rows: Record<string, unknown>[]
  statistics: Record<string, unknown> | null
  problem: string | null
  /**
   * The whole answer, envelope and all.
   *
   * Carried because the rows are not the whole of it. A positions answer states
   * its totals beside the list rather than inside it, and those totals include
   * profit already realised on rows the book no longer holds, which adding up
   * what came back cannot see. A reader that wants them needs the envelope, and
   * a second request to get it would be asking the same question twice.
   */
  raw: unknown
}

const EMPTY: StrategyBook = { rows: [], statistics: null, problem: null, raw: null }

/**
 * The rows out of whichever key this book calls them.
 *
 * Three books and three spellings, plus a broker that answers `data` as a bare
 * list. Read by trying each rather than by assuming, because a book that
 * answered rows under a name this did not know would render as "no orders",
 * which reads as a strategy that has done nothing.
 */
function rowsOf(data: unknown): Record<string, unknown>[] {
  if (Array.isArray(data)) return data as Record<string, unknown>[]
  if (!data || typeof data !== 'object') return []
  for (const key of ['orders', 'trades', 'positions', 'positionbook', 'data']) {
    const held = (data as Record<string, unknown>)[key]
    if (Array.isArray(held)) return held as Record<string, unknown>[]
  }
  return []
}

/**
 * One of a deployment's three books.
 *
 * Addressed by the deployment, because an order's tag is the deployment's id
 * and that tag is the whole of the attribution. Asked for by file name, a
 * script deployed twice is answered nothing at all rather than one deployment's
 * orders mixed with the other's, which is the failure this replaced.
 */
async function book(kind: string, file: string, signal?: AbortSignal): Promise<StrategyBook> {
  try {
    const res = await webClient.get<{ status: string; data?: unknown; message?: string }>(
      `${BASE}/${kind}/${encodeURIComponent(file)}`,
      { signal }
    )
    if (res.data?.status !== 'success') {
      return {
        ...EMPTY,
        raw: res.data,
        problem: res.data?.message || `The ${kind} could not be read.`,
      }
    }
    const data = res.data.data
    const statistics =
      data && typeof data === 'object' && 'statistics' in (data as Record<string, unknown>)
        ? ((data as Record<string, unknown>).statistics as Record<string, unknown>)
        : null
    return { rows: rowsOf(data), statistics, problem: null, raw: res.data }
  } catch (error) {
    // A book that cannot be read is said so in the row rather than thrown: one
    // failing tab must not take down the panel a trader is using to decide
    // whether to stop something that is trading.
    return { ...EMPTY, problem: problemFrom(error, `The ${kind} could not be read.`).message }
  }
}

export const strategyOrderbook = (file: string, signal?: AbortSignal) =>
  book('orderbook', file, signal)
export const strategyTradebook = (file: string, signal?: AbortSignal) =>
  book('tradebook', file, signal)
export const strategyPositions = (file: string, signal?: AbortSignal) =>
  book('positions', file, signal)
