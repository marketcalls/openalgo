/**
 * What this pins.
 *
 * The engine is stubbed, not the wiring around it: the real legend builder,
 * theme bridge and volume helpers run. Only `createChart`, the history API and
 * the market-data hook are stubs, because the assertions are about what this
 * component asks the engine to do.
 *
 * Two of these guard a trader directly. The time base: the backend's bars carry
 * a +5:30 shift and the engine wants real UTC, so a bar handed over unshifted
 * labels every candle 5h30m late and counts down to the wrong close. And the
 * keyboard: the scalper places orders on the arrow keys, so a chart that kept
 * its shortcuts would pan, or swallow the key, when an order was meant.
 */

import { act, render, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ScalpChart } from './ScalpChart'

const IST = 19800

interface SeriesStub {
  type: string
  options: Record<string, unknown>
  setData: ReturnType<typeof vi.fn>
  update: ReturnType<typeof vi.fn>
  applyOptions: ReturnType<typeof vi.fn>
  priceScale: () => { setOptions: ReturnType<typeof vi.fn> }
}

interface ChartStub {
  options: Record<string, unknown>
  series: SeriesStub[]
  crosshair: Array<(e: { time: number | null }) => void>
  destroyed: number
}

const harness = vi.hoisted(() => {
  const charts: ChartStub[] = []
  const createChart = vi.fn((_host: HTMLElement, options: Record<string, unknown>) => {
    const chart: ChartStub & Record<string, unknown> = {
      options,
      series: [],
      crosshair: [],
      destroyed: 0,
      addSeries: (type: string, opts?: Record<string, unknown>) => {
        const series: SeriesStub = {
          type,
          options: opts ?? {},
          setData: vi.fn(),
          update: vi.fn(),
          applyOptions: vi.fn(),
          priceScale: () => ({ setOptions: vi.fn() }),
        }
        chart.series.push(series)
        return series
      },
      setDataContext: vi.fn(),
      getVisibleLogicalRange: () => null,
      setVisibleLogicalRange: vi.fn(),
      fitContent: vi.fn(),
      setTheme: vi.fn(),
      theme: () => ({ upColor: '#00aa00', downColor: '#aa0000', background: '#000000' }),
      subscribeCrosshairMove: (cb: (e: { time: number | null }) => void) => {
        chart.crosshair.push(cb)
        return () => {}
      },
      destroy: () => {
        chart.destroyed += 1
      },
    }
    charts.push(chart)
    return chart
  })
  const quotes = { data: new Map<string, { data: Record<string, unknown> }>() }
  const getHistory = vi.fn()
  return { charts, createChart, quotes, getHistory }
})

vi.mock('openalgo-charts', () => ({
  createChart: harness.createChart,
  compactVolume: (n: number) => `${n}`,
  lightTheme: {},
  darkTheme: {},
}))

vi.mock('@/api/scalping', () => ({ scalpingApi: { getHistory: harness.getHistory } }))

vi.mock('@/hooks/useMarketData', () => ({
  useMarketData: () => ({ data: harness.quotes.data }),
}))

// Two completed 1m bars in the backend's IST-shifted base: 09:15 and 09:16 IST.
const T0 = 1_761_536_700 + IST
const HISTORY = [
  { time: T0, open: 100, high: 102, low: 99, close: 101, volume: 500 },
  { time: T0 + 60, open: 101, high: 104, low: 100, close: 103, volume: 700 },
]

const chart = () => harness.charts[harness.charts.length - 1]
const candles = () => chart().series[0]
const volume = () => chart().series[1]

function pushTick(symbol: string, exchange: string, ltp: number, utcSeconds: number, vol = 0) {
  harness.quotes.data = new Map([
    [
      `${exchange}:${symbol}`,
      { data: { ltp, volume: vol, timestamp: new Date(utcSeconds * 1000).toISOString() } },
    ],
  ])
}

beforeEach(() => {
  harness.charts.length = 0
  harness.createChart.mockClear()
  harness.quotes.data = new Map()
  harness.getHistory.mockReset()
  harness.getHistory.mockResolvedValue({ status: 'success', candles: HISTORY, date: '2025-10-27' })
})

