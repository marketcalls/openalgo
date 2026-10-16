/**
 * OpenAlgo REST adapter (ARCHITECTURE.md §10.0). The chart depends only on the
 * `DataFeed` interface; this is the only file that knows OpenAlgo's REST shape.
 *
 * History endpoint: POST `${baseUrl}/api/v1/history`.
 * Search endpoint: POST `${baseUrl}/api/v1/search`.
 * The request fields and interval mapping are pinned by offline adapter
 * fixtures. Response timestamps accept epoch seconds, epoch milliseconds,
 * offset-qualified timestamps and unqualified IST date/time strings.
 */
import type { Bar } from '../model/bar';
import type { BarsRequest, DataFeed, SymbolMatch, SymbolSearchRequest } from './types';
import { epochMsToUtcSeconds, istStringToUtcSeconds, utcSecondsToIstDateString } from './time';
import { withHistoryDeadline } from './request-pool';
import { dataVariantError, unsupportedDataVariant } from './data-variant';
import type { LooseOptional } from '../helpers/types';

export interface OpenAlgoConfig {
  baseUrl: string;
  apiKey: string;
  /** Injectable fetch (defaults to global fetch); lets the adapter be tested offline. */
  fetchImpl?: typeof fetch;
  /**
   * Instrument capability from host metadata. Explicit false omits the API's
   * placeholder OI column before it can become a misleading cash reading.
   * Missing/unknown capability preserves finite observations, including zero.
   */
  hasOpenInterest?(request: Readonly<BarsRequest>): boolean | undefined;
}

interface HistoryRow {
  timestamp?: number | string;
  time?: number | string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
  /** Present on a derivatives response; the platform always sends the column. */
  oi?: number;
}

interface HistoryResponse {
  status?: string;
  message?: string;
  data?: HistoryRow[];
}

/** Pure: coerce a row timestamp (epoch s / epoch ms / IST string) to UTC seconds. */
export function rowTimeToUtcSeconds(value: number | string): number {
  if (typeof value === 'number') {
    // Heuristic: > 1e12 is almost certainly milliseconds.
    return value > 1e12 ? epochMsToUtcSeconds(value) : Math.floor(value);
  }
  // Numeric-looking string?
  const asNum = Number(value);
  if (value.trim() !== '' && !Number.isNaN(asNum) && !/[-T :]/.test(value.trim())) {
    return asNum > 1e12 ? epochMsToUtcSeconds(asNum) : Math.floor(asNum);
  }
  if (/(?:Z|[+-]\d{2}:?\d{2})$/i.test(value.trim())) {
    const ms = Date.parse(value.trim().replace(' ', 'T'));
    if (Number.isFinite(ms)) return epochMsToUtcSeconds(ms);
  }
  return istStringToUtcSeconds(value);
}

/** Pure: map an OpenAlgo history response into sorted internal bars. */
export function mapHistoryResponse(json: HistoryResponse, hasOpenInterest?: boolean): Bar[] {
  if (json.status === 'error') throw new Error(json.message ?? 'OpenAlgo history request failed');
  const rows = json.data ?? [];
  const bars: Bar[] = [];
  for (const r of rows) {
    const ts = r.timestamp ?? r.time;
    if (ts === undefined) continue;
    // A row without volume leaves it undefined, which a Bar reads as absent.
    bars.push({
      time: rowTimeToUtcSeconds(ts),
      open: r.open,
      high: r.high,
      low: r.low,
      close: r.close,
      volume: r.volume,
      ...(hasOpenInterest !== false && Number.isFinite(r.oi) ? { oi: r.oi } : {}),
    } satisfies LooseOptional<Bar> as Bar);
  }
  return bars.sort((a, b) => a.time - b.time);
}

interface SearchResponse {
  status?: string;
  message?: unknown;
  data?: unknown;
}

/** The platform ranks its answer, so the first rows are the closest. */
const SEARCH_ROWS = 50;

/**
 * Map a search answer onto picker results. The options of one underlying and
 * expiry on one exchange share a row that opens onto them, so a search for an
 * index lists its expiries rather than hundreds of strikes.
 */
