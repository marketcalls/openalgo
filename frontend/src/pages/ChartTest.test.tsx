/**
 * What this pins about the chart test page.
 *
 * The engine is stubbed, not the wiring around it: the real theme bridge runs,
 * and only `createChart`, the network and the market-data hook are stubs,
 * because the assertions are about what the page asks the engine to do.
 *
 * The time base matters most. `/chart/test/api/history` returns bar times with
 * +5:30 added, and live ticks are bucketed in that same shifted base so the two
 * line up. The engine wants real UTC and labels it in IST by itself, so a bar
 * handed over still shifted labels every candle 5h30m late, without failing.
 *
 * The page also builds and removes several charts, so removing one must
 * destroy exactly that one and leave the others drawing.
 */

import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useThemeStore } from '@/stores/themeStore'

const IST = 19800

interface SeriesStub {
  type: string
  options: { style?: Record<string, unknown> }
  setData: ReturnType<typeof vi.fn>
  update: ReturnType<typeof vi.fn>
}

interface ChartStub {
  host: HTMLElement
  options: Record<string, unknown>
  series: SeriesStub[]
  setTheme: ReturnType<typeof vi.fn>
  fitContent: ReturnType<typeof vi.fn>
  setVisibleLogicalRange: ReturnType<typeof vi.fn>
  destroyed: number
}

const harness = vi.hoisted(() => {
  const charts: ChartStub[] = []
  const createChart = vi.fn((host: HTMLElement, options: Record<string, unknown>) => {
    // The engine draws into its host; a canvas stands in so the cleanup has
    // something to clear.
    host.appendChild(document.createElement('canvas'))
    const chart: ChartStub & Record<string, unknown> = {
      host,
      options,
      series: [],
      setTheme: vi.fn(),
      fitContent: vi.fn(),
      setVisibleLogicalRange: vi.fn(),
      getVisibleLogicalRange: () => ({ from: 1, to: 2 }),
      destroyed: 0,
      addSeries: (type: string, opts?: SeriesStub['options']) => {
        const series: SeriesStub = {
          type,
          options: opts ?? {},
          setData: vi.fn(),
          update: vi.fn(),
        }
        chart.series.push(series)
        return series
      },
      destroy: () => {
        chart.destroyed += 1
      },
    }
    charts.push(chart)
    return chart
  })
  const quotes = { data: new Map<string, { data: Record<string, unknown> }>() }
  return { charts, createChart, quotes }
})

vi.mock('openalgo-charts', () => ({
  createChart: harness.createChart,
  lightTheme: {},
  darkTheme: {},
}))

vi.mock('@/hooks/useMarketData', () => ({
  useMarketData: () => ({ data: harness.quotes.data, isAuthenticated: true }),
}))

vi.mock('@/utils/toast', () => ({ showToast: { info: vi.fn(), success: vi.fn(), error: vi.fn() } }))

import ChartTest from './ChartTest'

// 09:15 and 09:16 IST in real UTC seconds, and as the backend sends them.
const T0 = Date.UTC(2026, 9, 27, 3, 45, 0) / 1000
const HISTORY = [
  { time: T0 + IST, open: 100, high: 102, low: 99, close: 101, volume: 500 },
  { time: T0 + 60 + IST, open: 101, high: 104, low: 100, close: 103, volume: 700 },
]

const SEARCH = [
  { symbol: 'RELIANCE', exchange: 'NSE', name: 'Reliance Industries' },
  { symbol: 'INFY', exchange: 'NSE', name: 'Infosys' },
]

const historyCalls: string[] = []

function stubFetch() {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => ({
      json: async () => {
        if (url.startsWith('/search/api/search')) return { results: SEARCH }
        historyCalls.push(url)
        return { status: 'success', candles: HISTORY, date: '2026-10-27' }
      },
    }))
  )
}

const chartFor = (symbol: string) => {
  const found = harness.charts.find((c) => String(c.options.ariaLabel).startsWith(`${symbol} `))
  if (!found) throw new Error(`no chart for ${symbol}`)
  return found
}

async function addChart(symbol: string) {
  fireEvent.change(screen.getByPlaceholderText(/Search symbol/), { target: { value: symbol } })
  const option = await screen.findByText(symbol, { selector: 'div' })
  fireEvent.mouseDown(option)
  await waitFor(() => expect(chartFor(symbol).series[0].setData).toHaveBeenCalled())
}

function pushTick(symbol: string, ltp: number, utcSeconds: number) {
  harness.quotes.data = new Map([
    [`NSE:${symbol}`, { data: { ltp, timestamp: new Date(utcSeconds * 1000).toISOString() } }],
  ])
}

