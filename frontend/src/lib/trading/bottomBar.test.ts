import {
  type Bar,
  type Chart,
  createChart,
  DEFAULT_TIMEZONE,
  SessionCalendar,
} from 'openalgo-charts'
import { DEFAULT_RANGES } from 'openalgo-charts/widget'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  applyRange,
  type BottomBarPane,
  mountTradingBottomBar,
  placeRange,
  rangeMessage,
} from './bottomBar'
import { calendarSpec } from './sessionHours'

const IST = 19_800
/** One-minute bars for each IST date, 09:15 to 15:29, on a price that wanders. */
function sessions(dates: string[]): Bar[] {
  const out: Bar[] = []
  let price = 812
  for (const date of dates) {
    const [y, m, d] = date.split('-').map(Number)
    const open = Date.UTC(y, m - 1, d, 9, 15) / 1000 - IST
    for (let i = 0; i < 375; i++) {
      price += Math.sin(out.length * 0.37) * 0.6
      out.push({ time: open + i * 60, open: price, high: price + 1, low: price - 1, close: price })
    }
  }
  return out
}

const charts: Chart[] = []
function chartWith(bars: Bar[]): Chart {
  const chart = createChart(document.createElement('div'), {
    shortcuts: false,
    timeNavigator: false,
    raf: {
      schedule: (cb) => {
        cb()
        return 1
      },
      cancel() {},
    },
  })
  chart.applySize(900, 500)
  chart.addSeries('candlestick').setData(bars)
  charts.push(chart)
  return chart
}

function pane(chart: Chart | null, overrides: Partial<BottomBarPane> = {}) {
  let range: string | null = null
  let interval = '1m'
  const element = document.createElement('div')
  const self = {
    liveChart: () => chart,
    chartElement: () => element,
    currentInterval: () => interval,
    supportedIntervals: () => ['1m', '5m', '15m', '1h', 'D'],
    showInterval: vi.fn(async (iv: string) => {
      interval = iv
      return true
    }),
    loadHistoryBack: vi.fn(async () => 'exhausted' as const),
    activeRange: () => range,
    setActiveRange: vi.fn((id: string | null) => {
      range = id
    }),
    applyChartSettings: vi.fn(async () => {}),
    ...overrides,
  }
  return { pane: self as BottomBarPane & typeof self, element }
}

const byId = (id: string) => DEFAULT_RANGES.find((r) => r.id === id)!

beforeEach(() => {
  const context = new Proxy(
    {
      measureText: (text: string) => ({ width: text.length * 7 }),
      createLinearGradient: () => ({ addColorStop() {} }),
      getImageData: () => ({ data: new Uint8ClampedArray([0, 0, 0, 255]) }),
    },
    { get: (target, key) => target[key as keyof typeof target] ?? (() => {}) }
  )
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(
    context as unknown as CanvasRenderingContext2D
  )
})
afterEach(() => {
  for (const chart of charts.splice(0)) chart.destroy()
  document.body.innerHTML = ''
  vi.restoreAllMocks()
})

