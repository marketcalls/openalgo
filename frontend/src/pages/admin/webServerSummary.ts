import type { SystemRuntime } from '@/types/admin'

/**
 * The web server part of the system report, as rows a trader can read.
 *
 * The labels match the downloadable report (blueprints/admin.py
 * `_render_report`), because docs/gthread/README.md tells an operator to check
 * "Web server", "Request threads" and "Started by launcher" there, and the
 * page should answer with the same words. The values are sentences rather
 * than the report's raw fields.
 *
 * eventlet is the default and what almost every install runs. There it has
 * no request thread pool, so every row about threads is left out rather than
 * shown as "not set", which would read as something missing.
 */

export interface RuntimeRow {
  label: string
  value: string
}

const WEB_SERVER_NAMES: Record<string, string> = {
  eventlet: 'eventlet (the default)',
  gthread: 'gthread',
  dev: 'Development server',
}

const PROXY_MODES: Record<string, string> = {
  subprocess: 'Separate process started by OpenAlgo',
  thread: 'Inside the OpenAlgo process',
  external: 'Separate service (Docker or standalone mode)',
}

function isNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

function plural(count: number, one: string, many: string): string {
  return `${count} ${count === 1 ? one : many}`
}

/**
 * Which web server is serving requests, read from the newest field first.
 *
 * `worker_class` is what the server registered. A server that could not
 * work it out still reports whether eventlet patched the process and a
 * `gunicorn-<worker>` or `flask-dev` hint, so those answer next.
 */
export function webServerKind(runtime: SystemRuntime): string | null {
  if (runtime.worker_class) return runtime.worker_class
  if (runtime.eventlet_active) return 'eventlet'
  const hint = runtime.wsgi_hint
  if (hint === 'flask-dev') return 'dev'
  if (hint?.startsWith('gunicorn-')) return hint.slice('gunicorn-'.length) || null
  return null
}

/** The web server's name as the page shows it. */
export function webServerLabel(kind: string | null): string {
  if (!kind) return 'Not detected'
  return WEB_SERVER_NAMES[kind] ?? kind
}

/** Where the market data proxy runs, in words. */
export function proxyModeLabel(mode: string | null | undefined): string {
  if (!mode) return 'Not detected'
  return PROXY_MODES[mode] ?? mode
}

/** Process uptime as days, hours and minutes. */
export function formatUptime(seconds: number | null | undefined): string | null {
  if (!isNumber(seconds) || seconds < 0) return null
  const minutes = Math.floor(seconds / 60)
  if (minutes < 1) return 'Less than a minute'
  const days = Math.floor(minutes / 1440)
  const hours = Math.floor((minutes % 1440) / 60)
  const mins = minutes % 60
  if (days > 0) return `${days} d ${hours} h`
  if (hours > 0) return `${hours} h ${mins} min`
  return `${mins} min`
}

function proxyStatusText(runtime: SystemRuntime): string | null {
  const status = runtime.websocket_proxy
  if (!status || typeof status.alive !== 'boolean') return null
  const state = status.alive ? 'Running' : 'Stopped'
  const restarts = status.restarts
  if (isNumber(restarts) && restarts > 0) {
    return `${state}, restarted ${plural(restarts, 'time', 'times')} since OpenAlgo started`
  }
  return state
}

function httpPoolText(runtime: SystemRuntime): string | null {
  if (!('http_pool' in runtime)) return null
  const pool = runtime.http_pool
  if (!pool) return 'None opened yet'
  const parts: string[] = []
  if (isNumber(pool.connections)) parts.push(`${pool.connections} open`)
  if (isNumber(pool.idle)) parts.push(`${pool.idle} idle`)
  if (parts.length === 0) return null
  if (isNumber(pool.max_connections)) parts.push(`up to ${pool.max_connections}`)
  return parts.join(', ')
}

/**
 * The rows of the Web server card, leaving out whatever the server did not
 * report or does not apply to the web server in use.
 */
export function webServerRows(runtime: SystemRuntime): RuntimeRow[] {
  const rows: RuntimeRow[] = []
  const add = (label: string, value: string | null | undefined) => {
    if (value !== null && value !== undefined && value !== '') rows.push({ label, value })
  }

  const kind = webServerKind(runtime)
  add('Web server', webServerLabel(kind))

  const requested = runtime.requested_worker_class
  if (requested) {
    const name = webServerLabel(requested)
    add('Web server in .env', kind === 'dev' ? `${name}, not used by the development server` : name)
  }

  add('gunicorn', runtime.gunicorn_version ?? null)

  // An eventlet install started the way it always was is not "missing" the
  // launcher, so a No is shown only where gthread is running or asked for.
  const launched = runtime.started_by_launcher
  const gthreadInvolved = kind === 'gthread' || requested === 'gthread'
  if (typeof launched === 'boolean' && (launched || gthreadInvolved)) {
    add('Started by launcher', launched ? 'Yes' : 'No')
  }

  const threads = isNumber(runtime.configured_threads) ? runtime.configured_threads : null
  if (threads !== null) {
    add('Request threads', String(threads))
    const pool = runtime.thread_pool
    if (pool && isNumber(pool.busy)) add('Request threads busy', `${pool.busy} of ${threads}`)
    if (pool && isNumber(pool.waiting)) {
      add('Requests waiting', pool.waiting === 0 ? 'None' : String(pool.waiting))
    }
    const budget = runtime.thread_budget
    if (budget && isNumber(budget.headroom)) {
      add('Threads free', `${Math.max(0, budget.headroom)} of ${threads}`)
    }
  }

  const budget = runtime.thread_budget
  if (budget && isNumber(budget.streams)) add('Open streams', String(budget.streams))
  if (budget && isNumber(budget.socketio)) add('Browser sessions', String(budget.socketio))

  if ('websocket_proxy_mode' in runtime || runtime.websocket_proxy) {
    add(
      'Market data proxy',
      proxyModeLabel(runtime.websocket_proxy_mode ?? runtime.websocket_proxy?.mode)
    )
  }
  add('Market data proxy status', proxyStatusText(runtime))

  add('Broker connections', httpPoolText(runtime))

  if (isNumber(runtime.graceful_timeout)) {
    add('Time to finish requests on stop', plural(runtime.graceful_timeout, 'second', 'seconds'))
  }
  if (isNumber(runtime.active_threads)) add('Process threads', String(runtime.active_threads))

  return rows
}

/** The server's notes for the operator, without blanks. */
export function webServerNotes(runtime: SystemRuntime): string[] {
  const notes = runtime.notes
  if (!Array.isArray(notes)) return []
  return notes.filter((note): note is string => typeof note === 'string' && note.trim() !== '')
}
