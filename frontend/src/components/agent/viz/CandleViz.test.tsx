/**
 * What this pins.
 *
 * The engine is stubbed, not the wiring around it: the real `CHART_TYPES` map
 * and the real `buildChartTheme` bridge run, so a chart type or a theme token
 * that stopped resolving would fail here. Only `createChart` itself is a stub,
 * because the assertions are about what this component asks the engine to do.
 *
 * The one that matters most is disposal. A chart per message that never
 * destroys is a leak in a thread that only grows, and it is invisible until an
 * afternoon of conversation has a canvas and a frame loop per answer.
 */

import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { CandleViz } from './CandleViz'

interface SeriesStub {
  type: string
  setData: ReturnType<typeof vi.fn>
  priceScale: () => { setOptions: ReturnType<typeof vi.fn> }
}

interface ChartStub {
  options: Record<string, unknown>
  series: SeriesStub[]
  indicators: string[]
  primitives: Array<{ primitive: unknown; pane: number }>
  destroyed: number
  fitted: number
  spacing: number[]
  addSeries: (type: string) => SeriesStub
  addPrimitive: (primitive: unknown, pane: number) => void
  addIndicator: (id: string) => void
  fitContent: () => void
  timeScale: { barSpacing: number; setBarSpacing: (value: number) => void }
  destroy: () => void
}

const harness = vi.hoisted(() => {
  const charts: ChartStub[] = []
  const createChart = vi.fn((_host: HTMLElement, options: Record<string, unknown>) => {
    const chart: ChartStub = {
      options,
      series: [],
      indicators: [],
      primitives: [],
      destroyed: 0,
      fitted: 0,
      spacing: [],
      // A fresh chart opens wide, which is what a one-bar range would leave it
      // at and what the bar-spacing cap exists to pull back.
      timeScale: {
        barSpacing: 120,
        setBarSpacing: (value: number) => {
          chart.spacing.push(value)
          chart.timeScale.barSpacing = value
        },
      },
      addSeries: (type: string) => {
        const series: SeriesStub = {
          type,
          setData: vi.fn(),
          priceScale: () => ({ setOptions: vi.fn() }),
        }
        chart.series.push(series)
        return series
      },
      addPrimitive: (primitive: unknown, pane: number) => {
        chart.primitives.push({ primitive, pane })
      },
      addIndicator: (id: string) => {
        // An id this build does not know is exactly what the engine throws on.
        if (id === 'not-an-indicator') throw new Error('unknown indicator')
        chart.indicators.push(id)
      },
      fitContent: () => {
        chart.fitted += 1
      },
      destroy: () => {
        chart.destroyed += 1
      },
    }
    charts.push(chart)
    return chart
  })
  // The brand mark is a host-owned primitive, so the stub records what it was
  // constructed with; the test below asserts the asset and the corner rather
  // than merely that something was added.
  class LogoWatermark {
    options: Record<string, unknown>
    constructor(options: Record<string, unknown>) {
      this.options = options
    }
  }
  return { charts, createChart, LogoWatermark }
})

vi.mock('openalgo-charts', () => ({
  createChart: harness.createChart,
  isValidTimezone: (zone: string) => zone === 'Asia/Kolkata',
  lightTheme: {},
  darkTheme: {},
  LogoWatermark: harness.LogoWatermark,
}))

vi.mock('openalgo-charts/transform', () => ({
  runTransform: (_transform: unknown, bars: unknown) => bars,
  HeikinAshiTransform: class {},
  LineBreakTransform: class {},
  RangeBarsTransform: class {},
  RenkoTransform: class {},
}))

vi.mock('openalgo-charts/indicators', () => ({}))

function bar(time: number, close: number, volume = 1000) {
  return { time, open: close, high: close, low: close, close, volume }
}

const SPEC = {
  symbol: 'RELIANCE',
  exchange: 'NSE',
  interval: 'D',
  chart_type: 'candlestick',
  start_date: '2026-06-03',
  end_date: '2026-09-03',
  source: 'api',
  timezone: 'Asia/Kolkata',
  bar_count: 3,
  bars: [bar(1780444800, 1315), bar(1780531200, 1320), bar(1780617600, 1309)],
  indicators: [{ id: 'ema', inputs: { length: 20 } }],
  summary: { change_percent: -0.4563 },
}

beforeEach(() => {
  harness.charts.length = 0
  harness.createChart.mockClear()
})