beforeEach(() => {
  harness.charts.length = 0
  harness.createChart.mockClear()
  harness.quotes.data = new Map()
  historyCalls.length = 0
  stubFetch()
  useThemeStore.setState({ mode: 'light', appMode: 'live' })
  document.documentElement.classList.remove('dark', 'analyzer')
})

describe('ChartTest charts', () => {
  it('hands the engine real UTC seconds, for history and for the live candle', async () => {
    const { rerender } = render(<ChartTest />)
    await addChart('RELIANCE')
    const candles = chartFor('RELIANCE').series[0]

    const bars = candles.setData.mock.lastCall?.[0] as Array<Record<string, number>>
    expect(bars.map((b) => b.time)).toEqual([T0, T0 + 60])
    expect(bars[1]).toMatchObject({ open: 101, high: 104, low: 100, close: 103 })

    // 09:17:05 IST opens the next 1m candle, 09:17:40 extends it.
    pushTick('RELIANCE', 105, T0 + 125)
    rerender(<ChartTest />)
    pushTick('RELIANCE', 107, T0 + 160)
    rerender(<ChartTest />)

    expect(candles.update).toHaveBeenLastCalledWith({
      time: T0 + 120,
      open: 105,
      high: 107,
      low: 105,
      close: 107,
    })
  })

  it('draws theme-coloured candles with the page keyboard left alone', async () => {
    render(<ChartTest />)
    await addChart('RELIANCE')
    const chart = chartFor('RELIANCE')

    expect(chart.options.shortcuts).toBe(false)
    expect(chart.options.timeNavigator).toBe(false)
    expect(chart.options.branding).toBe(false)
    expect(chart.options.timeFormatter).toBeUndefined()
    expect(chart.options.timezone).toBeUndefined()
    expect(chart.series).toHaveLength(1)
    expect(chart.series[0].type).toBe('candlestick')
    // No palette of its own: the candle pair comes from the theme.
    expect(chart.series[0].options.style).toEqual({ borderVisible: false })
    // The chart sits in a card, so it takes the card's ground, not the page's.
    // jsdom has no canvas to resolve the token with, so it comes back as named.
    expect((chart.options.theme as Record<string, string>).background).toContain('--card')
    // A first load shows the whole range.
    expect(chart.fitContent).toHaveBeenCalledTimes(1)
  })

  it('switches the timeframe on the same chart instead of building a new one', async () => {
    render(<ChartTest />)
    await addChart('RELIANCE')
    const chart = chartFor('RELIANCE')

    fireEvent.click(screen.getByRole('button', { name: '5m' }))

    await waitFor(() => expect(historyCalls.at(-1)).toContain('interval=5m'))
    await waitFor(() => expect(chart.fitContent).toHaveBeenCalledTimes(2))
    expect(harness.createChart).toHaveBeenCalledTimes(1)
    expect(chart.destroyed).toBe(0)
  })

  it('re-themes every chart in place for dark and for the analyzer', async () => {
    render(<ChartTest />)
    await addChart('RELIANCE')
    await addChart('INFY')
    for (const chart of harness.charts) chart.setTheme.mockClear()

    act(() => useThemeStore.getState().setMode('dark'))
    for (const chart of harness.charts) expect(chart.setTheme).toHaveBeenCalledTimes(1)
    act(() => useThemeStore.getState().setAppMode('analyzer'))
    for (const chart of harness.charts) expect(chart.setTheme).toHaveBeenCalledTimes(2)

    expect(harness.createChart).toHaveBeenCalledTimes(2)
  })

  it('destroys exactly the chart that is removed, and the rest with Remove all', async () => {
    render(<ChartTest />)
    await addChart('RELIANCE')
    await addChart('INFY')
    const reliance = chartFor('RELIANCE')
    const infy = chartFor('INFY')

    fireEvent.click(screen.getAllByTitle('Remove')[0])

    expect(reliance.destroyed).toBe(1)
    expect(reliance.host.innerHTML).toBe('')
    expect(infy.destroyed).toBe(0)
    expect(infy.host.childElementCount).toBe(1)

    fireEvent.click(screen.getByRole('button', { name: 'Remove all' }))

    expect(reliance.destroyed).toBe(1)
    expect(infy.destroyed).toBe(1)
    expect(infy.host.innerHTML).toBe('')
  })

  it('destroys every chart when the page unmounts', async () => {
    const { unmount } = render(<ChartTest />)
    await addChart('RELIANCE')
    await addChart('INFY')

    unmount()

    for (const chart of harness.charts) expect(chart.destroyed).toBe(1)
  })
})
