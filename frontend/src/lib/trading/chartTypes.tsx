/**
 * Chart-type catalogue for the trading terminal: the TradingView-style dropdown
 * groups, each type's icon, its underlying openalgo-charts series, and (for
 * movement-driven types) a transform factory. Kagi and Point & Figure are
 * intentionally omitted for now.
 */

import {
  HeikinAshiTransform,
  type ISeriesTransform,
  LineBreakTransform,
  RangeBarsTransform,
  RenkoTransform,
} from 'openalgo-charts/transform'
import type { ReactNode } from 'react'

export interface ChartTypeDef {
  value: string
  label: string
  iconKey: string
  series: string
  /** Movement-driven types run this transform over the raw bars first. */
  transform?: (boxSize: number) => ISeriesTransform
  /** Baseline needs a baseValue in its series style. */
  baseline?: boolean
}

/** Ordered groups (separators between them), matching the dropdown layout. */
export const CHART_TYPE_GROUPS: ChartTypeDef[][] = [
  [
    { value: 'bar', label: 'Bars (OHLC)', iconKey: 'bars', series: 'bar' },
    { value: 'candlestick', label: 'Candles', iconKey: 'candle', series: 'candlestick' },
    { value: 'hollow-candle', label: 'Hollow Candles', iconKey: 'hollow', series: 'hollow-candle' },
    { value: 'volume-candle', label: 'Volume Candles', iconKey: 'vol', series: 'volume-candle' },
    { value: 'high-low', label: 'High-Low', iconKey: 'highLow', series: 'high-low' },
  ],
  [
    { value: 'line', label: 'Line', iconKey: 'line', series: 'line' },
    { value: 'line-markers', label: 'Line + Markers', iconKey: 'lineDots', series: 'line-markers' },
    { value: 'step', label: 'Step', iconKey: 'step', series: 'step' },
    { value: 'area', label: 'Area', iconKey: 'area', series: 'area' },
    { value: 'hlc-area', label: 'HLC Area', iconKey: 'area', series: 'hlc-area' },
    {
      value: 'baseline',
      label: 'Baseline',
      iconKey: 'baseline',
      series: 'baseline',
      baseline: true,
    },
  ],
  [
    {
      value: 'heikin-ashi',
      label: 'Heikin Ashi',
      iconKey: 'candle',
      series: 'candlestick',
      transform: () => new HeikinAshiTransform(),
    },
    {
      value: 'renko',
      label: 'Renko',
      iconKey: 'bricks',
      series: 'candlestick',
      transform: (b) => new RenkoTransform({ boxSize: b }),
    },
    {
      value: 'range',
      label: 'Range Bars',
      iconKey: 'bricks',
      series: 'candlestick',
      transform: (b) => new RangeBarsTransform({ range: b }),
    },
    {
      value: 'line-break',
      label: 'Line Break',
      iconKey: 'bricks',
      series: 'candlestick',
      transform: () => new LineBreakTransform({ lines: 3 }),
    },
  ],
]

export const CHART_TYPES: Record<string, ChartTypeDef> = Object.fromEntries(
  CHART_TYPE_GROUPS.flat().map((d) => [d.value, d])
)

const s = {
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.7,
  strokeLinecap: 'round' as const,
  strokeLinejoin: 'round' as const,
}

/** Icon for a chart-type value (used in the dropdown button + menu items). */
export function chartTypeIcon(iconKey: string): ReactNode {
  switch (iconKey) {
    case 'candle':
      return (
        <svg viewBox="0 0 24 24" fill="currentColor">
          <rect x="4.5" y="9" width="4" height="7" rx="1" />
          <rect x="6" y="5" width="1" height="15" rx=".5" />
          <rect x="14.5" y="7" width="4" height="6" rx="1" />
          <rect x="16" y="4" width="1" height="16" rx=".5" />
        </svg>
      )
    case 'hollow':
      return (
        <svg viewBox="0 0 24 24" {...s} strokeWidth={1.6}>
          <rect x="4.5" y="9" width="4" height="7" rx="1" />
          <path d="M6.5 9V5M6.5 16v3" />
          <rect x="14.5" y="7" width="4" height="6" rx="1" />
          <path d="M16.5 7V4M16.5 13v3" />
        </svg>
      )
    case 'bars':
      return (
        <svg viewBox="0 0 24 24" {...s} strokeWidth={1.6}>
          <path d="M7 4v16M4 8h3M7 13h3M17 5v14M14 9h3M17 15h3" />
        </svg>
      )
    case 'highLow':
      return (
        <svg viewBox="0 0 24 24" {...s} strokeWidth={1.8}>
          <path d="M6 6v12M12 4v14M18 8v10" />
        </svg>
      )
    case 'vol':
      return (
        <svg viewBox="0 0 24 24" fill="currentColor">
          <rect x="5" y="6" width="4" height="6" rx="1" />
          <rect x="6.5" y="3" width="1" height="13" />
          <rect x="4.5" y="18" width="5" height="2.5" rx=".5" opacity=".5" />
          <rect x="14.5" y="8" width="4" height="5" rx="1" />
          <rect x="16" y="5" width="1" height="13" />
          <rect x="14" y="16" width="5" height="4.5" rx=".5" opacity=".5" />
        </svg>
      )
    case 'line':
      return (
        <svg viewBox="0 0 24 24" {...s} strokeWidth={1.8}>
          <path d="M3 16l4-5 4 3 4-6 6 4" />
        </svg>
      )
    case 'lineDots':
      return (
        <svg viewBox="0 0 24 24" {...s} strokeWidth={1.5}>
          <path d="M3 16l4-5 4 3 4-6 6 4" />
          <circle cx="7" cy="11" r="1.7" fill="currentColor" stroke="none" />
          <circle cx="11" cy="14" r="1.7" fill="currentColor" stroke="none" />
          <circle cx="15" cy="8" r="1.7" fill="currentColor" stroke="none" />
        </svg>
      )
    case 'step':
      return (
        <svg viewBox="0 0 24 24" {...s}>
          <path d="M3 17h4v-6h5V7h4v4h1" />
        </svg>
      )
    case 'area':
      return (
        <svg viewBox="0 0 24 24">
          <path d="M3 17l4-5 4 3 4-6 6 4v6H3z" fill="currentColor" opacity=".32" />
          <path d="M3 17l4-5 4 3 4-6 6 4" {...s} strokeWidth={1.6} />
        </svg>
      )
    case 'baseline':
      return (
        <svg viewBox="0 0 24 24">
          <path
            d="M3 12h18"
            stroke="currentColor"
            strokeWidth={1}
            strokeDasharray="2 2"
            opacity=".6"
          />
          <path d="M3 13l4-5 4 2 4-5 6 4" {...s} strokeWidth={1.6} />
        </svg>
      )
    case 'bricks':
      return (
        <svg viewBox="0 0 24 24" fill="currentColor">
          <rect x="3" y="13" width="5" height="5" rx=".6" />
          <rect x="9.5" y="8.5" width="5" height="5" rx=".6" />
          <rect x="16" y="10" width="5" height="5" rx=".6" />
        </svg>
      )
    default:
      return null
  }
}