describe('CandleViz', () => {
  it('draws the bars it was given and destroys the chart on unmount', async () => {
    const view = render(<CandleViz spec={SPEC} title="RELIANCE NSE D" source="history_service" />)

    await waitFor(() => expect(harness.charts).toHaveLength(1))
    const chart = harness.charts[0]

    expect(chart.options.shortcuts).toBe(false)
    expect(chart.options.timeNavigator).toBe(false)
    expect(chart.options.timezone).toBe('Asia/Kolkata')
    expect(chart.series[0].type).toBe('candlestick')
    expect(chart.series[0].setData).toHaveBeenCalledWith(SPEC.bars)
    // Volume rides an overlay scale in the price pane, as it does on /trading.
    expect(chart.series[1].type).toBe('histogram')
    await waitFor(() => expect(chart.indicators).toEqual(['ema']))

    expect(screen.getByText('RELIANCE')).toBeInTheDocument()
    expect(screen.getByText('-0.46%')).toBeInTheDocument()
    expect(screen.getByText('3 bars')).toBeInTheDocument()
    expect(screen.getByText('ema(20)')).toBeInTheDocument()

    expect(chart.destroyed).toBe(0)
    view.unmount()
    expect(chart.destroyed).toBe(1)
  })

  it('keeps one candle readable rather than filling the card with it', async () => {
    const single = { ...SPEC, bar_count: 1, bars: [bar(1780444800, 1315)], indicators: [] }
    render(<CandleViz spec={single} />)

    await waitFor(() => expect(harness.charts).toHaveLength(1))
    const chart = harness.charts[0]
    expect(chart.fitted).toBe(1)
    expect(chart.spacing).toEqual([24])
    expect(screen.getByText('1 bar')).toBeInTheDocument()
  })

  it('draws a range whose high equals its low', async () => {
    const flat = {
      ...SPEC,
      bars: [
        { time: 1780444800, open: 100, high: 100, low: 100, close: 100 },
        { time: 1780531200, open: 100, high: 100, low: 100, close: 100 },
      ],
      indicators: [],
    }
    render(<CandleViz spec={flat} />)

    await waitFor(() => expect(harness.charts).toHaveLength(1))
    // No volume series: not one bar carried any.
    expect(harness.charts[0].series).toHaveLength(1)
    expect(screen.getByText('2 bars')).toBeInTheDocument()
  })

  it('drops a bar with no usable time or close, and orders what is left', async () => {
    const messy = {
      ...SPEC,
      indicators: [],
      bars: [
        bar(1780531200, 1320),
        { open: 1, high: 1, low: 1, close: 1 },
        { time: 1780617600, open: 2, high: 2, low: 2 },
        bar(1780444800, 1315),
      ],
    }
    render(<CandleViz spec={messy} />)

    await waitFor(() => expect(harness.charts).toHaveLength(1))
    const drawn = harness.charts[0].series[0].setData.mock.calls[0][0] as { time: number }[]
    expect(drawn.map((row) => row.time)).toEqual([1780444800, 1780531200])
    expect(screen.getByText('2 bars')).toBeInTheDocument()
  })

  it('skips an indicator id this build does not know', async () => {
    const unknown = {
      ...SPEC,
      indicators: [
        { id: 'not-an-indicator', inputs: {} },
        { id: 'rsi', inputs: { length: 14 } },
      ],
    }
    render(<CandleViz spec={unknown} />)

    await waitFor(() => expect(harness.charts).toHaveLength(1))
    await waitFor(() => expect(harness.charts[0].indicators).toEqual(['rsi']))
    expect(screen.getByText('3 bars')).toBeInTheDocument()
  })

  it('says so when the tool drew no candles', async () => {
    render(<CandleViz spec={{ ...SPEC, bar_count: 0, bars: [] }} />)

    expect(await screen.findByText(/No candles came back/)).toBeInTheDocument()
    expect(harness.createChart).not.toHaveBeenCalled()
  })

  it.each([
    ['null', null],
    ['a string', 'RELIANCE'],
    ['an object with no bars', { symbol: 'RELIANCE' }],
    ['bars that are not a list', { symbol: 'RELIANCE', bars: 42 }],
    ['bars that are all unusable', { symbol: 'RELIANCE', bars: [1, 'x', {}] }],
  ])('renders a message rather than throwing for %s', async (_name, spec) => {
    render(<CandleViz spec={spec} title="RELIANCE NSE D" />)

    expect(await screen.findByText(/could not be drawn/)).toBeInTheDocument()
    expect(harness.createChart).not.toHaveBeenCalled()
  })

  it('carries the OpenAlgo mark by default', async () => {
    // The library has no watermark option: the mark is a primitive the host
    // adds, so a chart that never adds one simply has none, and nothing fails.
    // That is how it went missing here while /trading kept its own. Pinned by
    // the asset and the corner, not merely by something having been added.
    render(<CandleViz spec={SPEC} title="RELIANCE NSE D" />)
    await waitFor(() => expect(harness.charts).toHaveLength(1))

    const marks = harness.charts[0].primitives
    expect(marks).toHaveLength(1)
    expect(marks[0].pane).toBe(0)

    const options = (marks[0].primitive as { options: Record<string, unknown> }).options
    expect(options.src).toBe('/images/openalgo-glyph.svg')
    expect(options.position).toBe('bottom-left')
    expect(options.label).toBe('OpenAlgo Charts')
  })
})
