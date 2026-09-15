/**
 * The screener's vocabulary: what a filter is, and what crosses the worker boundary.
 *
 * Kept free of React, of `openalgo-charts` and of anything that touches the DOM,
 * because both realms import it -- the page to build filters and render results,
 * the worker to evaluate them -- and a worker cannot pull a component tree in
 * behind a type.
 */

/** One bar, as `openalgo-charts` expects it. `time` is UTC **seconds**. */
export interface Bar {
  time: number
  open: number
  high: number
  low: number
  close: number
  volume?: number
}

/** What `calc` returns: one column per key, each exactly `bars.length` long. */
export type IndicatorValues = Record<string, (number | null)[]>

/** The wire shape of `/historify/api/bulk-ohlcv`. Columns, not bar objects. */
export interface BarColumns {
  t: number[]
  o: number[]
  h: number[]
  l: number[]
  c: number[]
  v?: number[]
}

export interface BulkOhlcvResponse {
  status: string
  message?: string
  interval: string
  bars: number
  live: boolean
  data: Record<string, BarColumns>
  missing: { symbol: string; exchange: string }[]
}

/** Columnar arrays back into the bar objects an indicator reads. */
export function toBars(columns: BarColumns): Bar[] {
  const bars: Bar[] = new Array(columns.t.length)
  for (let i = 0; i < columns.t.length; i++) {
    bars[i] = {
      time: columns.t[i],
      open: columns.o[i],
      high: columns.h[i],
      low: columns.l[i],
      close: columns.c[i],
      volume: columns.v ? columns.v[i] : undefined,
    }
  }
  return bars
}

// ---------------------------------------------------------------------------
// Filters
// ---------------------------------------------------------------------------

export type CompareOp = '>' | '<' | '>=' | '<=' | 'crossesAbove' | 'crossesBelow' | 'between'

export const COMPARE_LABELS: Record<CompareOp, string> = {
  '>': 'greater than',
  '<': 'less than',
  '>=': 'at least',
  '<=': 'at most',
  crossesAbove: 'crosses above',
  crossesBelow: 'crosses below',
  between: 'between',
}

/** The right-hand side of a comparison: a fixed number, or another column. */
export type Operand = { kind: 'const'; value: number } | { kind: 'column'; key: string }

export type Filter =
  | {
      id: string
      kind: 'value'
      column: string
      op: CompareOp
      rhs: Operand
      /** Upper bound, `between` only. */
      rhs2?: Operand
    }
  | { id: string; kind: 'alert'; alertId: string }

/** An indicator's declared alert, the analogue of Pine's `alertcondition()`. */
export interface AlertSpec {
  id: string
  title?: string
  when(ctx: {
    bars: Bar[]
    values: IndicatorValues
    settings: Record<string, unknown>
    index: number
  }): boolean
}

function at(values: IndicatorValues, key: string, index: number): number | null {
  const column = values[key]
  if (!column) return null
  const raw = column[index]
  return typeof raw === 'number' && Number.isFinite(raw) ? raw : null
}

function operandAt(operand: Operand, values: IndicatorValues, index: number): number | null {
  if (operand.kind === 'const') {
    return Number.isFinite(operand.value) ? operand.value : null
  }
  return at(values, operand.key, index)
}

/**
 * Does this symbol pass every filter, judged on its most recent bar?
 *
 * Filters combine with AND, matching the Pine Screener. Crossovers are the only
 * rule that reads further back than the last bar, and they read exactly one bar.
 *
 * A missing reading -- null, NaN, a column the indicator never produced -- makes
 * a filter **false**. This is the one defensible default: an indicator inside its
 * warm-up window has no value yet, and treating "no value" as a pass fills the
 * results with precisely the symbols that had too little history to judge.
 *
 * ponytail: AND only. OR groups when someone asks for them; until then two scans
 * is the workaround and this stays one loop.
 */
export function evaluateFilters(
  filters: Filter[],
  bars: Bar[],
  values: IndicatorValues,
  settings: Record<string, unknown>,
  alerts: AlertSpec[]
): boolean {
  const i = bars.length - 1
  if (i < 0) return false

  for (const filter of filters) {
    if (filter.kind === 'alert') {
      const alert = alerts.find((a) => a.id === filter.alertId)
      if (!alert?.when({ bars, values, settings, index: i })) return false
      continue
    }

    const left = at(values, filter.column, i)
    if (left === null) return false

    if (filter.op === 'crossesAbove' || filter.op === 'crossesBelow') {
      if (i < 1) return false
      const leftPrev = at(values, filter.column, i - 1)
      const rightPrev = operandAt(filter.rhs, values, i - 1)
      const right = operandAt(filter.rhs, values, i)
      if (leftPrev === null || rightPrev === null || right === null) return false
      const crossed =
        filter.op === 'crossesAbove'
          ? leftPrev <= rightPrev && left > right
          : leftPrev >= rightPrev && left < right
      if (!crossed) return false
      continue
    }

    if (filter.op === 'between') {
      const low = operandAt(filter.rhs, values, i)
      const high = filter.rhs2 ? operandAt(filter.rhs2, values, i) : null
      if (low === null || high === null) return false
      if (left < low || left > high) return false
      continue
    }

    const right = operandAt(filter.rhs, values, i)
    if (right === null) return false
    if (filter.op === '>' && !(left > right)) return false
    if (filter.op === '<' && !(left < right)) return false
    if (filter.op === '>=' && !(left >= right)) return false
    if (filter.op === '<=' && !(left <= right)) return false
  }

  return true
}

// ---------------------------------------------------------------------------
// Worker protocol
// ---------------------------------------------------------------------------

export interface ScanSymbol {
  symbol: string
  exchange: string
}

export interface ScanRow extends ScanSymbol {
  /** Last bar's close, straight from the series. */
  close: number | null
  /** Percent move over the previous bar. */
  changePct: number | null
  /** UTC seconds of the newest bar, so staleness is visible per row. */
  lastBarTime: number | null
  /** Every column `calc` produced, read at the last bar. */
  values: Record<string, number | null>
  /** Alert ids that fired on the last bar. */
  alerts: string[]
  /** Set instead of the rest when this symbol's calc threw. */
  error?: string
}

export interface ScanRequest {
  type: 'scan'
  runId: number
  csrf: string
  symbols: ScanSymbol[]
  interval: string
  bars: number
  live: boolean
  indicatorId: string
  settings: Record<string, unknown>
  filters: Filter[]
}

export type ScanCommand = ScanRequest | { type: 'cancel'; runId: number }

export type ScanEvent =
  | { type: 'progress'; runId: number; done: number; total: number }
  | {
      type: 'columns'
      runId: number
      plots: { key: string; title: string }[]
      extra: string[]
    }
  | { type: 'rows'; runId: number; rows: ScanRow[] }
  | { type: 'missing'; runId: number; missing: ScanSymbol[] }
  | { type: 'problem'; runId: number; message: string }
  | { type: 'done'; runId: number; matched: number; scanned: number; failed: number }
  | { type: 'error'; runId: number; message: string }

/** How many symbols one request and one calc pass covers. */
export const SCAN_CHUNK = 50
