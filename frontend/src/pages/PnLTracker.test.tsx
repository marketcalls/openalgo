/**
 * What this pins.
 *
 * The engine and html2canvas are stubbed, not the wiring around them: the real
 * theme bridge runs, so the profit and loss colours below are the theme's own
 * pair. The assertions are about what the page asks the engine to do.
 *
 * Three of these guard a trader directly. The time base: the backend sends
 * real UTC milliseconds and the engine labels seconds in IST itself, so a +5:30
 * shift on the way in would place every minute of the day five and a half
 * hours late. The break-even: the MTM curve is split at zero, and a baseline
 * anywhere else paints a losing day green. And the screenshot, which is the
 * thing a trader shares: it must carry the chart, not a blank box where the
 * chart was.
 */

import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { CANDLE_PAIRS } from '@/lib/trading/chartTheme'
import { useThemeStore } from '@/stores/themeStore'
import PnLTracker from './PnLTracker'

interface SeriesStub {
  type: string
  options: { paneIndex?: number; style?: Record<string, unknown> } & Record<string, unknown>
  setData: ReturnType<typeof vi.fn>
  applyOptions: ReturnType<typeof vi.fn>
}

interface PriceLineStub {
  options: Record<string, unknown>
  pane: number | undefined
  setOptions: ReturnType<typeof vi.fn>
}

interface ChartStub {
  host: HTMLElement
  options: Record<string, unknown>
  series: SeriesStub[]
  priceLines: PriceLineStub[]
  weights: Map<number, number>
  setTheme: ReturnType<typeof vi.fn>
  fitContent: ReturnType<typeof vi.fn>
  takeScreenshot: ReturnType<typeof vi.fn>
  destroyed: number
}

const CHART_PNG = 'data:image/png;base64,Q0hBUlQ='

const harness = vi.hoisted(() => {
  const charts: ChartStub[] = []
  const createChart = vi.fn((host: HTMLElement, options: Record<string, unknown>) => {
    // The engine paints into its host: a canvas here is what the screenshot
    // has to leave out, and what the cleanup has to clear.
    host.appendChild(document.createElement('canvas'))
    const chart: ChartStub & Record<string, unknown> = {
      host,
      options,
      series: [],
      priceLines: [],
      weights: new Map(),
      setTheme: vi.fn(),
      fitContent: vi.fn(),
      takeScreenshot: vi.fn(() => ({ toDataURL: () => 'data:image/png;base64,Q0hBUlQ=' })),
      destroyed: 0,
      addSeries: (type: string, opts?: Record<string, unknown>) => {
        const series: SeriesStub = {
          type,
          options: opts ?? {},
          setData: vi.fn(),
          applyOptions: vi.fn(),
        }
        Object.assign(series, { priceScale: () => ({ setOptions: vi.fn() }) })
        chart.series.push(series)
        return series
      },
      addPriceLine: (opts: Record<string, unknown>, pane?: number) => {
        const line: PriceLineStub = { options: opts, pane, setOptions: vi.fn() }
        chart.priceLines.push(line)
        return line
      },
      setPaneWeight: (index: number, weight: number) => {
        chart.weights.set(index, weight)
      },
      destroy: () => {
        chart.destroyed += 1
      },
    }
    charts.push(chart)
    return chart
  })
  const html2canvas = vi.fn()
  return { charts, createChart, html2canvas }
})

vi.mock('openalgo-charts', () => ({
  createChart: harness.createChart,
  withAlpha: (color: string, alpha: number) => `${color}@${alpha}`,
  lightTheme: {},
  darkTheme: {},
}))

vi.mock('html2canvas-pro', () => ({ default: harness.html2canvas }))

vi.mock('@/utils/toast', () => ({ showToast: { error: vi.fn(), success: vi.fn() } }))

// 09:15 and 09:16 IST on 27 Oct 2025, in real UTC milliseconds as the backend sends them.
const T0 = 1_761_536_700

