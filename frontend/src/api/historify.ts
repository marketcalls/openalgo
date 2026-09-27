/**
 * Historify API: the locally downloaded DuckDB history store.
 *
 * Served by blueprints/historify.py under the root path (not /api/v1), so this
 * uses webClient, which carries the session cookie and the CSRF token. Every
 * read route here is session-authenticated and takes no API key, so a user who
 * has never generated one can still browse what they have downloaded.
 *
 * Using axios rather than bare fetch is not cosmetic. check_session_validity
 * only answers a 401 when the request looks like AJAX; on an expired session a
 * plain fetch gets a 302 to the login HTML and then fails inside response.json()
 * with a parse error that names nothing useful. Axios sends an Accept header
 * beginning with application/json, so the same expiry arrives as a 401 and the
 * shared interceptor redirects to /login.
 */

import { webClient } from './client'

/** One stored (symbol, exchange, interval) and the range it covers. */
export interface CatalogRow {
  symbol: string
  exchange: string
  interval: string
  first_timestamp: number
  last_timestamp: number
  record_count: number
  last_download_at?: string
  /** Added by the service, not the table. Absent on some branches. */
  first_date?: string
  last_date?: string
}

/** A catalog row joined to the master-contract metadata, for a readable picker. */
export interface CatalogMetadataRow extends CatalogRow {
  name?: string
  expiry?: string
  strike?: number
  lotsize?: number
  instrumenttype?: string
  tick_size?: number
}

/**
 * One candle.
 *
 * `timestamp` and `volume` are typed number because that is what they mean, but
 * the wire is not consistent about it: the stored 1m and D intervals return
 * integers while every computed interval comes back from a DuckDB FLOOR() as a
 * float. Normalizing is the feed's job, not the caller's.
 */
export interface HistorifyCandle {
  timestamp: number
  open: number
  high: number
  low: number
  close: number
  volume: number
  oi: number
}

interface CatalogEnvelope {
  status: 'success' | 'error'
  data?: CatalogRow[]
  count?: number
  message?: string
}

interface MetadataEnvelope {
  status: 'success' | 'error'
  data?: CatalogMetadataRow[]
  count?: number
  message?: string
}

/**
 * The data route's envelope.
 *
 * An empty result is a 200 with `count: 0` and no symbol/exchange/interval
 * echo, which is a different shape from a hit. Callers must not read those
 * three without checking `count`.
 */
interface DataEnvelope {
  status: 'success' | 'error'
  symbol?: string
  exchange?: string
  interval?: string
  data?: HistorifyCandle[]
  count?: number
  message?: string
}

export interface ChartDataRequest {
  symbol: string
  exchange: string
  interval: string
  /** YYYY-MM-DD. Omitting both ends returns the whole stored history. */
  startDate?: string
  endDate?: string
  signal?: AbortSignal
}

export const historifyApi = {
  /** Every stored range, one row per symbol, exchange and interval. */
  catalog: async (signal?: AbortSignal): Promise<CatalogRow[]> => {
    const res = await webClient.get<CatalogEnvelope>('/historify/api/catalog', { signal })
    return res.data.data ?? []
  },

  /**
   * The catalog joined to symbol metadata.
   *
   * The one call that combines availability with a readable name, expiry and
   * strike, which is what a picker restricted to downloaded data needs. Falls
   * back to the plain catalog, because the join is the newer route and an
   * installation that has never enriched its metadata still has a catalog.
   */
  catalogMetadata: async (signal?: AbortSignal): Promise<CatalogMetadataRow[]> => {
    try {
      const res = await webClient.get<MetadataEnvelope>('/historify/api/catalog/metadata', {
        signal,
      })
      if (res.data.data?.length) return res.data.data
    } catch {
      // Fall through to the plain catalog below.
    }
    return historifyApi.catalog(signal)
  },

  /** Candles for one symbol, exchange and interval. */
  chartData: async (req: ChartDataRequest): Promise<HistorifyCandle[]> => {
    const res = await webClient.get<DataEnvelope>('/historify/api/data', {
      signal: req.signal,
      params: {
        symbol: req.symbol.toUpperCase(),
        exchange: req.exchange.toUpperCase(),
        interval: req.interval,
        ...(req.startDate ? { start_date: req.startDate } : {}),
        ...(req.endDate ? { end_date: req.endDate } : {}),
      },
    })
    // An empty window is a normal answer, not a failure: a symbol simply may
    // not have been downloaded that far back.
    return res.data.data ?? []
  },
}

/**
 * The sentence to show a trader when a read fails.
 *
 * Always the caller's fallback, and that is deliberate. Every read route here
 * answers a failure with `jsonify({"status": "error", "message": str(e)})` and
 * a 500, and the shared axios interceptor lifts that onto `error.message`. So
 * the server's text is a rendered Python exception, and for these routes it is
 * never anything else.
 *
 * An earlier version of this tried to filter that text instead, rejecting
 * anything that looked like a traceback or an exception class. It does not
 * work, because the damaging strings do not announce themselves: a bad date
 * yields `time data 'abc' does not match format '%Y-%m-%d'`, which is 48
 * characters, carries no exception class and names no status code, and would
 * have sailed through every check and landed in front of someone reading a
 * price chart.
 *
 * Deciding by shape is guesswork; deciding by route is not. If a route is ever
 * given text genuinely written for a user, read it at that call site rather
 * than widening this.
 */
export function historifyError(_error: unknown, fallback: string): string {
  return fallback
}
