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

/** What a script will be run against, saved on the server per script. */
export interface RunSettings {
  file: string
  symbol: string
  exchange: string
  interval: string
  product: string
  updated_at?: string | null
}

/** When a script starts and stops, on the platform's own scheduler. */
export interface Schedule {
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
 * Start one script. Answers the run it created, never an outcome.
 *
 * It takes no body: what a run is of comes from the settings saved against the
 * script, so a start that carried an instrument would be a second place the
 * same fact is stated. A script with no settings is refused by name.
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

export async function stopStrategy(file: string): Promise<void> {
  try {
    await webClient.post(`${BASE}/stop/${encodeURIComponent(file)}`)
  } catch (error) {
    throw problemFrom(error, `${file} could not be stopped.`)
  }
}

export async function saveSettings(settings: RunSettings): Promise<void> {
  try {
    await webClient.post(`${BASE}/config/${encodeURIComponent(settings.file)}`, {
      symbol: settings.symbol,
      exchange: settings.exchange,
      interval: settings.interval,
      product: settings.product,
    })
  } catch (error) {
    throw problemFrom(error, `The settings for ${settings.file} could not be saved.`)
  }
}

export async function clearSettings(file: string): Promise<void> {
  try {
    await webClient.delete(`${BASE}/config/${encodeURIComponent(file)}`)
  } catch (error) {
    throw problemFrom(error, `The settings for ${file} could not be cleared.`)
  }
}

export async function saveSchedule(schedule: Schedule): Promise<void> {
  try {
    await webClient.post(`${BASE}/schedule/${encodeURIComponent(schedule.file)}`, {
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
}

const EMPTY: StrategyBook = { rows: [], statistics: null, problem: null }

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

async function book(kind: string, file: string, signal?: AbortSignal): Promise<StrategyBook> {
  try {
    const res = await webClient.get<{ status: string; data?: unknown; message?: string }>(
      `${BASE}/${kind}/${encodeURIComponent(file)}`,
      { signal }
    )
    if (res.data?.status !== 'success') {
      return { ...EMPTY, problem: res.data?.message || `The ${kind} could not be read.` }
    }
    const data = res.data.data
    const statistics =
      data && typeof data === 'object' && 'statistics' in (data as Record<string, unknown>)
        ? ((data as Record<string, unknown>).statistics as Record<string, unknown>)
        : null
    return { rows: rowsOf(data), statistics, problem: null }
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
