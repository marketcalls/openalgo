/**
 * Typing straight onto a chart: a letter starts a symbol search, a digit starts
 * an interval.
 *
 * The rules for when a key is the chart's are the strict ones the drawing
 * shortcuts already follow (`chartMayTakeKey`), plus two of their own. A key
 * with Ctrl, Cmd or Alt held is somebody else's chord: the drawing tools, the
 * price scale and the browser all live there. And the key has to land on the
 * chart, its toolbar or nothing at all: a letter typed while focus sits in the
 * order book or the watchlist belongs to that panel, never to the chart.
 *
 * `0` is left alone on purpose. The chart already reads it as "reset the view",
 * and no interval starts with a zero.
 */

import { chartMayTakeKey } from './drawingKeys'

export type QuickEntryKind = 'symbol' | 'interval'

/** Marks the symbol search's box, so quick entry knows when typing has a home. */
export const SEARCH_INPUT_ATTR = 'data-symbol-search-input'

/** The fields of a key event this reads. */
export interface QuickEntryKey {
  key: string
  target: EventTarget | null
  defaultPrevented?: boolean
  isComposing?: boolean
  repeat?: boolean
  ctrlKey?: boolean
  metaKey?: boolean
  altKey?: boolean
}

/** Where a typed key may start quick entry: the page itself, a chart or its toolbar. */
const CHART_SCOPE = '[data-chart-pane], [data-workspace-toolbar]'

function onChart(target: EventTarget | null): boolean {
  if (!target || typeof (target as Node).nodeType !== 'number') return true
  const node = target as Node
  if (node.nodeType === 9) return true
  const el = node as Element & { ownerDocument?: Document }
  if (el === el.ownerDocument?.body || el === el.ownerDocument?.documentElement) return true
  return !!el.closest?.(CHART_SCOPE)
}

/** Which box a key opens, or null when the key is not quick entry's to take. */
export function quickEntryKind(e: QuickEntryKey): QuickEntryKind | null {
  if (e.defaultPrevented || e.isComposing || e.repeat) return null
  if (e.ctrlKey || e.metaKey || e.altKey) return null
  if (e.key.length !== 1) return null
  const kind: QuickEntryKind | null = /^[1-9]$/.test(e.key)
    ? 'interval'
    : /^[A-Za-z]$/.test(e.key)
      ? 'symbol'
      : null
  if (kind === null) return null
  if (!onChart(e.target)) return null
  if (!chartMayTakeKey(e as Pick<KeyboardEvent, 'target'>)) return null
  return kind
}

export type QuickInterval =
  | { code: string; error?: undefined }
  | { code?: undefined; error: string }

/** How a typed unit reads, keyed by what may be typed for it. */
const UNITS: Record<string, 's' | 'm' | 'h' | 'D' | 'W' | 'M'> = {
  s: 's',
  sec: 's',
  secs: 's',
  m: 'm',
  min: 'm',
  mins: 'm',
  h: 'h',
  hr: 'h',
  hrs: 'h',
  d: 'D',
  day: 'D',
  w: 'W',
  wk: 'W',
  mo: 'M',
  mn: 'M',
}

/**
 * Read what a trader typed into the interval box as one of the broker's codes.
 *
 * A bare number is minutes, because that is what a number on a chart nearly
 * always means: `5` then Enter is five minutes. `1h`, `D`, `W` and `M` read the
 * way the interval menu writes them. Lower-case `m` is minutes and capital `M`
 * is months, which is how the broker's own codes tell the two apart.
 *
 * Only an interval the broker serves is accepted. One it does not is refused
 * with the reason, rather than quietly swapped for the nearest one.
 */
export function parseQuickInterval(text: string, available: readonly string[]): QuickInterval {
  const typed = text.trim().replace(/\s+/g, '')
  if (typed === '') return { error: 'Type an interval, such as 5, 15, 1h or D' }
  if (available.includes(typed)) return { code: typed }
  const match = /^(\d*)([A-Za-z]*)$/.exec(typed)
  if (!match) return { error: 'Type a number of minutes, or a value such as 1h, D or W' }
  const count = match[1] === '' ? 1 : Number(match[1])
  const word = match[2]
  if (!Number.isSafeInteger(count) || count < 1)
    return { error: 'Type a number of minutes, or a value such as 1h, D or W' }
  let unit: 's' | 'm' | 'h' | 'D' | 'W' | 'M' | undefined
  if (word === '') unit = match[1] === '' ? undefined : 'm'
  else if (word === 'M') unit = 'M'
  else unit = UNITS[word.toLowerCase()]
  if (unit === undefined)
    return { error: 'Type a number of minutes, or a value such as 1h, D or W' }
  const candidates =
    unit === 'D' || unit === 'W' || unit === 'M'
      ? count === 1
        ? [unit, `1${unit}`]
        : [`${count}${unit}`]
      : [`${count}${unit}`]
  const found = candidates.find((code) => available.includes(code))
  if (found) return { code: found }
  return {
    error: `Your broker does not offer ${candidates[0]}. Choose one from the interval menu.`,
  }
}
