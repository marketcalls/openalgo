/**
 * Drawings kept per instrument, inside one pane's storage namespace.
 *
 * Every build before this one saved a pane's drawings under one `draw` entry,
 * which outlives the symbol in the pane: a level drawn on one instrument came
 * back on every instrument loaded after it, at the same prices, and deleting it
 * anywhere deleted it everywhere. Now each instrument has its own entry,
 * `draw:NSE:INFY`, beside the pane's other preferences.
 *
 * The draw tier ships this as `InstrumentDrawings` and `migrateUnscopedDrawings`,
 * and the rules here are the same ones: the key is the library's
 * `instrumentDrawingsKey` (exchange and symbol, each URI-encoded), and an
 * unscoped document is filed under the instrument it was saved with only when
 * that instrument has nothing of its own. Two things keep the terminal from
 * calling them directly. The tier is fetched on first use, and a pane that has
 * never drawn must still swap to the next symbol's drawings without paying for
 * it. And the terminal rebuilds its chart on every symbol change, so the swap
 * happens between two charts rather than on one chart's data context, which is
 * the only moment `InstrumentDrawings` follows.
 */

/** The pane-level entry every earlier build wrote, whatever symbol was on screen. */
export const UNSCOPED_DRAWINGS = 'draw'

/**
 * Set once the pane's unscoped entry has been filed under its instrument.
 *
 * The unscoped entry itself is left exactly as it was, so a trader who opens
 * the same browser profile on an older build still finds their drawings. The
 * marker is what stops it being adopted a second time: without it, a pane
 * reopened on another symbol would hand that symbol a copy of the first one's
 * levels.
 */
export const DRAWINGS_SCOPED = 'draw-scoped'

/** An instrument as the pane names it. */
export interface DrawingInstrument {
  symbol?: string
  exchange?: string
}

/** The two members of the pane's preference storage this module needs. */
export interface DrawingsStorage {
  get(key: string): string | null
  set(key: string, value: string): void
}

/**
 * The entry an instrument's drawings are stored under, or null when there is
 * no symbol. Same rule as the library's `instrumentDrawingsKey`, behind a
 * `draw:` prefix: both parts trimmed, case kept, and each part URI-encoded so a
 * colon inside a symbol cannot make two instruments one key.
 */
export function drawingsKey(instrument: DrawingInstrument | null | undefined): string | null {
  const symbol = typeof instrument?.symbol === 'string' ? instrument.symbol.trim() : ''
  if (symbol === '') return null
  const exchange = instrument?.exchange?.trim()
  return `draw:${exchange ? `${encodeURIComponent(exchange)}:` : ''}${encodeURIComponent(symbol)}`
}

/** The pane's saved `symbol` entry as an instrument, or null when it is missing or unreadable. */
export function savedInstrument(raw: string | null): DrawingInstrument | null {
  if (!raw) return null
  try {
    const parsed: unknown = JSON.parse(raw)
    if (!parsed || typeof parsed !== 'object') return null
    const { symbol, exchange } = parsed as { symbol?: unknown; exchange?: unknown }
    if (typeof symbol !== 'string') return null
    return { symbol, exchange: typeof exchange === 'string' ? exchange : '' }
  } catch {
    return null
  }
}

/** Whether stored drawings text holds at least one drawing: a 1.9.x array or a document. */
export function holdsDrawings(raw: string | null): boolean {
  if (!raw) return false
  try {
    const parsed: unknown = JSON.parse(raw)
    if (Array.isArray(parsed)) return parsed.length > 0
    const drawings = (parsed as { drawings?: unknown } | null)?.drawings
    return Array.isArray(drawings) && drawings.length > 0
  } catch {
    return false
  }
}

/**
 * File the pane's unscoped drawings under `key`, once.
 *
 * The text is copied as it was stored, byte for byte, so whatever reads it next
 * (the tier's own migration, for a 1.9.x array) sees exactly what the earlier
 * build wrote. An instrument that already has an entry of its own keeps it,
 * even an empty one: that is a trader having cleared it. Returns whether
 * anything was written under `key`.
 */
export function adoptUnscopedDrawings(storage: DrawingsStorage, key: string): boolean {
  if (storage.get(DRAWINGS_SCOPED) === '1') return false
  const raw = storage.get(UNSCOPED_DRAWINGS)
  const adopt = raw !== null && holdsDrawings(raw) && storage.get(key) === null
  if (adopt) storage.set(key, raw)
  storage.set(DRAWINGS_SCOPED, '1')
  return adopt
}

/**
 * The stored text for the instrument a pane opens on: its own entry, after the
 * one-time adoption of the unscoped one. With no instrument known, the unscoped
 * entry is what the pane shows until its first symbol lands, unless it has
 * already been filed away.
 */
export function openingDrawings(storage: DrawingsStorage, key: string | null): string | null {
  if (key === null) {
    return storage.get(DRAWINGS_SCOPED) === '1' ? null : storage.get(UNSCOPED_DRAWINGS)
  }
  adoptUnscopedDrawings(storage, key)
  return storage.get(key)
}
