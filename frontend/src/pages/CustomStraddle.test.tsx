/**
 * What this pins.
 *
 * The engine is stubbed, not the wiring around it: the real theme bridge runs,
 * and only `createChart` and the APIs the page reads are stubs, because the
 * assertions are about what the page asks the engine to do.
 *
 * Three of these guard a trader directly. The time base: the backend already
 * sends real UTC seconds, so a page that shifted them by 5h30m, as
 * lightweight-charts pages had to, would label every bar five and a half hours
 * late. The colour of money: profit and loss come from the theme's up and down
 * pair, so a run that ended in a loss must not wear a green tag. And the
 * readout: the tooltip is where the strike, the adjustments and the P&L at a
 * moment are read, so it must quote the point under the crosshair.
 */

import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useThemeStore } from '@/stores/themeStore'
import CustomStraddle from './CustomStraddle'

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
  options: Record<string, unknown> & { theme: Record<string, string> }
  series: SeriesStub[]
  crosshair: Array<(e: CrosshairEvent) => void>
  unsubscribed: number
  destroyed: number
  fitContent: ReturnType<typeof vi.fn>
  setTheme: ReturnType<typeof vi.fn>
}

const harness = vi.hoisted(() => {
  const charts: ChartStub[] = []
  const createChart = vi.fn((host: HTMLElement, options: ChartStub['options']) => {
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
  const simulate = vi.fn()
  return { charts, createChart, simulate }
})

vi.mock('openalgo-charts', () => ({
  createChart: harness.createChart,
  lightTheme: { name: 'light' },
  darkTheme: { name: 'dark' },
}))

vi.mock('@/api/custom-straddle', () => ({
  customStraddleApi: {
    simulate: harness.simulate,
    getIntervals: async () => ({
      status: 'success',
      data: { seconds: [], minutes: ['1m', '5m'], hours: [] },
    }),
    getLotSize: async () => ({ status: 'success', lotsize: 65 }),
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

function point(time: number, pnl: number, extra: Record<string, number> = {}) {
  return {
    time,
    pnl,
    spot: 24990.25,
    atm_strike: 25000,
    entry_strike: 24950,
    ce_price: 112.5,
    pe_price: 121.4,
    straddle: 233.9,
    synthetic_future: 24991.1,
    adjustments: 3,
    ...extra,
  }
}

// Out of order on purpose: the page sorts before it hands anything over. The
// run ends in a loss.
const LOSING_RUN = [
  point(T0 + 60, -1250.5, { spot: 25010.5, synthetic_future: 25009.5 }),
  point(T0, 1234.5),
]

function respondWith(series: ReturnType<typeof point>[]) {
  const pnls = series.map((p) => p.pnl)
  harness.simulate.mockResolvedValue({
    status: 'success',
    data: {
      underlying: 'NIFTY',
      underlying_ltp: 25010.5,
      expiry_date: '28OCT26',
      interval: '1m',
      days_to_expiry: 1,
      adjustment_points: 50,
      lot_size: 65,
      lots: 1,
      quantity: 65,
      pnl_series: series,
      trades: [],
      summary: {
        total_pnl: pnls[0],
        total_adjustments: 3,
        max_pnl: Math.max(...pnls),
        min_pnl: Math.min(...pnls),
      },
    },
  })
}

const chart = () => harness.charts[harness.charts.length - 1]
const pnl = () => chart().series[0]
const spot = () => chart().series[1]
const synthetic = () => chart().series[2]
const tooltip = () => screen.getByTestId('straddle-pnl-tooltip')

/** The page simulates on demand: wait for an expiry, then press Simulate. */
async function renderSimulated() {
  const view = render(<CustomStraddle />)
  const button = screen.getByRole('button', { name: 'Simulate' })
  await waitFor(() => expect(screen.getByText('28-OCT-26')).toBeInTheDocument())
  fireEvent.click(button)
  await waitFor(() => expect(pnl().setData).toHaveBeenCalled())
  return view
}

beforeEach(() => {
  harness.charts.length = 0
  harness.createChart.mockClear()
  harness.simulate.mockReset()
  respondWith(LOSING_RUN)
  useThemeStore.setState({ mode: 'light', appMode: 'live' })
})

afterEach(() => {
  useThemeStore.setState({ mode: 'light', appMode: 'live' })
})

describe('CustomStraddle', () => {
  it('draws P&L as a baseline at zero on the right, spot and synthetic on the left', async () => {
    render(<CustomStraddle />)
    expect(harness.createChart).toHaveBeenCalledTimes(1)
    expect(chart().options.shortcuts).toBe(false)

    expect(chart().series.map((s) => [s.type, s.options.priceScaleId])).toEqual([
      ['baseline', 'right'],
      ['line', 'left'],
      ['line', 'left'],
    ])
    // Profit and loss colours are the theme's, so the series names none of its own.
    const pnlStyle = pnl().options.style as Record<string, unknown>
    expect(pnlStyle).toMatchObject({ baseValue: 0, lineWidth: 2, visible: true })
    for (const key of ['topColor', 'bottomColor', 'areaTopColor', 'areaBottomColor']) {
      expect(pnlStyle).not.toHaveProperty(key)
    }
    expect(chart().options.theme.baselineTopLine).toBe(chart().options.theme.upColor)
    expect(chart().options.theme.baselineBottomLine).toBe(chart().options.theme.downColor)

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
    expect(pnl().scale).toHaveBeenCalledWith({ marginTop: 0.1, marginBottom: 0.1 })
    expect(spot().scale).toHaveBeenCalledWith({ marginTop: 0.05, marginBottom: 0.05 })
  })

  it('hands the engine the backend times as they are: real UTC seconds, in order', async () => {
    await renderSimulated()
    expect(pnl().setData).toHaveBeenLastCalledWith([
      { time: T0, value: 1234.5 },
      { time: T0 + 60, value: -1250.5 },
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

  it('quotes the hovered point in the tooltip, in the colour of its P&L', async () => {
    await renderSimulated()
    const theme = chart().options.theme
    expect(tooltip().style.display).toBe('')

    // The engine reports the hovered bar in UTC seconds: this is 09:15 IST.
    act(() => {
      for (const cb of chart().crosshair) cb({ time: T0, point: { x: 100, y: 80 } })
    })
    const text = tooltip().textContent ?? ''
    expect(tooltip().style.display).toBe('block')
    // Each label beside its own value.
    expect(text).toMatch(/P&L\s*1,234\.50/)
    expect(text).toMatch(/Spot\s*24,990\.25/)
    expect(text).toMatch(/ATM Strike\s*25000/)
    expect(text).toMatch(/Entry Strike\s*24950/)
    expect(text).toMatch(/Straddle\s*233\.90/)
    expect(text).toMatch(/Synthetic Fut\s*24,991\.10/)
    expect(text).toMatch(/Adjustments\s*3/)
    expect(text).toMatch(/27 Oct\s*09:15 AM/)
    expect(tooltip().firstElementChild?.getAttribute('style')).toContain(theme.upColor)

    act(() => {
      for (const cb of chart().crosshair) cb({ time: T0 + 60, point: { x: 120, y: 80 } })
    })
    expect(tooltip().textContent).toMatch(/P&L\s*-1,250\.50/)
    expect(tooltip().firstElementChild?.getAttribute('style')).toContain(theme.downColor)

    act(() => {
      for (const cb of chart().crosshair) cb({ time: null, point: null })
    })
    expect(tooltip().style.display).toBe('')
  })

  it('tags the P&L by where the run stands, and hands the tag to spot when P&L is hidden', async () => {
    await renderSimulated()
    const theme = chart().options.theme
    // The run ended in a loss.
    let tagged = chart().setTheme.mock.lastCall?.[0]
    expect(tagged.lastPriceUp).toBe(theme.downColor)
    expect(tagged.lastPriceDown).toBe(theme.downColor)

    fireEvent.click(screen.getByRole('button', { name: 'P&L' }))
    fireEvent.click(screen.getByRole('button', { name: 'Spot' }))
    expect(pnl().applyOptions).toHaveBeenLastCalledWith(expect.objectContaining({ visible: false }))
    expect(spot().applyOptions).toHaveBeenLastCalledWith(expect.objectContaining({ visible: true }))
    const spotColour = spot().applyOptions.mock.lastCall?.[0].color
    tagged = chart().setTheme.mock.lastCall?.[0]
    expect(tagged.lastPriceUp).toBe(spotColour)
    expect(tagged.lastPriceDown).toBe(spotColour)
  })

  it('tags a run that ended in profit in the profit colour', async () => {
    respondWith([point(T0, -500), point(T0 + 60, 750)])
    await renderSimulated()
    const tagged = chart().setTheme.mock.lastCall?.[0]
    expect(tagged.lastPriceUp).toBe(chart().options.theme.upColor)
  })

  it('re-themes the same chart for dark and analyzer instead of rebuilding it', async () => {
    await renderSimulated()
    const built = chart()
    const lightTheme = built.options.theme

    act(() => {
      useThemeStore.setState({ mode: 'dark' })
    })
    expect(harness.createChart).toHaveBeenCalledTimes(1)
    const dark = built.setTheme.mock.lastCall?.[0]
    expect(dark.upColor).not.toBe(lightTheme.upColor)
    // Still the losing run, now in the dark theme's loss colour.
    expect(dark.lastPriceUp).toBe(dark.downColor)
    expect(synthetic().applyOptions).toHaveBeenLastCalledWith(
      expect.objectContaining({ color: '#60a5fa' })
    )

    // Analyzer shares the dark pair, so what proves the switch landed is that
    // the same chart was re-themed again rather than a second one built.
    const before = built.setTheme.mock.calls.length
    act(() => {
      useThemeStore.setState({ appMode: 'analyzer' })
    })
    expect(built.setTheme.mock.calls.length).toBeGreaterThan(before)
    expect(built.setTheme.mock.lastCall?.[0].lastPriceUp).toBe(dark.downColor)
    expect(harness.createChart).toHaveBeenCalledTimes(1)
  })

  it('destroys the chart, drops the crosshair listener and empties the host on unmount', async () => {
    const { unmount } = await renderSimulated()
    const built = chart()
    expect(built.host.childElementCount).toBe(1)
    unmount()
    expect(built.destroyed).toBe(1)
    expect(built.unsubscribed).toBe(1)
    expect(built.host.childElementCount).toBe(0)
  })
})
