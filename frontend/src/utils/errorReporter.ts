/**
 * Browser error reporter.
 *
 * Routes uncaught errors and unhandled promise rejections to the backend so
 * they land in log/errors.jsonl alongside server errors. Designed to never
 * crash the app — every codepath is wrapped, and the reporter refuses to
 * recurse into itself.
 *
 * Privacy: only message + stack + URL + component stack are sent. No DOM,
 * no localStorage, no form values, no breadcrumbs.
 *
 * Throttling: dedups identical messages within 30s. Caps at 30 reports/min
 * (server enforces too).
 *
 * Auth: endpoint requires a valid admin session. On 401 we stop trying for
 * the rest of this page lifetime to avoid noise.
 */

interface ClientErrorPayload {
  message: string
  stack?: string
  url?: string
  component_stack?: string
  user_agent?: string
  level?: 'ERROR' | 'WARN'
}

const ENDPOINT = '/admin/api/errors/client'
const DEDUP_WINDOW_MS = 30_000
const MAX_REPORTS_PER_MINUTE = 30
const RECENT_TTL_MS = 60_000

// Patterns that are noise — never report these.
const IGNORE_PATTERNS = [
  /ResizeObserver loop/i,
  /Non-Error promise rejection captured/i,
  /^Script error\.?$/, // cross-origin script with no CORS
  /Loading chunk \d+ failed/i, // stale build during deploy
  /ChunkLoadError/i,
  /Failed to fetch dynamically imported module/i,
]

const recentSends = new Map<string, number>()
const sendTimestamps: number[] = []
let isReporting = false
let isDisabled = false

function shouldIgnore(message: string): boolean {
  if (!message) return true
  return IGNORE_PATTERNS.some((rx) => rx.test(message))
}

function dedupKey(payload: ClientErrorPayload): string {
  return `${payload.level ?? 'ERROR'}|${payload.message}|${(payload.stack ?? '').slice(0, 200)}`
}

function withinRateLimit(): boolean {
  const now = Date.now()
  while (sendTimestamps.length > 0 && now - sendTimestamps[0] > RECENT_TTL_MS) {
    sendTimestamps.shift()
  }
  return sendTimestamps.length < MAX_REPORTS_PER_MINUTE
}

function pruneDedup(): void {
  const now = Date.now()
  for (const [key, ts] of recentSends.entries()) {
    if (now - ts > DEDUP_WINDOW_MS) recentSends.delete(key)
  }
}

async function fetchCSRFTokenSafe(): Promise<string | null> {
  try {
    const resp = await fetch('/auth/csrf-token', {
      credentials: 'include',
      keepalive: true,
    })
    if (!resp.ok) return null
    const data = await resp.json()
    return data?.csrf_token ?? null
  } catch {
    return null
  }
}

async function send(payload: ClientErrorPayload): Promise<void> {
  if (isDisabled || isReporting) return
  if (!withinRateLimit()) return

  pruneDedup()
  const key = dedupKey(payload)
  const now = Date.now()
  const last = recentSends.get(key)
  if (last !== undefined && now - last < DEDUP_WINDOW_MS) return
  recentSends.set(key, now)
  sendTimestamps.push(now)

  isReporting = true
  try {
    const csrf = await fetchCSRFTokenSafe()
    const resp = await fetch(ENDPOINT, {
      method: 'POST',
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
        ...(csrf ? { 'X-CSRFToken': csrf } : {}),
      },
      body: JSON.stringify(payload),
      keepalive: true,
    })
    if (resp.status === 401 || resp.status === 403) {
      // Not logged in / no permission — stop trying this session.
      isDisabled = true
    }
  } catch {
    // Reporter is best-effort. Never throw.
  } finally {
    isReporting = false
  }
}

export function reportClientError(payload: ClientErrorPayload): void {
  try {
    const message = (payload.message || '').slice(0, 2000)
    if (shouldIgnore(message)) return
    void send({
      level: payload.level ?? 'ERROR',
      message,
      stack: payload.stack?.slice(0, 20_000),
      url: (payload.url || window.location.href).slice(0, 2000),
      component_stack: payload.component_stack?.slice(0, 5000),
      user_agent: navigator.userAgent.slice(0, 500),
    })
  } catch {
    // Reporter must never crash the app.
  }
}

let installed = false

export function installGlobalErrorReporter(): void {
  if (installed) return
  installed = true

  // Don't spam during local dev — React StrictMode double-renders
  // produce noise that isn't representative of production.
  if (import.meta.env.DEV) return

  window.addEventListener('error', (event: ErrorEvent) => {
    reportClientError({
      message: event.message || 'Uncaught error',
      stack: event.error?.stack,
      url: event.filename || window.location.href,
    })
    // Stale-bundle recovery: if a top-level script tag failed to load
    // (e.g. preload of the new entry chunk after a deploy), reload once
    // to fetch the fresh index.html.
    void import('@/utils/chunkReload').then(({ tryAutoReloadOnChunkError }) => {
      tryAutoReloadOnChunkError(event.message)
    })
  })

  window.addEventListener('unhandledrejection', (event: PromiseRejectionEvent) => {
    const reason = event.reason
    let message = 'Unhandled promise rejection'
    let stack: string | undefined
    if (reason instanceof Error) {
      message = reason.message || message
      stack = reason.stack
    } else if (typeof reason === 'string') {
      message = reason
    } else {
      try {
        message = JSON.stringify(reason).slice(0, 2000)
      } catch {
        // ignore — keep default message
      }
    }
    reportClientError({ message, stack })
    // Defense-in-depth: React.lazy() rejections normally land in the
    // ErrorBoundary, but rapid navigation or non-React import() callers
    // can let them surface here instead. tryAutoReloadOnChunkError is a
    // no-op for unrelated rejections.
    void import('@/utils/chunkReload').then(({ tryAutoReloadOnChunkError }) => {
      tryAutoReloadOnChunkError(message)
    })
  })
}
