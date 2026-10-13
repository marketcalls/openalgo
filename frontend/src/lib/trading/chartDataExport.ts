/**
 * What goes into a chart's CSV download.
 *
 * The engine already writes the file (`exportChartDataCsv`): UTC seconds, the
 * unrounded bars, every study and every comparison close, and nothing a replay
 * has not yet revealed. This only turns the trader's three choices into its
 * options: which bars, which studies, and whether the comparison closes come
 * along.
 */
import type { Chart, ChartDataCsvOptions } from 'openalgo-charts'

export interface DataExportOptions {
  /** Every loaded bar (the default), or only those on screen. */
  range?: 'all' | 'visible'
  /** Study instance ids to include, in this order. Absent means every study. */
  studies?: readonly string[]
  /** False leaves the comparison closes out. */
  comparisons?: boolean
}

/** The span of bar times on screen, or null when no loaded bar is. */
export function visibleTimes(
  chart: Pick<Chart, 'getVisibleLogicalRange' | 'primaryBars' | 'dataLayer'>
): { from: number; to: number } | null {
  const view = chart.getVisibleLogicalRange()
  const axis = chart.dataLayer
  const first = Math.max(0, Math.ceil(view.from))
  const last = Math.min(axis.length - 1, Math.floor(view.to))
  const tail = chart.primaryBars().at(-1)?.time
  if (first > last || tail === undefined) return null
  const from = axis.indexToTime(first)
  const end = axis.indexToTime(last)
  if (from === undefined || end === undefined) return null
  const to = Math.min(end, tail)
  return Number.isFinite(from) && Number.isFinite(to) && from <= to ? { from, to } : null
}

/** The engine's options for one download. */
export function csvOptions(
  chart: Pick<Chart, 'getVisibleLogicalRange' | 'primaryBars' | 'dataLayer'>,
  options: DataExportOptions
): ChartDataCsvOptions {
  const out: { -readonly [K in keyof ChartDataCsvOptions]: ChartDataCsvOptions[K] } = {}
  if (options.studies !== undefined)
    out.indicators = options.studies.length ? options.studies : false
  if (options.comparisons === false) out.comparisons = []
  if (options.range === 'visible') {
    const range = visibleTimes(chart)
    if (!range) throw new Error('No bars are on screen to export')
    out.range = range
  }
  return out
}