function pnlResponse(pnl: Array<[number, number]>, drawdown: Array<[number, number]>) {
  return {
    status: 'success',
    data: {
      current_mtm: pnl[pnl.length - 1][1],
      max_mtm: 0,
      max_mtm_time: '09:15:00',
      min_mtm: 0,
      min_mtm_time: '09:16:00',
      max_drawdown: -100,
      pnl_series: pnl.map(([time, value]) => ({ time: time * 1000, value })),
      drawdown_series: drawdown.map(([time, value]) => ({ time: time * 1000, value })),
    },
  }
}

let nextResponse = pnlResponse(
  // Out of order on purpose: the chart wants them sorted.
  [
    [T0 + 60, -250],
    [T0, 400],
  ],
  [
    [T0 + 60, -650],
    [T0, 0],
  ]
)

const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
  const url = String(input)
  const body = url.includes('/auth/csrf-token') ? { csrf_token: 'token' } : nextResponse
  return { ok: true, json: async () => body } as Response
})
const pnlFetches = () =>
  fetchMock.mock.calls.filter(([input]) => String(input).includes('/pnltracker/api/pnl')).length

const chart = () => harness.charts[harness.charts.length - 1]
const pnlSeries = () => chart().series[0]
const drawdownSeries = () => chart().series[1]

beforeEach(() => {
  harness.charts.length = 0
  harness.createChart.mockClear()
  harness.html2canvas.mockReset()
  fetchMock.mockClear()
  vi.stubGlobal('fetch', fetchMock)
  useThemeStore.setState({ mode: 'light', appMode: 'live' })
  nextResponse = pnlResponse(
    [
      [T0 + 60, -250],
      [T0, 400],
    ],
    [
      [T0 + 60, -650],
      [T0, 0],
    ]
  )
})

afterEach(() => {
  vi.unstubAllGlobals()
  const url = URL as unknown as Record<string, unknown>
  delete url.createObjectURL
  delete url.revokeObjectURL
})

