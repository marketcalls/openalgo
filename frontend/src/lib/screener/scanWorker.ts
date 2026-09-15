/**
 * Runs the scan off the main thread.
 *
 * The whole design of the screener rests on one property: an `openalgo-charts`
 * indicator descriptor's `calc` is a pure function of `(bars, settings)`. It
 * needs no chart, no canvas and no DOM, so the very code that draws a study on
 * `/trading` produces the screener's numbers here. That is why a value in the
 * results table equals the value on the chart -- not because two
 * implementations agree, but because there is one implementation.
 *
 * The indicator registry is per realm, so this worker loads its own copy of the
 * built-in tier and of the user's `strategies/indicators/*.js`. That is not
 * duplicated work being wasted; it is the price of `calc` running here instead
 * of blocking the page for several hundred symbols.
 *
 * The worker also does its own fetching. Routing bars through the main thread
 * would clone every bar twice for no gain, and fetching per chunk is what makes
 * an honest progress percentage possible: each chunk is requested, calculated
 * and reported before the next is asked for.
 */
import {
  type AlertSpec,
  type BulkOhlcvResponse,
  evaluateFilters,
  type IndicatorValues,
  SCAN_CHUNK,
  type ScanCommand,
  type ScanEvent,
  type ScanRequest,
  type ScanRow,
  type ScanSymbol,
  toBars,
} from './model'

interface Descriptor {
  id: string
  name: string
  inputs?: { key: string; default?: unknown }[]
  plots?: { key: string; title?: string; ohlc?: Record<string, string> }[]
  alerts?: AlertSpec[]
  attach?: unknown
  calc(
    bars: unknown,
    settings: Record<string, unknown>,
    store: Record<string, unknown>
  ): IndicatorValues
}

let catalogue: Promise<{ getIndicator(id: string): Descriptor | undefined }> | null = null
let cancelled = -1

function post(event: ScanEvent): void {
  ;(self as unknown as Worker).postMessage(event)
}

function messageOf(e: unknown): string {
  return e instanceof Error ? e.message : String(e)
}

/**
 * Register the built-in tier and the user's own indicators, once per worker.
 *
 * Order matters and is copied from `terminal.ts:loadIndicators`: the custom
 * loader snapshots the built-in ids on its first run to detect a user file
 * shadowing a built-in, so the tier has to have registered before it runs or
 * that warning is silently lost.
 */
function loadCatalogue() {
  if (!catalogue) {
    catalogue = (async () => {
      const core = await import('openalgo-charts')
      await import('openalgo-charts/indicators')
      const { loadCustomIndicators } = await import('@/lib/trading/customIndicators')
      // Same-origin module imports carry the session cookie, so the
      // session-guarded /custom-indicators route serves the worker too.
      await loadCustomIndicators({
        onProblem: (message) => post({ type: 'problem', runId: cancelled, message }),
      })
      return core as unknown as { getIndicator(id: string): Descriptor | undefined }
    })()
  }
  return catalogue
}

async function fetchChunk(request: ScanRequest, chunk: ScanSymbol[]): Promise<BulkOhlcvResponse> {
  const response = await fetch('/historify/api/bulk-ohlcv', {
    method: 'POST',
    credentials: 'same-origin',
    headers: {
      'Content-Type': 'application/json',
      // Without this an expired session answers with a 302 to the login page,
      // which fetch follows to a 200 of HTML; parsing that as JSON reports a
      // syntax error about an unexpected '<' rather than the real problem.
      // Asking for JSON gets a straight 401 instead. Same reasoning as
      // customIndicators.ts.
      Accept: 'application/json',
      'X-CSRFToken': request.csrf,
    },
    body: JSON.stringify({
      symbols: chunk,
      interval: request.interval,
      bars: request.bars,
      live: request.live,
    }),
  })

  if (response.status === 401 || response.status === 403) {
    throw new Error('Session expired. Sign in again and rescan.')
  }

  let body: BulkOhlcvResponse
  try {
    body = (await response.json()) as BulkOhlcvResponse
  } catch {
    // A body that is not JSON at all means something upstream answered instead
    // of the route -- a login page, a proxy error page. The status is the only
    // honest thing left to report.
    throw new Error(`Bar request failed (${response.status} ${response.statusText})`)
  }
  if (!response.ok || body.status !== 'success') {
    throw new Error(body.message || `Bar request failed (${response.status})`)
  }
  return body
}

