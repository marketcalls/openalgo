/**
 * The sizes of the rows and columns of a multi-chart grid, as weights.
 *
 * A grid track is `<weight>fr`, so a weight is a share of the space rather than
 * pixels: a split dragged on a laptop keeps its proportions on a wide monitor,
 * and a window resize never pins one chart while the others shrink. The weights
 * are what a workspace document already stores (`rowWeights`, `columnWeights`),
 * so a named workspace saves them with no change to its format.
 *
 * The unnamed grid keeps its weights in this browser, per layout, under one key.
 * A layout with nothing stored opens with the preset's own sizes, which is how
 * every grid opened before sizes could be dragged.
 */

export interface GridWeights {
  columns: number[]
  rows: number[]
}

/** One draggable divider: a boundary between two tracks, and the span of it that is not inside a chart. */
export interface DividerSegment {
  axis: 'column' | 'row'
  /** The boundary after track `index` (between `index` and `index + 1`). */
  index: number
  /** First and last track across the divider that it runs along, inclusive. */
  from: number
  to: number
}

const SIZES_KEY = 'oa-trading-layout-sizes'
/** The engine's own ceiling on a workspace weight. */
const MAX_WEIGHT = 1000

/** `1.4fr 1fr` to `[1.4, 1]`. Anything that is not a positive `fr` track reads as 1. */
export function parseTracks(template: string): number[] {
  return template
    .trim()
    .split(/\s+/)
    .map((track) => {
      const value = Number(track.replace(/fr$/, ''))
      return Number.isFinite(value) && value > 0 ? value : 1
    })
}

/** `[1.4, 1]` to `1.4fr 1fr`, rounded so a stored split does not grow fifteen decimals. */
export function tracksTemplate(weights: readonly number[]): string {
  return weights.map((weight) => `${round(weight)}fr`).join(' ')
}

function round(value: number): number {
  return Math.round(value * 10_000) / 10_000
}

/** `"a b" "a c"` to `[['a','b'],['a','c']]`. */
export function parseAreas(areas: string): string[][] {
  return [...areas.matchAll(/"([^"]+)"/g)].map((match) => match[1].trim().split(/\s+/))
}

/**
 * Where dividers go: every boundary between two tracks, along the stretches
 * where the cells on either side belong to different charts. In the 1 + 2
 * layout the row boundary runs only beside the two small charts, because the
 * large one spans it and there is nothing there to divide.
 */
export function dividerSegments(cells: readonly (readonly string[])[]): DividerSegment[] {
  const out: DividerSegment[] = []
  const rows = cells.length
  const columns = cells[0]?.length ?? 0
  const push = (axis: DividerSegment['axis'], index: number, along: boolean[]) => {
    let start = -1
    along.forEach((split, position) => {
      if (split && start < 0) start = position
      if (!split && start >= 0) {
        out.push({ axis, index, from: start, to: position - 1 })
        start = -1
      }
    })
    if (start >= 0) out.push({ axis, index, from: start, to: along.length - 1 })
  }
  for (let column = 0; column < columns - 1; column++)
    push(
      'column',
      column,
      cells.map((row) => row[column] !== row[column + 1])
    )
  for (let row = 0; row < rows - 1; row++)
    push(
      'row',
      row,
      cells[row].map((name, column) => name !== cells[row + 1][column])
    )
  return out
}

/**
 * Move the boundary after track `index` by `delta` pixels.
 *
 * Only the two tracks either side change, and neither goes below `minPx`: a
 * drag past the limit stops at it rather than swapping the charts over. The
 * result is in the same total weight as the input, so the other tracks keep
 * exactly the share they had.
 */
export function resizeTracks(
  weights: readonly number[],
  index: number,
  delta: number,
  totalPx: number,
  minPx: number
): number[] {
  const sum = weights.reduce((total, weight) => total + weight, 0)
  if (index < 0 || index >= weights.length - 1 || sum <= 0 || totalPx <= 0) return [...weights]
  const px = weights.map((weight) => (weight / sum) * totalPx)
  const pair = px[index] + px[index + 1]
  const floor = Math.min(minPx, pair / 2)
  const first = Math.min(pair - floor, Math.max(floor, px[index] + delta))
  px[index] = first
  px[index + 1] = pair - first
  return px.map((size) => round((size / totalPx) * sum))
}

/** Whether two weight lists draw the same split. */
export function sameWeights(a: readonly number[], b: readonly number[]): boolean {
  if (a.length !== b.length) return false
  const sa = a.reduce((total, weight) => total + weight, 0)
  const sb = b.reduce((total, weight) => total + weight, 0)
  return a.every((weight, index) => Math.abs(weight / sa - b[index] / sb) < 1e-4)
}

function validWeights(value: unknown, count: number): value is number[] {
  return (
    Array.isArray(value) &&
    value.length === count &&
    value.every((weight) => typeof weight === 'number' && weight > 0 && weight <= MAX_WEIGHT)
  )
}

type Store = Pick<Storage, 'getItem' | 'setItem'>

function readAll(store: Store): Record<string, unknown> {
  try {
    const parsed: unknown = JSON.parse(store.getItem(SIZES_KEY) ?? '{}')
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed)
      ? (parsed as Record<string, unknown>)
      : {}
  } catch {
    return {}
  }
}

/** The unnamed grid's stored split for a layout, or the preset's own when nothing usable is stored. */
export function readGridWeights(
  store: Store,
  layoutId: string,
  defaults: GridWeights
): GridWeights {
  const saved = readAll(store)[layoutId] as Partial<GridWeights> | undefined
  const columns = saved?.columns
  const rows = saved?.rows
  return {
    columns: validWeights(columns, defaults.columns.length) ? columns : [...defaults.columns],
    rows: validWeights(rows, defaults.rows.length) ? rows : [...defaults.rows],
  }
}

/** Keep the unnamed grid's split for a layout; the preset's own split clears the entry. */
export function writeGridWeights(
  store: Store,
  layoutId: string,
  weights: GridWeights,
  defaults: GridWeights
): void {
  const all = readAll(store)
  if (sameWeights(weights.columns, defaults.columns) && sameWeights(weights.rows, defaults.rows))
    delete all[layoutId]
  else all[layoutId] = { columns: weights.columns.map(round), rows: weights.rows.map(round) }
  try {
    store.setItem(SIZES_KEY, JSON.stringify(all))
  } catch {
    // Storage refused: the split holds until the page is reloaded.
  }
}
