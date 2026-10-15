/**
 * Chart-type catalogue for the trading terminal: the dropdown
 * groups, each type's icon, its underlying openalgo-charts series, and (for
 * movement-driven types) the transform the chart applies to the raw bars.
 */

import type { Bar, SeriesTransformSpec } from 'openalgo-charts'
// Registers the in-chart transforms the specs below name, and the point and
// figure and Kagi renderers. Imported here, beside the catalogue that names
// them, so every chart reading this catalogue can apply them.
import 'openalgo-charts/transform'
import type { ReactNode } from 'react'
import { ChromeIcon, hasChromeIcon, lineStroke24 } from './glyphs'

export interface ChartTypeDef {
  value: string
  label: string
  iconKey: string
  series: string
  /**
   * Movement-driven types: the transform the chart applies to the raw bars,
   * for a box (or range, or reversal) sized from the instrument's price. The
   * chart forms the elements again on every tick, so a brick appears as the
   * bar that completes it arrives. `value` stays the saved name, which is why
   * it is not always the transform's own id (`range` is `range-bars`).
   */
  transform?: (boxSize: number) => SeriesTransformSpec
  /** Baseline needs a baseValue in its series style. */
  baseline?: boolean
}

/** Ordered groups (separators between them), matching the dropdown layout. */
export const CHART_TYPE_GROUPS: ChartTypeDef[][] = [
  [
    { value: 'bar', label: 'Bars (OHLC)', iconKey: 'chart-bar', series: 'bar' },
    { value: 'candlestick', label: 'Candles', iconKey: 'chart-candlestick', series: 'candlestick' },
    {
      value: 'hollow-candle',
      label: 'Hollow Candles',
      iconKey: 'chart-hollow-candle',
      series: 'hollow-candle',
    },
    {
      value: 'volume-candle',
      label: 'Volume Candles',
      iconKey: 'chart-volume-candle',
      series: 'volume-candle',
    },
    { value: 'high-low', label: 'High-Low', iconKey: 'chart-high-low', series: 'high-low' },
  ],
  [
    { value: 'line', label: 'Line', iconKey: 'chart-line', series: 'line' },
    {
      value: 'line-markers',
      label: 'Line + Markers',
      iconKey: 'chart-line-markers',
      series: 'line-markers',
    },
    { value: 'step', label: 'Step', iconKey: 'chart-step', series: 'step' },
    { value: 'area', label: 'Area', iconKey: 'chart-area', series: 'area' },
    { value: 'hlc-area', label: 'HLC Area', iconKey: 'chart-hlc-area', series: 'hlc-area' },
    {
      value: 'baseline',
      label: 'Baseline',
      iconKey: 'chart-baseline',
      series: 'baseline',
      baseline: true,
    },
  ],
  [
    {
      value: 'heikin-ashi',
      label: 'Heikin Ashi',
      iconKey: 'chart-heikin-ashi',
      series: 'candlestick',
      transform: () => ({ type: 'heikin-ashi' }),
    },
    {
      value: 'renko',
      label: 'Renko',
      iconKey: 'chart-renko',
      series: 'candlestick',
      transform: (b) => ({ type: 'renko', options: { boxSize: b } }),
    },
    {
      value: 'range',
      label: 'Range Bars',
      iconKey: 'chart-range-bars',
      series: 'candlestick',
      transform: (b) => ({ type: 'range-bars', options: { range: b } }),
    },
    {
      value: 'line-break',
      label: 'Line Break',
      iconKey: 'chart-line-break',
      series: 'candlestick',
      transform: () => ({ type: 'line-break', options: { lines: 3 } }),
    },
    {
      value: 'point-figure',
      label: 'Point & Figure',
      iconKey: 'chart-point-figure',
      series: 'point-figure',
      // Three boxes to reverse, from each bar's high and low: the standard
      // construction, and the transform's own defaults.
      transform: (b) => ({ type: 'point-figure', options: { boxSize: b } }),
    },
    {
      value: 'kagi',
      label: 'Kagi',
      iconKey: 'chart-kagi',
      series: 'kagi',
      // A reversal of two boxes, the proportion the transform itself takes
      // between its box and a Kagi reversal when it sizes both from history.
      transform: (b) => ({ type: 'kagi', options: { reversal: Number((b * 2).toPrecision(12)) } }),
    },
  ],
  [
    { value: 'tpo', label: 'Time Price Opportunity', iconKey: 'tpo', series: 'candlestick' },
    {
      value: 'session-volume-profile',
      label: 'Session Volume Profile',
      iconKey: 'profile',
      series: 'candlestick',
    },
  ],
]

export const CHART_TYPES: Record<string, ChartTypeDef> = Object.fromEntries(
  CHART_TYPE_GROUPS.flat().map((d) => [d.value, d])
)

/**
 * The types built from price boxes, which carry a settings dialog of their own
 * beside the chart type: box size and how it is measured, reversal, prices.
 */
export function isBoxChartType(value: string): value is 'renko' | 'point-figure' {
  return value === 'renko' || value === 'point-figure'
}

/**
 * The chart type id the packaged widget knows a value by. The widget applies
 * a transform itself under the transform's own id, so `range` is `range-bars`
 * there; every other value is the same word.
 */
export function widgetChartType(value: string): string {
  return CHART_TYPES[value]?.transform?.(0).type ?? value
}

/**
 * Volume under each element of a transformed chart: the raw bars' volume summed
 * onto the element they formed, keyed by the element's time. An element's own
 * `volume` is not traded volume (a Kagi line keeps its thickness there and a
 * brick carries none), so this is what a volume histogram under one draws.
 * Raw bars after the last element (a brick still forming) count toward it.
 */
export function volumeUnderElements(elements: readonly Bar[], raw: readonly Bar[]): Bar[] {
  const out: Bar[] = []
  let ri = 0
  for (const element of elements) {
    let v = 0
    while (ri < raw.length && raw[ri].time <= element.time) {
      v += raw[ri].volume || 0
      ri++
    }
    out.push({ time: element.time, open: 0, high: v, low: 0, close: v })
  }
  let rest = 0
  while (ri < raw.length) {
    rest += raw[ri].volume || 0
    ri++
  }
  if (out.length && rest) {
    const last = out[out.length - 1]
    last.high += rest
    last.close += rest
  }
  return out
}

const s = {
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.7,
  strokeLinecap: 'round' as const,
  strokeLinejoin: 'round' as const,
}

/**
 * Icon for a chart-type value (used in the dropdown button + menu items).
 *
 * Every type the engine draws a glyph for uses it, so the chart-type menu
 * reads from the same set as the toolbar around it. The two profile types are
 * this terminal's own and keep their pictures, drawn at the same line.
 */
export function chartTypeIcon(iconKey: string): ReactNode {
  if (hasChromeIcon(iconKey)) return <ChromeIcon id={iconKey} />
  switch (iconKey) {
    case 'tpo':
      return (
        <svg viewBox="0 0 24 24" {...s} strokeWidth={lineStroke24(16)}>
          <path d="M4 3v18M4 6h8M4 10h16M4 14h12M4 18h8M8 4v16M12 4v16M16 8v8M20 8v4" />
        </svg>
      )
    case 'profile':
      return (
        <svg viewBox="0 0 24 24" {...s} strokeWidth={lineStroke24(16)}>
          <path d="M4 3v18M4 5h7v4H4M4 9h16v4H4M4 13h12v4H4M4 17h5v4H4" />
        </svg>
      )
    default:
      return null
  }
}
