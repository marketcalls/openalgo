/**
 * What this pins.
 *
 * The engine is stubbed, not the wiring around it: the real theme bridge runs,
 * so the call and put colours below are the theme's own up and down pair. Only
 * `createChart`, the IV API and the exchange hook are stubs, because the
 * assertions are about what the page asks the engine to do.
 *
 * The one that guards a trader most directly is the time base. The backend
 * sends real UTC seconds and the engine labels them in IST itself, so a time
 * shifted by +5:30 on the way in (as the previous chart needed, for its own
 * formatter) would label every reading five and a half hours late.
 */

import { act, render, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { CANDLE_PAIRS } from '@/lib/trading/chartTheme'
import { useThemeStore } from '@/stores/themeStore'
import IVChart from './IVChart'

interface SeriesStub {
  type: string
  options: Record<string, unknown>
  setData: ReturnType<typeof vi.fn>
  applyOptions: ReturnType<typeof vi.fn>
  priceScale: () => { setOptions: ReturnType<typeof vi.fn> }
}

interface ChartStub {
  host: HTMLElement
  options: Record<string, unknown>
  series: SeriesStub[]
  setTheme: ReturnType<typeof vi.fn>
  fitContent: ReturnType<typeof vi.fn>
  destroyed: number
}

const harness = vi.hoisted(() => {
  const charts: ChartStub[] = []
  const createChart = vi.fn((host: HTMLElement, options: Record<string, unknown>) => {
    // The engine paints into its host; something has to be there for the
    // cleanup's clearing of the host to be observable.
    host.appendChild(document.createElement('canvas'))
    const chart: ChartStub & Record<string, unknown> = {
      host,
      options,
      series: [],
      setTheme: vi.fn(),
      fitContent: vi.fn(),
      destroyed: 0,
      addSeries: (type: string, opts?: Record<string, unknown>) => {
        const series: SeriesStub = {
          type,
          options: opts ?? {},
          setData: vi.fn(),
          applyOptions: vi.fn(),
          priceScale: () => ({ setOptions: vi.fn() }),
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
  const api = {
    getIntervals: vi.fn(),
    getUnderlyings: vi.fn(),
    getExpiries: vi.fn(),
    getIVData: vi.fn(),
  }
  const exchanges = {
    toolsFnoExchanges: [{ value: 'NFO', label: 'NFO' }],
    defaultToolsFnoExchange: 'NFO',
    defaultUnderlyings: { NFO: ['NIFTY'] },
  }
  return { charts, createChart, api, exchanges }
})

vi.mock('openalgo-charts', () => ({
  createChart: harness.createChart,
  lightTheme: {},
  darkTheme: {},
}))

vi.mock('@/api/iv-chart', () => ({ ivChartApi: harness.api }))

vi.mock('@/hooks/useSupportedExchanges', () => ({
  useSupportedExchanges: () => harness.exchanges,
}))

vi.mock('@/utils/toast', () => ({ showToast: { error: vi.fn(), success: vi.fn() } }))

// 09:15 and 09:20 IST on 27 Oct 2025, in real UTC seconds as the backend sends them.
const T0 = 1_761_536_700
const point = (time: number, iv: number | null) => ({
  time,
  iv,
  delta: 0.5,
  gamma: 0.001,
  theta: -10,
  vega: 5,
  option_price: 100,
  underlying_price: 25000,
})

const DATA = {
  underlying: 'NIFTY',
  underlying_ltp: 25000,
  atm_strike: 25000,
  ce_symbol: 'NIFTY28OCT2525000CE',
  pe_symbol: 'NIFTY28OCT2525000PE',
  interval: '5m',
  series: [
    {
      symbol: 'NIFTY28OCT2525000CE',
      option_type: 'CE',
      strike: 25000,
      // Out of order, with a gap: the chart wants them sorted and the gap dropped.
      iv_data: [point(T0 + 300, 13.5), point(T0 + 150, null), point(T0, 12.25)],
    },
    {
      symbol: 'NIFTY28OCT2525000PE',
      option_type: 'PE',
      strike: 25000,
      iv_data: [point(T0, 14), point(T0 + 300, 14.75)],
    },
  ],
}

/** The chart drawn for one panel, found by the label the page gave it. */
const chartFor = (label: string) => {
  const found = harness.charts.filter((c) => c.options.ariaLabel === label && c.destroyed === 0)
  return found[found.length - 1]
}

beforeEach(() => {
  harness.charts.length = 0
  harness.createChart.mockClear()
  useThemeStore.setState({ mode: 'light', appMode: 'live' })
  harness.api.getIntervals.mockResolvedValue({
    status: 'success',
    data: { seconds: [], minutes: ['5m'], hours: [] },
  })
  harness.api.getUnderlyings.mockResolvedValue({ status: 'success', underlyings: ['NIFTY'] })
  harness.api.getExpiries.mockResolvedValue({ status: 'success', expiries: ['28-OCT-25'] })
  harness.api.getIVData.mockResolvedValue({ status: 'success', data: DATA })
})

describe('IVChart', () => {
  it('draws ten read-only line charts, the call in the up colour and the put in the down', () => {
    render(<IVChart />)
    const live = harness.charts.filter((c) => c.destroyed === 0)
    expect(live).toHaveLength(10)
    for (const chart of live) {
      expect(chart.options.shortcuts).toBe(false)
      expect(chart.series).toHaveLength(1)
      expect(chart.series[0].type).toBe('line')
    }
    const ce = chartFor('CE IV chart')
    const pe = chartFor('PE IV chart')
    expect(ce.series[0].options.style).toMatchObject({ color: CANDLE_PAIRS.light.up })
    expect(pe.series[0].options.style).toMatchObject({ color: CANDLE_PAIRS.light.down })
    // The value tag carries the side's colour, not the last move's.
    expect(ce.options.theme).toMatchObject({
      lastPriceUp: CANDLE_PAIRS.light.up,
      lastPriceDown: CANDLE_PAIRS.light.up,
    })
  })

  it('formats each metric on its own axis', () => {
    render(<IVChart />)
    const format = (label: string) =>
      (chartFor(label).series[0].options.priceFormat as { formatter: (v: number) => string })
        .formatter
    expect(format('CE IV chart')(12.3456)).toBe('12.35%')
    expect(format('PE Gamma chart')(0.0012347)).toBe('0.001235')
  })

  it('hands the engine real UTC seconds, sorted, with the gaps left out', async () => {
    render(<IVChart />)
    const ce = chartFor('CE IV chart')
    await waitFor(() => expect(ce.series[0].setData).toHaveBeenCalled())
    expect(ce.series[0].setData).toHaveBeenLastCalledWith([
      { time: T0, value: 12.25 },
      { time: T0 + 300, value: 13.5 },
    ])
    expect(ce.fitContent).toHaveBeenCalled()
    expect(chartFor('PE IV chart').series[0].setData).toHaveBeenLastCalledWith([
      { time: T0, value: 14 },
      { time: T0 + 300, value: 14.75 },
    ])
  })

  it('re-themes the charts in place when the theme changes', async () => {
    render(<IVChart />)
    const created = harness.createChart.mock.calls.length
    const ce = chartFor('CE IV chart')
    const pe = chartFor('PE IV chart')

    act(() => useThemeStore.setState({ mode: 'dark' }))

    expect(harness.createChart.mock.calls.length).toBe(created)
    expect(ce.setTheme).toHaveBeenLastCalledWith(
      expect.objectContaining({ upColor: CANDLE_PAIRS.dark.up, lastPriceUp: CANDLE_PAIRS.dark.up })
    )
    expect(ce.series[0].applyOptions).toHaveBeenLastCalledWith({ color: CANDLE_PAIRS.dark.up })
    expect(pe.series[0].applyOptions).toHaveBeenLastCalledWith({ color: CANDLE_PAIRS.dark.down })

    const before = ce.setTheme.mock.calls.length
    act(() => useThemeStore.setState({ appMode: 'analyzer' }))
    expect(ce.setTheme).toHaveBeenCalledTimes(before + 1)
    expect(harness.createChart.mock.calls.length).toBe(created)
  })

  it('destroys every chart and empties its host on unmount', () => {
    const { unmount } = render(<IVChart />)
    const live = harness.charts.filter((c) => c.destroyed === 0)
    expect(live).toHaveLength(10)
    unmount()
    for (const chart of live) {
      expect(chart.destroyed).toBe(1)
      expect(chart.host.innerHTML).toBe('')
    }
  })
})