describe('preset ranges', () => {
  it('switches to the interval the broker offers nearest the range, then marks it', async () => {
    const { pane: p } = pane(chartWith(sessions(['2026-09-28', '2026-09-29', '2026-09-30'])))
    await applyRange(p, '6M')
    expect(p.showInterval).toHaveBeenCalledWith('D')
    expect(p.setActiveRange).toHaveBeenCalledWith('6M')
    await applyRange(p, '1D')
    expect(p.showInterval).toHaveBeenLastCalledWith('1m')
  })

  it('leaves no range when the interval did not load', async () => {
    const { pane: p } = pane(chartWith(sessions(['2026-09-30'])), {
      showInterval: vi.fn(async () => false),
    })
    expect(await applyRange(p, '1D')).toEqual({ status: 'cancelled' })
    expect(p.setActiveRange).not.toHaveBeenCalled()
  })

  it('places one day on the last session the chart holds', async () => {
    const bars = sessions(['2026-09-28', '2026-09-29', '2026-09-30'])
    const { pane: p } = pane(chartWith(bars))
    const result = await placeRange(p, byId('1D'))
    expect(result.status).toBe('placed')
    expect(result.from).toBe(bars[750].time)
    expect(result.to).toBe(bars[bars.length - 1].time)
    expect(p.loadHistoryBack).not.toHaveBeenCalled()
  })

  it('asks for older history and says plainly when the broker has less', async () => {
    const bars = sessions(['2026-09-29', '2026-09-30'])
    const chart = chartWith(bars)
    // NSE hours: five sessions back reach before the bars the chart holds.
    const nse = [{ exchange: 'NSE', start_offset: 33_300_000, end_offset: 55_800_000 }]
    chart.setSessionCalendar(new SessionCalendar(calendarSpec('NSE', nse, [])))
    const { pane: p } = pane(chart)
    const result = await placeRange(p, byId('5D'))
    expect(p.loadHistoryBack).toHaveBeenCalled()
    expect(result).toMatchObject({ status: 'partial', history: 'exhausted', from: bars[0].time })
    expect(rangeMessage(byId('5D'), result, DEFAULT_TIMEZONE)).toBe(
      "The broker's history at this interval starts on 29 Sept 2026, so 5D shows from there."
    )
  })

  it('treats all of the history as the whole range', async () => {
    const { pane: p } = pane(chartWith(sessions(['2026-09-30'])))
    expect((await placeRange(p, byId('ALL'))).status).not.toBe('partial')
  })

  it('has nothing to place without bars', async () => {
    const { pane: p } = pane(null)
    expect(await placeRange(p, byId('1D'))).toEqual({ status: 'no-data' })
    expect(rangeMessage(byId('1D'), { status: 'no-data' }, DEFAULT_TIMEZONE)).toBe(
      'No bars to show for 1D.'
    )
  })

  it('words a failed load without the technical detail', () => {
    const text = rangeMessage(
      byId('1Y'),
      { status: 'error', error: new Error('history failed (500)') },
      DEFAULT_TIMEZONE
    )
    expect(text).toBe(
      '1Y could not be shown: the broker did not return older bars. Try again in a moment.'
    )
  })
})

describe('the bar', () => {
  function mountBar(p: BottomBarPane | null) {
    const root = document.createElement('div')
    document.body.appendChild(root)
    const notify = vi.fn()
    const bar = mountTradingBottomBar(root, { pane: () => p, notify })
    return { root, bar, notify }
  }

  it('shows the ranges, Go to, the clock and the scale toggles on one strip', () => {
    const { pane: p } = pane(chartWith(sessions(['2026-09-30'])))
    const { root, bar } = mountBar(p)
    const strip = root.querySelector('.oac-bottombar')!
    expect([...strip.querySelectorAll('[data-range]')].map((b) => b.textContent)).toEqual([
      '1D',
      '5D',
      '1M',
      '3M',
      '6M',
      'YTD',
      '1Y',
      '5Y',
      'All',
    ])
    expect(strip.querySelector('.oac-bottombar__goto')).not.toBeNull()
    expect(strip.querySelectorAll('[data-scale]')).toHaveLength(3)
    bar.destroy()
    expect(root.querySelector('.oac-bottombar')).toBeNull()
  })

  it('keeps a scale toggle in the pane chart settings', () => {
    const chart = chartWith(sessions(['2026-09-30']))
    const { pane: p } = pane(chart)
    const { root, bar } = mountBar(p)
    root.querySelector<HTMLElement>('[data-scale="log"]')!.click()
    expect(p.applyChartSettings).toHaveBeenCalledWith({ 'scales.mode': 'logarithmic' })
    root.querySelector<HTMLElement>('[data-scale="auto"]')!.click()
    expect(p.applyChartSettings).toHaveBeenLastCalledWith({ 'scales.autoScale': false })
    bar.destroy()
  })

  it('puts a saved range back once the pane has loaded', async () => {
    const bars = sessions(['2026-09-29', '2026-09-30'])
    const chart = chartWith(bars)
    const { pane: p } = pane(chart)
    p.setActiveRange('1D')
    const { bar } = mountBar(p)
    bar.paneLoaded(p)
    await vi.waitFor(() => expect(chart.getVisibleLogicalRange().from).toBeGreaterThanOrEqual(374))
    bar.destroy()
  })

  it('opens Go to over the charts and holds the page Escape while it is open', () => {
    const { pane: p } = pane(chartWith(sessions(['2026-09-30'])))
    const { root, bar } = mountBar(p)
    root.querySelector<HTMLElement>('.oac-bottombar__goto')!.click()
    expect(root.querySelector('.oac-goto')).not.toBeNull()
    expect(root.dataset.tradingDialogOpen).toBe('true')
    bar.destroy()
  })

  it('asks the trader to wait when no chart has loaded', () => {
    const { root, bar, notify } = mountBar(pane(null).pane)
    const goTo = root.querySelector<HTMLElement>('.oac-bottombar__goto')!
    expect(goTo.getAttribute('aria-disabled')).toBe('true')
    bar.destroy()
    expect(notify).not.toHaveBeenCalled()
  })
})