describe('PnLTracker', () => {
  it('draws MTM over drawdown, 3 to 1, both split at zero', () => {
    render(<PnLTracker />)
    expect(harness.createChart).toHaveBeenCalledTimes(1)
    expect(chart().options.shortcuts).toBe(false)

    const [pnl, drawdown] = chart().series
    expect(pnl.type).toBe('baseline')
    expect(pnl.options.paneIndex).toBe(0)
    expect(pnl.options.style).toMatchObject({
      baseValue: 0,
      topColor: CANDLE_PAIRS.light.up,
      bottomColor: CANDLE_PAIRS.light.down,
    })
    expect(drawdown.type).toBe('baseline')
    expect(drawdown.options.paneIndex).toBe(1)
    expect(drawdown.options.style).toMatchObject({
      baseValue: 0,
      bottomColor: '#eab308',
      lastValueVisible: false,
    })
    expect(chart().weights.get(0)).toBe(3)
    expect(chart().weights.get(1)).toBe(1)
  })

  it('formats both axes as money', () => {
    render(<PnLTracker />)
    for (const series of chart().series) {
      const format = (series.options.priceFormat as { formatter: (v: number) => string }).formatter
      expect(format(1234.5)).toContain('1,234.50')
    }
  })

  it('hands the engine real UTC seconds, sorted, without an IST shift', async () => {
    render(<PnLTracker />)
    await waitFor(() => expect(pnlSeries().setData).toHaveBeenCalled())
    expect(pnlSeries().setData).toHaveBeenLastCalledWith([
      { time: T0, value: 400 },
      { time: T0 + 60, value: -250 },
    ])
    expect(drawdownSeries().setData).toHaveBeenLastCalledWith([
      { time: T0, value: 0 },
      { time: T0 + 60, value: -650 },
    ])
    expect(chart().fitContent).toHaveBeenCalled()
  })

  it('colours the MTM value tag by where the day stands', async () => {
    render(<PnLTracker />)
    await waitFor(() => expect(pnlSeries().setData).toHaveBeenCalled())
    // The day ended below zero, so the tag is the loss colour.
    expect(chart().setTheme).toHaveBeenLastCalledWith(
      expect.objectContaining({
        lastPriceUp: CANDLE_PAIRS.light.down,
        lastPriceDown: CANDLE_PAIRS.light.down,
      })
    )
  })

  it('marks the current drawdown in amber, and moves the mark on refresh', async () => {
    render(<PnLTracker />)
    await waitFor(() => expect(chart().priceLines).toHaveLength(1))
    const line = chart().priceLines[0]
    expect(line.pane).toBe(1)
    expect(line.options).toMatchObject({ price: -650, color: '#eab308' })

    nextResponse = pnlResponse([[T0, 100]], [[T0, -40]])
    fireEvent.click(screen.getByRole('button', { name: 'Refresh' }))
    await waitFor(() => expect(line.setOptions).toHaveBeenCalled())
    expect(line.setOptions).toHaveBeenLastCalledWith(expect.objectContaining({ price: -40 }))
    expect(chart().priceLines).toHaveLength(1)
  })

  it('re-themes in place on a theme change, without a rebuild or a refetch', async () => {
    render(<PnLTracker />)
    await waitFor(() => expect(pnlSeries().setData).toHaveBeenCalled())
    const fetches = pnlFetches()

    act(() => useThemeStore.setState({ mode: 'dark' }))

    expect(harness.createChart).toHaveBeenCalledTimes(1)
    expect(chart().setTheme).toHaveBeenLastCalledWith(
      expect.objectContaining({ upColor: CANDLE_PAIRS.dark.up })
    )
    expect(pnlSeries().applyOptions).toHaveBeenLastCalledWith(
      expect.objectContaining({
        topColor: CANDLE_PAIRS.dark.up,
        bottomColor: CANDLE_PAIRS.dark.down,
      })
    )
    expect(pnlFetches()).toBe(fetches)
  })

  it('puts the chart into the screenshot as the engine exports it', async () => {
    // jsdom has neither; set for this test and taken off again in afterEach.
    Object.assign(URL, { createObjectURL: vi.fn(() => 'blob:shot'), revokeObjectURL: vi.fn() })
    harness.html2canvas.mockResolvedValue({
      toBlob: (cb: (blob: Blob) => void) => cb(new Blob(['png'])),
    })
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})

    render(<PnLTracker />)
    await waitFor(() => expect(pnlSeries().setData).toHaveBeenCalled())
    fireEvent.click(screen.getByRole('button', { name: /Screenshot/ }))
    await waitFor(() => expect(harness.html2canvas).toHaveBeenCalledTimes(1))

    expect(chart().takeScreenshot).toHaveBeenCalledTimes(1)
    const [target, options] = harness.html2canvas.mock.calls[0] as [
      HTMLElement,
      {
        ignoreElements: (element: Element) => boolean
        onclone: (doc: Document) => void
      },
    ]
    // The whole report, cards included, as before.
    expect(target.textContent).toContain('Current MTM')
    expect(target.textContent).toContain('Intraday PnL Curve')

    // The chart's live canvases are left out; any other element is not.
    const liveCanvas = chart().host.querySelector('canvas') as HTMLCanvasElement
    expect(options.ignoreElements(liveCanvas)).toBe(true)
    expect(options.ignoreElements(document.createElement('canvas'))).toBe(false)
    expect(options.ignoreElements(chart().host)).toBe(false)

    // In the copy, the engine's export takes the chart's place.
    const copy = document.implementation.createHTMLDocument('copy')
    copy.body.innerHTML = '<div data-pnl-chart=""></div>'
    options.onclone(copy)
    const image = copy.querySelector('[data-pnl-chart] img') as HTMLImageElement
    expect(image.getAttribute('src')).toBe(CHART_PNG)

    await waitFor(() => expect(click).toHaveBeenCalled())
    click.mockRestore()
  })

  it('destroys the chart and empties its host on unmount', () => {
    const { unmount } = render(<PnLTracker />)
    const built = chart()
    unmount()
    expect(built.destroyed).toBe(1)
    expect(built.host.innerHTML).toBe('')
  })
})
