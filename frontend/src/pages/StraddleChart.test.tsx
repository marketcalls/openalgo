/**
 * What this pins.
 *
 * The engine is stubbed, not the wiring around it: the real theme bridge runs,
 * and only `createChart` and the two APIs the page reads are stubs, because the
 * assertions are about what the page asks the engine to do.
 *
 * Two of these guard a trader directly. The time base: the backend already
 * sends real UTC seconds, so a page that shifted them by 5h30m, as
 * lightweight-charts pages had to, would label every bar five and a half hours
 * late. And the readout: the tooltip is the only place the call, the put and
 * the strike are read, so it must quote the point under the crosshair.
 */

import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useThemeStore } from '@/stores/themeStore'
import StraddleChart from './StraddleChart'

interface SeriesStub {
  type: string
  options: Record<string, unknown>
  setData: ReturnType<typeof vi.fn>
  applyOptions: ReturnType<typeof vi.fn>
  scale: ReturnType<typeof vi.fn>
  priceScale: () => { setOptions: ReturnType<typeof vi.fn> }
}

interface CrosshairEvent {
  time: number | null
  point: { x: number; y: number } | null
}

interface ChartStub {
  host: HTMLElement
  options: Record<string, unknown>
  series: SeriesStub[]
  crosshair: Array<(e: CrosshairEvent) => void>
  unsubscribed: number
  destroyed: number
  fitContent: ReturnType<typeof vi.fn>
  setTheme: ReturnType<typeof vi.fn>
}

const harness = vi.hoisted(() => {
  const charts: ChartStub[] = []
  const createChart = vi.fn((host: HTMLElement, options: Record<string, unknown>) => {
    const chart: ChartStub & Record<string, unknown> = {
      host,
      options,
      series: [],
      crosshair: [],
      unsubscribed: 0,
      destroyed: 0,
      fitContent: vi.fn(),
      setTheme: vi.fn(),
      addSeries: (type: string, opts?: Record<string, unknown>) => {
        const scale = vi.fn()
        const series: SeriesStub = {
          type,
          options: opts ?? {},
          setData: vi.fn(),
          applyOptions: vi.fn(),
          scale,
          priceScale: () => ({ setOptions: scale }),
        }
        chart.series.push(series)
        return series
      },
      subscribeCrosshairMove: (cb: (e: CrosshairEvent) => void) => {
        chart.crosshair.push(cb)
        return () => {
          chart.unsubscribed += 1
        }
      },
      destroy: () => {
        chart.destroyed += 1
      },
    }
    // The engine puts its canvas in the host; cleanup has to clear it.
    host.appendChild(document.createElement('canvas'))
    charts.push(chart)
    return chart
  })
  const getStraddleData = vi.fn()
  return { charts, createChart, getStraddleData }
})

vi.mock('openalgo-charts', () => ({
  createChart: harness.createChart,
  lightTheme: { name: 'light' },
  darkTheme: { name: 'dark' },
}))

vi.mock('@/api/straddle-chart', () => ({
  straddleChartApi: {
    getStraddleData: harness.getStraddleData,
    getIntervals: async () => ({
      status: 'success',
      data: { seconds: [], minutes: ['1m', '5m'], hours: [] },
    }),
  },
}))

vi.mock('@/api/oi-profile', () => ({
  oiProfileApi: {
    getUnderlyings: async () => ({ status: 'success', underlyings: ['NIFTY'] }),
    getExpiries: async () => ({ status: 'success', expiries: ['28-OCT-26'] }),
  },
}))

// 09:15 and 09:16 IST on 27 Oct 2026, as the backend sends them: real UTC.
const T0 = Date.UTC(2026, 9, 27, 3, 45) / 1000
const POINTS = [
  // Out of order on purpose: the page sorts before it hands anything over.
  {
    time: T0 + 60,
    spot: 25010.5,
    atm_strike: 25000,
    ce_price: 120.25,
    pe_price: 110.75,
    straddle: 231,
    synthetic_future: 25009.5,
  },
  {
    time: T0,
    spot: 24990.25,
    atm_strike: 25000,
    ce_price: 112.5,
    pe_price: 121.4,
    straddle: 233.9,
    synthetic_future: 24991.1,
  },
]

const chart = () => harness.charts[harness.charts.length - 1]
const straddle = () => chart().series[0]
const spot = () => chart().series[1]
const synthetic = () => chart().series[2]
const tooltip = () => screen.getByTestId('straddle-tooltip')

async function renderLoaded() {
  const view = render(<StraddleChart />)
  await waitFor(() => expect(straddle().setData).toHaveBeenCalled())
  return view
}

beforeEach(() => {
  harness.charts.length = 0
  harness.createChart.mockClear()
  harness.getStraddleData.mockReset()
  harness.getStraddleData.mockResolvedValue({
    status: 'success',
    data: {
      underlying: 'NIFTY',
      underlying_ltp: 25010.5,
      expiry_date: '28OCT26',
      interval: '1m',
      days_to_expiry: 1,
      series: POINTS,
    },
  })
  useThemeStore.setState({ mode: 'light', appMode: 'live' })
})

afterEach(() => {
  useThemeStore.setState({ mode: 'light', appMode: 'live' })
})

