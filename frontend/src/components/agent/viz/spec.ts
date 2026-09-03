/**
 * Reading a viz frame's `spec`, for every renderer that draws one.
 *
 * A `spec` arrives as JSON off the wire and is carried through `VizBlock`
 * unvalidated on purpose, so each renderer reads its own payload. Reading it is
 * still the same four questions every time: is this an object, is this a
 * non-empty string, is this a finite number, and are these bars drawable. These
 * lived inside `CandleViz` while it was the only price renderer; the instrument
 * card needs the same four, and a second copy of them is how the two drift.
 *
 * The rules they encode are the point, not the three lines each takes:
 *
 * - **A number that cannot be read is absent, never zero.** A bar plotted at
 *   zero is a lie; a bar left out is a gap. The numeric-string branch is there
 *   because a JSON encoder somewhere along the way may have produced one.
 * - **A bar with no timestamp or no close is dropped.** It can be neither
 *   placed nor valued, and the backend drops these too.
 * - **Two bars sharing a timestamp collide** in the data layer, which gives one
 *   logical index per timestamp. Only an already-wrong frame contains a
 *   repeat, and dropping it is what keeps that frame drawable instead of
 *   throwing.
 */

import type { Bar } from 'openalgo-charts'

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