describe('ScalpChart', () => {
  it('keeps the arrow keys for order entry and shows the candle countdown', () => {
    render(<ScalpChart symbol="NIFTY28OCT2525000CE" exchange="NFO" interval="1m" />)
    const options = chart().options
    expect(options.shortcuts).toBe(false)
    expect(options.axisChrome).toEqual({ barCountdown: true })
  })

  it('hands the engine real UTC seconds, not the backend shifted base', async () => {
    render(<ScalpChart symbol="NIFTY28OCT2525000CE" exchange="NFO" interval="1m" />)
    await waitFor(() => expect(candles().setData).toHaveBeenLastCalledWith(expect.any(Array)))
    await waitFor(() => expect(candles().setData.mock.lastCall?.[0]).toHaveLength(2))
    const bars = candles().setData.mock.lastCall?.[0] as Array<Record<string, number>>
    expect(bars.map((b) => b.time)).toEqual([T0 - IST, T0 + 60 - IST])
    expect(bars[1]).toMatchObject({ open: 101, close: 103, volume: 700 })
    const vols = volume().setData.mock.lastCall?.[0] as Array<Record<string, number>>
    expect(vols.map((b) => [b.time, b.close])).toEqual([
      [T0 - IST, 500],
      [T0 + 60 - IST, 700],
    ])
  })

  it('builds the forming candle from live ticks in the same UTC base', async () => {
    const { rerender } = render(
      <ScalpChart symbol="NIFTY28OCT2525000CE" exchange="NFO" interval="1m" />
    )
    await waitFor(() => expect(candles().setData.mock.lastCall?.[0]).toHaveLength(2))

    // 09:17:05 IST opens the next bucket, 09:17:40 extends it.
    const opens = T0 - IST + 125
    pushTick('NIFTY28OCT2525000CE', 'NFO', 105, opens)
    rerender(<ScalpChart symbol="NIFTY28OCT2525000CE" exchange="NFO" interval="1m" />)
    pushTick('NIFTY28OCT2525000CE', 'NFO', 107, opens + 35)
    rerender(<ScalpChart symbol="NIFTY28OCT2525000CE" exchange="NFO" interval="1m" />)

    expect(candles().update).toHaveBeenLastCalledWith(
      expect.objectContaining({ time: T0 + 120 - IST, open: 105, high: 107, close: 107 })
    )
  })

  it('draws no volume and reads none for an index', async () => {
    const { container } = render(<ScalpChart symbol="NIFTY" exchange="NSE_INDEX" interval="1m" />)
    await waitFor(() => expect(container.textContent).toContain('C 103.00'))
    expect(volume().applyOptions).toHaveBeenCalledWith({ visible: false })
    expect(container.textContent).not.toMatch(/\bV \d/)
  })

  it('reads the hovered candle in the legend, and keeps it through a live tick', async () => {
    const { container, rerender } = render(
      <ScalpChart symbol="NIFTY28OCT2525000CE" exchange="NFO" interval="1m" />
    )
    await waitFor(() => expect(container.textContent).toContain('C 103.00'))
    expect(container.textContent).toContain('NIFTY28OCT2525000CE')
    expect(container.textContent).toContain('· 1m · NFO')

    // The engine reports the hovered bar in UTC seconds.
    act(() => {
      for (const cb of chart().crosshair) cb({ time: T0 - IST })
    })
    expect(container.textContent).toContain('C 101.00')

    pushTick('NIFTY28OCT2525000CE', 'NFO', 108, T0 - IST + 125)
    rerender(<ScalpChart symbol="NIFTY28OCT2525000CE" exchange="NFO" interval="1m" />)
    expect(container.textContent).toContain('C 101.00')

    // Off the chart, it follows the forming candle again.
    act(() => {
      for (const cb of chart().crosshair) cb({ time: null })
    })
    expect(container.textContent).toContain('C 108.00')
  })

  it('destroys the chart when it unmounts', async () => {
    const { unmount } = render(<ScalpChart symbol="USDINR" exchange="CDS" interval="1m" />)
    await waitFor(() => expect(candles().setData.mock.lastCall?.[0]).toHaveLength(2))
    const built = chart()
    unmount()
    expect(built.destroyed).toBe(1)
  })
})