function mapSearchResponse(json: SearchResponse): SymbolMatch[] {
  if (json.status === 'error') throw new Error(typeof json.message === 'string' ? json.message : 'openalgo-charts: symbol search failed');
  const hits: SymbolMatch[] = [];
  const groups = new Map<string, SymbolMatch[]>();
  for (const row of Array.isArray(json.data) ? json.data as Array<Record<string, unknown> | null> : []) {
    const text = (key: string): string => typeof row?.[key] === 'string' ? (row[key] as string).trim() : '';
    const [symbol, exchange, name, expiry] = [text('symbol'), text('exchange'), text('name'), text('expiry')];
    if (symbol === '') continue;
    // The platform's symbology: a contract has an expiry, and an option's symbol ends in CE or PE.
    const option = expiry !== '' && /(?:CE|PE)$/.test(symbol);
    const hit: SymbolMatch = {
      symbol, ...(exchange ? { exchange } : {}), ...(name ? { name } : {}),
      assetClass: exchange.endsWith('_INDEX') ? 'Index' : expiry === '' ? 'Equity' : option ? 'Options' : 'Futures',
    };
    if (!option) { hits.push(hit); continue; }
    const key = `${exchange}\n${name}\n${expiry}`;
    let contracts = groups.get(key);
    if (contracts === undefined) {
      groups.set(key, contracts = []);
      const label = `${name} ${expiry}`.trim();
      hits.push({ symbol: label, ...(exchange ? { exchange } : {}), assetClass: 'Options', contractGroup: { label, contracts } });
    }
    contracts.push(hit);
  }
  // An expiry with one option lists that option itself.
  return hits.slice(0, SEARCH_ROWS).map(hit => hit.contractGroup?.contracts.length === 1 ? hit.contractGroup.contracts[0]! : hit);
}

export class OpenAlgoDataFeed implements DataFeed {
  private readonly _config: OpenAlgoConfig;
  private readonly _fetch: typeof fetch;

  public constructor(config: OpenAlgoConfig) {
    this._config = config;
    // Bind the global fetch to the global object: calling `window.fetch` as a
    // stored method (`this._fetch(...)`) throws "Illegal invocation" in browsers.
    const f = config.fetchImpl ?? (typeof fetch !== 'undefined' ? fetch.bind(globalThis) : undefined);
    if (f === undefined) throw new Error('openalgo-charts: no fetch available; pass config.fetchImpl');
    this._fetch = f;
  }

  public async getBars(req: BarsRequest): Promise<Bar[]> {
    // The history API has one series per instrument. Another variant would be
    // that series under the wrong label, so it is refused before any request.
    const unsupported = unsupportedDataVariant(undefined, req.variant);
    if (unsupported) throw dataVariantError(unsupported, req.variant);
    const hasOpenInterest = this._config.hasOpenInterest?.(req);
    // OpenAlgo /api/v1/history requires start_date/end_date as IST YYYY-MM-DD
    // (mandatory). Convert the internal UTC-seconds range to IST date strings.
    const { from, to } = req;
    if (from === undefined || to === undefined) {
      throw new Error('openalgo-charts: getBars requires `from` and `to` (UTC seconds): OpenAlgo history needs a date range');
    }
    return withHistoryDeadline(req, async signal => {
      const res = await this._fetch(`${this._config.baseUrl}/api/v1/history`, {
        method: 'POST',
        signal,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          apikey: this._config.apiKey,
          symbol: req.symbol,
          exchange: req.exchange,
          interval: ({ '1d': 'D', '1D': 'D', '1w': 'W', '1W': 'W', '1M': 'M', MN: 'M' } as Record<string, string>)[req.interval] ?? req.interval,
          start_date: utcSecondsToIstDateString(from),
          end_date: utcSecondsToIstDateString(to),
        }),
      });
      if (!res.ok) throw new Error(`openalgo-charts: history request failed (${res.status})`);
      return mapHistoryResponse((await res.json()) as HistoryResponse, hasOpenInterest);
    });
  }

  /** Instruments matching `request.query` on every exchange, in the order the platform ranks them. */
  public async searchSymbols(request: SymbolSearchRequest): Promise<SymbolMatch[]> {
    // The platform refuses an empty query; there is nothing to ask it.
    if (request.query.trim() === '') return [];
    return withHistoryDeadline(request, async signal => {
      const res = await this._fetch(`${this._config.baseUrl}/api/v1/search`, {
        method: 'POST',
        signal,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ apikey: this._config.apiKey, query: request.query }),
      });
      if (!res.ok) throw new Error(`openalgo-charts: symbol search failed (${res.status})`);
      return mapSearchResponse((await res.json()) as SearchResponse);
    });
  }

  // Note: this is a history-only feed, so `subscribeBars` is intentionally NOT
  // implemented (the optional DataFeed method is omitted, so callers can feature-
  // detect it). For live bars use `OpenAlgoLiveDataFeed` (REST + WS + candle
  // builder) or feed `OpenAlgoWsFeed` ticks through `CandleBuilder` into `series.update()`.
}
