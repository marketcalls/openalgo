import type { Bar, SeriesStyle } from 'openalgo-charts'
import type { ChartSettingsField, ChartSettingsRequest } from './terminal'

type Values = Record<string, string | number | boolean>

export const VOLUME_DEFAULTS: Values = {
  'volume.colorByDirection': true,
  'volume.showMA': false,
  'volume.maPeriod': 20,
  'volume.maColor': '#e6b53c',
  'volume.maWidth': 1.5,
  'volume.maStyle': 'solid',
}

const fields: ChartSettingsField[] = [
  {
    key: 'volume.colorByDirection',
    type: 'boolean',
    label: 'Match candle colours',
    group: 'Histogram',
  },
  { key: 'volume.showMA', type: 'boolean', label: 'Show moving average', group: 'Moving average' },
  {
    key: 'volume.maPeriod',
    type: 'number',
    label: 'Period',
    min: 1,
    max: 500,
    step: 1,
    group: 'Moving average',
  },
  { key: 'volume.maColor', type: 'color', label: 'Colour', group: 'Moving average' },
  {
    key: 'volume.maWidth',
    type: 'number',
    label: 'Thickness',
    min: 1,
    max: 5,
    step: 0.5,
    group: 'Moving average',
  },
  {
    key: 'volume.maStyle',
    type: 'select',
    label: 'Line style',
    group: 'Moving average',
    options: [
      { value: 'solid', label: 'Solid' },
      { value: 'dashed', label: 'Dashed' },
      { value: 'dotted', label: 'Dotted' },
    ],
  },
]

export function volumeValues(saved: Values): Values {
  const values = { ...VOLUME_DEFAULTS }
  for (const key of Object.keys(values)) {
    const value = saved[key]
    if (typeof value !== typeof values[key]) continue
    if (typeof value === 'number') {
      if (!Number.isFinite(value)) continue
      values[key] =
        key === 'volume.maPeriod'
          ? Math.max(1, Math.min(500, Math.round(value)))
          : Math.max(1, Math.min(5, value))
    } else if (key === 'volume.maStyle') {
      if (['solid', 'dashed', 'dotted'].includes(String(value))) values[key] = value
    } else if (typeof value !== 'string' || value.trim()) values[key] = value
  }
  return values
}

export function volumeSettingsView(
  view: ChartSettingsRequest,
  saved: Values
): ChartSettingsRequest {
  return {
    tabs: [...view.tabs, { id: 'volume', label: 'Volume', inputs: fields }],
    values: { ...view.values, ...volumeValues(saved) },
    defaults: { ...view.defaults, ...VOLUME_DEFAULTS },
  }
}

/** The histogram follows the same body-colour rule as the displayed candle. */
export function volumePoint(
  bar: Bar,
  previousClose: number | undefined,
  amount: number,
  style: Pick<SeriesStyle, 'upColor' | 'downColor' | 'colorByPreviousClose'>,
  direction: boolean
): Bar {
  const reference =
    style.colorByPreviousClose && Number.isFinite(previousClose) ? previousClose! : bar.open
  const color = direction
    ? (bar.color ?? (bar.close >= reference ? style.upColor : style.downColor))
    : undefined
  return {
    time: bar.time,
    open: 0,
    high: amount,
    low: 0,
    close: amount,
    ...(color ? { color } : {}),
  }
}

/** A tail update reads at most one averaging window, regardless of retained history. */
export function volumeAveragePoint(bars: readonly Bar[], index: number, period: number): Bar {
  let value = NaN
  if (index + 1 >= period) {
    let total = 0
    for (let i = index - period + 1; i <= index; i++) total += bars[i].close
    value = total / period
  }
  return { time: bars[index].time, open: value, high: value, low: value, close: value }
}

export function volumeAverage(bars: readonly Bar[], period: number): Bar[] {
  let total = 0
  return bars.map((bar, index) => {
    total += bar.close
    if (index >= period) total -= bars[index - period].close
    const value = index + 1 >= period ? total / period : NaN
    return { time: bar.time, open: value, high: value, low: value, close: value }
  })
}
