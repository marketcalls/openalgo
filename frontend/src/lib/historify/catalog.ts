/**
 * The downloaded-data catalog, reduced to what a symbol picker needs.
 *
 * The catalog is one row per symbol, exchange and interval, so a symbol held at
 * both 1m and D appears twice and an option chain appears once per contract per
 * interval. A picker wants one row per instrument, carrying which stored
 * intervals it has, because that is what decides the timeframes it can draw.
 *
 * There is no server route for this. `get_available_symbols()` exists in
 * `database/historify_db.py` and has no caller, no service and no route, so the
 * reduction is done here, over the catalog the page already fetched.
 */

import type { CatalogMetadataRow, CatalogRow } from '@/api/historify'
import { type SourceInterval, storedSources } from '@/lib/historify/intervals'

export interface CatalogSymbol {
  symbol: string
  exchange: string
  /** Long name from the master contract, when the metadata join supplied one. */
  name?: string
  expiry?: string
  strike?: number
  instrumenttype?: string
  /** Which stored intervals exist, which is what gates the timeframe list. */
  sources: Set<SourceInterval>
  /**
   * Newest stored candle per source interval, in UTC seconds.
   *
   * This is the store's horizon, and a chart needs it before its first fetch.
   * The engine builds its opening window backwards from the wall clock, so a
   * dataset whose newest candle is a few days old, which is every dataset over
   * a weekend, opens on an empty window and reports having no bars at all.
   */
  lastBySource: Partial<Record<SourceInterval, number>>
  /** Total candles held across every interval, for ordering by substance. */
  records: number
}

/**
 * Catalog rows to one entry per instrument.
 *
 * Sorted by exchange then symbol, which is the order the catalog route already
 * returns and the order a trader scanning a list expects. A row with neither 1m
 * nor D stored is kept: it is in the catalog, so something was downloaded, and
 * hiding it would leave a user hunting for a symbol they know they have.
 */
export function toCatalogSymbols(
  rows: readonly (CatalogRow | CatalogMetadataRow)[]
): CatalogSymbol[] {
  const byKey = new Map<string, CatalogSymbol>()

  for (const row of rows) {
    if (!row?.symbol || !row?.exchange) continue
    const key = `${row.symbol}:${row.exchange}`
    const meta = row as CatalogMetadataRow
    const existing = byKey.get(key)

    if (existing) {
      for (const source of storedSources([row.interval])) {
        existing.sources.add(source)
        const last = Number(row.last_timestamp)
        if (Number.isFinite(last) && last > (existing.lastBySource[source] ?? 0)) {
          existing.lastBySource[source] = last
        }
      }
      existing.records += Number(row.record_count) || 0
      // The metadata join is per symbol, not per interval, but a row may carry
      // it where an earlier one did not.
      existing.name ??= meta.name || undefined
      existing.expiry ??= meta.expiry || undefined
      existing.instrumenttype ??= meta.instrumenttype || undefined
      if (existing.strike === undefined && Number.isFinite(meta.strike))
        existing.strike = meta.strike
      continue
    }

    byKey.set(key, {
      symbol: row.symbol,
      exchange: row.exchange,
      name: meta.name || undefined,
      expiry: meta.expiry || undefined,
      strike: Number.isFinite(meta.strike) ? meta.strike : undefined,
      instrumenttype: meta.instrumenttype || undefined,
      sources: storedSources([row.interval]),
      lastBySource: Object.fromEntries(
        [...storedSources([row.interval])]
          .filter(() => Number.isFinite(Number(row.last_timestamp)))
          .map((source) => [source, Number(row.last_timestamp)])
      ),
      records: Number(row.record_count) || 0,
    })
  }

  return [...byKey.values()].sort(
    (a, b) => a.exchange.localeCompare(b.exchange) || a.symbol.localeCompare(b.symbol)
  )
}

/** One instrument from the reduced list, or null when it is not held. */
export function findCatalogSymbol(
  symbols: readonly CatalogSymbol[],
  symbol: string,
  exchange: string
): CatalogSymbol | null {
  return symbols.find((s) => s.symbol === symbol && s.exchange === exchange) ?? null
}