describe('StraddleChart', () => {
  it('draws the straddle on the right as the primary line, spot and synthetic on the left', async () => {
    await renderLoaded()
    expect(harness.createChart).toHaveBeenCalledTimes(1)
    expect(chart().options.shortcuts).toBe(false)

    expect(chart().series.map((s) => [s.type, s.options.priceScaleId])).toEqual([
      ['line', 'right'],
      ['line', 'left'],
      ['line', 'left'],
    ])
    expect(straddle().options.style).toMatchObject({ visible: true, lineWidth: 2 })
    expect(spot().options.style).toMatchObject({ visible: false, lineWidth: 2 })
    expect(synthetic().options.style).toMatchObject({
      visible: false,
      lineWidth: 1,
      lineStyle: 'dashed',
      priceLineVisible: false,
    })
    for (const s of chart().series) {
      expect(s.options.priceFormat).toEqual({ type: 'price', precision: 2, minMove: 0.01 })
    }
    expect(straddle().scale).toHaveBeenCalledWith({ marginTop: 0.05, marginBottom: 0.05 })
    expect(spot().scale).toHaveBeenCalledWith({ marginTop: 0.05, marginBottom: 0.05 })
  })

  it('hands the engine the backend times as they are: real UTC seconds, in order', async () => {
    await renderLoaded()
    expect(straddle().setData).toHaveBeenLastCalledWith([
      { time: T0, value: 233.9 },
      { time: T0 + 60, value: 231 },
    ])
    expect(spot().setData).toHaveBeenLastCalledWith([
      { time: T0, value: 24990.25 },
      { time: T0 + 60, value: 25010.5 },
    ])
    expect(synthetic().setData).toHaveBeenLastCalledWith([
      { time: T0, value: 24991.1 },
      { time: T0 + 60, value: 25009.5 },
    ])
    expect(chart().fitContent).toHaveBeenCalled()
  })

  it('quotes the hovered point in the tooltip and hides it when the pointer leaves', async () => {
    await renderLoaded()
    expect(tooltip().style.display).toBe('')

    // The engine reports the hovered bar in UTC seconds: this is 09:15 IST.
    act(() => {
      for (const cb of chart().crosshair) cb({ time: T0, point: { x: 100, y: 80 } })
    })
    const text = tooltip().textContent ?? ''
    expect(tooltip().style.display).toBe('block')
    // Each label beside its own value, so a call and put swapped would fail.
    expect(text).toMatch(/Straddle Price\s*233\.90/)
    expect(text).toMatch(/25000 Call:\s*112\.50/)
    expect(text).toMatch(/25000 Put:\s*121\.40/)
    expect(text).toMatch(/Synthetic Fut\s*24,991\.10/)
    expect(text).toMatch(/Spot Price\s*24,990\.25/)
    expect(text).toMatch(/27 Oct\s*09:15 AM/)

    act(() => {
      for (const cb of chart().crosshair) cb({ time: null, point: null })
    })
    expect(tooltip().style.display).toBe('')
  })

  it('shows and hides series from the legend, and the leading value tag follows', async () => {
    await renderLoaded()
    fireEvent.click(screen.getByRole('button', { name: 'Straddle' }))
    fireEvent.click(screen.getByRole('button', { name: 'Spot' }))

    expect(straddle().applyOptions).toHaveBeenLastCalledWith(
      expect.objectContaining({ visible: false })
    )
    expect(spot().applyOptions).toHaveBeenLastCalledWith(expect.objectContaining({ visible: true }))
    // With the straddle off, spot leads, so the tag wears spot's colour.
    const spotColour = spot().applyOptions.mock.lastCall?.[0].color
    const theme = chart().setTheme.mock.lastCall?.[0]
    expect(theme.lastPriceUp).toBe(spotColour)
    expect(theme.lastPriceDown).toBe(spotColour)
  })

  it('re-themes the same chart for dark and analyzer instead of rebuilding it', async () => {
    await renderLoaded()
    const built = chart()

    act(() => {
      useThemeStore.setState({ mode: 'dark' })
    })
    expect(harness.createChart).toHaveBeenCalledTimes(1)
    expect(built.setTheme).toHaveBeenCalled()
    expect(straddle().applyOptions).toHaveBeenLastCalledWith(
      expect.objectContaining({ color: '#4ade80' })
    )
    expect(synthetic().applyOptions).toHaveBeenLastCalledWith(
      expect.objectContaining({ color: '#60a5fa' })
    )

    act(() => {
      useThemeStore.setState({ appMode: 'analyzer' })
    })
    // In Analyze the straddle wears the mode's accent, which the theme carries.
    const theme = built.setTheme.mock.lastCall?.[0]
    expect(straddle().applyOptions).toHaveBeenLastCalledWith(
      expect.objectContaining({ color: theme.lineColor })
    )
    expect(theme.lastPriceUp).toBe(theme.lineColor)
    expect(harness.createChart).toHaveBeenCalledTimes(1)
  })

  it('destroys the chart, drops the crosshair listener and empties the host on unmount', async () => {
    const { unmount } = await renderLoaded()
    const built = chart()
    expect(built.host.childElementCount).toBe(1)
    unmount()
    expect(built.destroyed).toBe(1)
    expect(built.unsubscribed).toBe(1)
    expect(built.host.childElementCount).toBe(0)
  })
})
