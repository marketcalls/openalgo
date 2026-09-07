/**
 * Reading a viz frame's `spec`, for every renderer that draws one.
 *
 * A `spec` arrives as JSON off the wire and is carried through `VizBlock`
 * unvalidated on purpose, so each renderer reads its own payload. Reading it is
 * still the same few questions every time: is this an object, is this a
 * non-empty string, is this a finite number, is this a number that means
 * anything, are these bars drawable, and are these ladder rows real orders.
 * These lived inside `CandleViz` while it was the only price renderer; the
 * instrument card needed the same ones, the two live cards need them again, and
 * a second copy of any of them is how the set drifts.
 *
 * The rules they encode are the point, not the three lines each takes:
 *
 * - **A number that cannot be read is absent, never zero.** A bar plotted at
 *   zero is a lie; a bar left out is a gap. The numeric-string branch is there
 *   because a JSON encoder somewhere along the way may have produced one.
 * - **Zero spells absence for almost every market field.** No instrument
 *   trades at zero, an open interest of zero is a contract nobody holds, and a
 *   bid of zero is a book with no resting order rather than one offering to
 *   pay nothing. The last traded price is the one exception and its callers
 *   handle it, because there "nothing has printed yet" and "no quote came
 *   back" are different sentences.
 * - **A bar with no timestamp or no close is dropped.** It can be neither
 *   placed nor valued, and the backend drops these too.
 * - **Two bars sharing a timestamp collide** in the data layer, which gives one
 *   logical index per timestamp. Only an already-wrong frame contains a
 *   repeat, and dropping it is what keeps that frame drawable instead of
 *   throwing.
 * - **A ladder row with neither a price nor a size is padding**, not an order.
 *   A feed fills a fixed-width book with them, and drawing five bars of
 *   nothing beside one real bid reads as a book that exists.
 */

import type { Bar } from 'openalgo-charts'

/** Most depth levels read from one side of a book. The backend caps at five. */
export const MAX_DEPTH_LEVELS = 5

/** An object, and not an array. Anything else is `null`. */
export function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null
}

/** A non-empty trimmed string, or `null`. */
export function asText(value: unknown): string | null {
  if (typeof value !== 'string') return null
  const trimmed = value.trim()
  return trimmed === '' ? null : trimmed
}

/**
 * A finite number, accepting the numeric string a JSON encoder somewhere along
 * the way may have produced. Anything else, `null` and `NaN` included, is
 * absent rather than zero.
 */
export function asNumber(value: unknown): number | null {
  if (typeof value === 'number') return Number.isFinite(value) ? value : null
  if (typeof value === 'string') {
    const trimmed = value.trim()
    if (trimmed === '') return null
    const parsed = Number(trimmed)
    return Number.isFinite(parsed) ? parsed : null
  }
  return null
}

/**
 * A number that is present and not zero.
 *
 * For nearly every market field a renderer reads, zero spells absence rather
 * than a measurement, and the backend applies the same rule before it sends.
 * This is also what keeps a live tick carrying only depth from overwriting a
 * real served value with `0.00`.
 *
 * @param value - The field, exactly as it came off the wire.
 * @returns The number, or `undefined` when it is missing, unreadable or zero.
 */
export function nonZero(value: unknown): number | undefined {
  const parsed = asNumber(value)
  return parsed === null || parsed === 0 ? undefined : parsed
}

/** One resting order, or one side of a top-of-book. Either half may be absent. */
export interface DepthRow {
  price?: number
  quantity?: number
}

/**
 * Read one side of an order book.
 *
 * @param value - A `bids` or `asks` list, from a spec or from a live tick.
 * @returns Up to `MAX_DEPTH_LEVELS` real levels, best first. Padding rows the
 *   feed emits to fill a fixed-width book are dropped, because they are not
 *   orders and a card drawn from them describes a book that is not there.
 */
export function parseLevels(value: unknown): DepthRow[] {
  if (!Array.isArray(value)) return []
  const rows: DepthRow[] = []
  for (const entry of value) {
    if (rows.length >= MAX_DEPTH_LEVELS) break
    const row = asRecord(entry)
    if (!row) continue
    const price = nonZero(row.price)
    const quantity = nonZero(row.quantity)
    if (price === undefined && quantity === undefined) continue
    rows.push({ price, quantity })
  }
  return rows
}

/**
 * Read a list of OHLC bars, oldest first and one per timestamp.
 *
 * @param value - The `bars` field of a spec, exactly as it came off the wire.
 * @returns The drawable bars. Empty when the field held none, which every
 *   caller reads as "there is no chart here" rather than as an error.
 */
export function parseBars(value: unknown): Bar[] {
  if (!Array.isArray(value)) return []
  const bars: Bar[] = []
  for (const entry of value) {
    const row = asRecord(entry)
    if (!row) continue
    const time = asNumber(row.time)
    const close = asNumber(row.close)
    if (time === null || close === null) continue
    const bar: Bar = {
      time,
      open: asNumber(row.open) ?? close,
      high: asNumber(row.high) ?? close,
      low: asNumber(row.low) ?? close,
      close,
    }
    const volume = asNumber(row.volume)
    if (volume !== null) bar.volume = volume
    bars.push(bar)
  }
  bars.sort((a, b) => a.time - b.time)
  return bars.filter((bar, index) => index === 0 || bar.time > bars[index - 1].time)
}