/** Every column `calc` produced, read at the last bar. */
function lastValues(values: IndicatorValues, index: number): Record<string, number | null> {
  const out: Record<string, number | null> = {}
  for (const [key, column] of Object.entries(values)) {
    if (!Array.isArray(column)) continue
    const raw = column[index]
    out[key] = typeof raw === 'number' && Number.isFinite(raw) ? raw : null
  }
  return out
}

async function runScan(request: ScanRequest): Promise<void> {
  const { runId } = request

  let registry: { getIndicator(id: string): Descriptor | undefined }
  try {
    registry = await loadCatalogue()
  } catch (e) {
    post({ type: 'error', runId, message: `Could not load indicators: ${messageOf(e)}` })
    return
  }

  // getIndicator throws on an unknown id rather than returning undefined, so
  // this needs its own guard: folding it into the load failure above would tell
  // someone whose indicator has merely been renamed that the whole catalogue
  // failed to load, and send them looking in the wrong place.
  let descriptor: Descriptor | undefined
  try {
    descriptor = registry.getIndicator(request.indicatorId)
  } catch {
    descriptor = undefined
  }
  if (!descriptor) {
    post({ type: 'error', runId, message: `Unknown indicator '${request.indicatorId}'` })
    return
  }

  const alerts = descriptor.alerts ?? []
  let announcedColumns = false
  let done = 0
  let matched = 0
  let failed = 0

  for (let start = 0; start < request.symbols.length; start += SCAN_CHUNK) {
    if (cancelled === runId) return
    const chunk = request.symbols.slice(start, start + SCAN_CHUNK)

    let payload: BulkOhlcvResponse
    try {
      payload = await fetchChunk(request, chunk)
    } catch (e) {
      post({ type: 'error', runId, message: messageOf(e) })
      return
    }
    if (cancelled === runId) return

    if (payload.missing.length > 0) {
      post({ type: 'missing', runId, missing: payload.missing })
    }

    const rows: ScanRow[] = []
    for (const [key, columns] of Object.entries(payload.data)) {
      const [exchange, symbol] = [key.slice(0, key.indexOf(':')), key.slice(key.indexOf(':') + 1)]
      try {
        const bars = toBars(columns)
        // A fresh store per symbol: a shared one would leak one symbol's
        // scratch state into the next symbol's calculation.
        const values = descriptor.calc(bars, request.settings, {})
        const index = bars.length - 1

        if (!announcedColumns) {
          announcedColumns = true
          const plotKeys = new Set((descriptor.plots ?? []).map((p) => p.key))
          post({
            type: 'columns',
            runId,
            plots: (descriptor.plots ?? []).map((p) => ({ key: p.key, title: p.title || p.key })),
            // Signal flags and other non-plotted columns are discovered here
            // rather than declared: an indicator may emit any number of them,
            // and they are often the only thing worth screening on.
            extra: Object.keys(values).filter((k) => !plotKeys.has(k) && Array.isArray(values[k])),
          })
        }

        if (!evaluateFilters(request.filters, bars, values, request.settings, alerts)) continue

        const close = bars[index]?.close ?? null
        const previous = index > 0 ? bars[index - 1]?.close : null
        matched++
        rows.push({
          symbol,
          exchange,
          close,
          changePct: close !== null && previous ? ((close - previous) / previous) * 100 : null,
          lastBarTime: bars[index]?.time ?? null,
          values: lastValues(values, index),
          alerts: alerts
            .filter((a) => {
              try {
                return a.when({ bars, values, settings: request.settings, index })
              } catch {
                return false
              }
            })
            .map((a) => a.id),
        })
      } catch (e) {
        // One symbol's calc throwing must not end the scan. An indicator that
        // needs chart context throws on every symbol, which the page recognises
        // and reports once rather than as N identical rows.
        failed++
        rows.push({
          symbol,
          exchange,
          close: null,
          changePct: null,
          lastBarTime: null,
          values: {},
          alerts: [],
          error: messageOf(e),
        })
      }
    }

    done += chunk.length
    if (rows.length > 0) post({ type: 'rows', runId, rows })
    post({ type: 'progress', runId, done, total: request.symbols.length })
  }

  post({ type: 'done', runId, matched, scanned: request.symbols.length, failed })
}

self.onmessage = (event: MessageEvent<ScanCommand>) => {
  const command = event.data
  if (command.type === 'cancel') {
    cancelled = command.runId
    return
  }
  if (command.type === 'scan') {
    void runScan(command)
  }
}
