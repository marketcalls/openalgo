import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { MultiStrikeOIResponse, StrategyChartResponse } from '@/api/strategy-chart'
import {
  createMultiStrikeOIFeed,
  createStrategyChartFeed,
  type StrategyFeedRequest,
} from './strategyFeed'

const mocks = vi.hoisted(() => ({
  getStrategyChart: vi.fn(),
  getMultiStrikeOI: vi.fn(),
}))

vi.mock('@/api/strategy-chart', () => ({
  strategyChartApi: {
    getStrategyChart: mocks.getStrategyChart,
    getMultiStrikeOI: mocks.getMultiStrikeOI,
  },
}))

interface Deferred<T> {
  promise: Promise<T>
  resolve: (value: T) => void
}

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => {
    resolve = done
  })
  return { promise, resolve }
}

const LEG = {
  symbol: 'NIFTY22SEP2623100CE',
  exchange: 'NFO',
  side: 'BUY' as const,
  segment: 'OPTION' as const,
  active: true,
  price: 223.55,
}

function request(overrides: Partial<StrategyFeedRequest> = {}): StrategyFeedRequest {
  return {
    underlying: 'NIFTY',
    exchange: 'NSE_INDEX',
    underlyingSymbol: 'NIFTY',
    underlyingExchange: 'NSE_INDEX',
    legs: [LEG],
    ...overrides,
  }
}

function premium(underlying: string, series: StrategyChartResponse['data']): StrategyChartResponse {
  return {
    status: 'success',
    data: {
      underlying,
      underlying_ltp: 23_000,
      interval: '5m',
      tag: 'debit',
      entry_net_premium: -56.75,
      entry_abs_premium: 56.75,
      legs_used: 1,
      underlying_available: true,
      series: [],
      ...series,
    } as NonNullable<StrategyChartResponse['data']>,
  }
}

const ask = { symbol: 'NIFTY PREMIUM', exchange: 'NFO', interval: '5m' }

beforeEach(() => {
  vi.clearAllMocks()
})

describe('createStrategyChartFeed', () => {
  it('hands the combined premium to the chart as its bars', async () => {
    mocks.getStrategyChart.mockResolvedValue(
      premium('NIFTY', {
        series: [
          { time: 1_700_000_300, underlying: 23_010, net_premium: -60, combined_premium: 60 },
          { time: 1_700_000_000, underlying: 23_000, net_premium: -56.75, combined_premium: 56.75 },
        ],
      })
    )
    const feed = createStrategyChartFeed({ read: () => request(), onPayload: vi.fn() })

    const bars = await feed.getBars(ask)

    // Oldest first, whatever order the response arrived in: the data layer
    // indexes by time and a reader cannot tell a mis-ordered payload from a
    // mis-drawn chart.
    expect(bars.map((b) => b.time)).toEqual([1_700_000_000, 1_700_000_300])
    // The premium is the primary series, which is the whole reason the numbers
    // travel as bars: an indicator reads this and nothing else.
    expect(bars.map((b) => b.close)).toEqual([56.75, 60])
    // One sampled value per point, so the bar is flat rather than inventing a
    // range the endpoint never reported.
    expect(bars[0]).toMatchObject({ open: 56.75, high: 56.75, low: 56.75, close: 56.75 })
  })

  it('sends the timeframe the chart asked for', async () => {
    mocks.getStrategyChart.mockResolvedValue(premium('NIFTY', { series: [] }))
    const feed = createStrategyChartFeed({ read: () => request(), onPayload: vi.fn() })

    await feed.getBars({ ...ask, interval: '15m' })

    expect(mocks.getStrategyChart).toHaveBeenCalledWith(
      expect.objectContaining({
        interval: '15m',
        underlying: 'NIFTY',
        underlying_symbol: 'NIFTY',
        underlying_exchange: 'NSE_INDEX',
      })
    )
  })

  it('asks for the window the chart asked for, as IST dates', async () => {
    mocks.getStrategyChart.mockResolvedValue(premium('NIFTY', { series: [] }))
    const feed = createStrategyChartFeed({ read: () => request(), onPayload: vi.fn() })

    // 2023-11-14 22:13:20 UTC is already the 15th in IST, which is the whole
    // reason the conversion is done by zone rather than by a UTC date.
    await feed.getBars({ ...ask, from: 1_700_000_000, to: 1_700_100_000 })

    expect(mocks.getStrategyChart).toHaveBeenCalledWith(
      expect.objectContaining({ start_date: '2023-11-14', end_date: '2023-11-17' })
    )
  })

  it('moves the window back when the chart pages older history', async () => {
    mocks.getStrategyChart.mockResolvedValue(premium('NIFTY', { series: [] }))
    const feed = createStrategyChartFeed({ read: () => request(), onPayload: vi.fn() })

    await feed.getBars({ ...ask, from: 1_700_000_000, to: 1_700_100_000 })
    // What `loadMore` sends once the reader scrolls past the left edge.
    await feed.getBars({ ...ask, from: 1_699_000_000, to: 1_699_999_999 })

    const [first, second] = mocks.getStrategyChart.mock.calls.map((c) => c[0])
    // Without this the endpoint would answer both with the same recent slice,
    // counted back from today, and the chart would stop at wherever it landed.
    expect(second.start_date < first.start_date).toBe(true)
    expect(second.end_date < first.end_date).toBe(true)
  })

  it('names no window when the chart did not bound the request', async () => {
    mocks.getStrategyChart.mockResolvedValue(premium('NIFTY', { series: [] }))
    const feed = createStrategyChartFeed({ read: () => request(), onPayload: vi.fn() })

    await feed.getBars(ask)

    // An unbounded request wants whatever history there is, so the endpoint's
    // own lookback applies rather than a range invented here.
    const sent = mocks.getStrategyChart.mock.calls[0][0]
    expect(sent.start_date).toBeUndefined()
    expect(sent.days).toBeGreaterThan(0)
  })

  it('drops a point whose premium is not a number', async () => {
    mocks.getStrategyChart.mockResolvedValue(
      premium('NIFTY', {
        series: [
          { time: 1_700_000_000, net_premium: -10, combined_premium: 10 },
          // A gap. Drawn as zero this would read as a spread that collapsed to
          // nothing, which is a number someone might act on.
          {
            time: 1_700_000_300,
            net_premium: Number.NaN,
            combined_premium: Number.NaN,
          },
          { time: 1_700_000_600, net_premium: -12, combined_premium: 12 },
        ],
      })
    )
    const feed = createStrategyChartFeed({ read: () => request(), onPayload: vi.fn() })

    const bars = await feed.getBars(ask)

    expect(bars.map((b) => b.time)).toEqual([1_700_000_000, 1_700_000_600])
  })

  it('fetches nothing and reports nothing when there are no legs', async () => {
    const onPayload = vi.fn()
    const feed = createStrategyChartFeed({ read: () => request({ legs: [] }), onPayload })

    await expect(feed.getBars(ask)).resolves.toEqual([])

    expect(mocks.getStrategyChart).not.toHaveBeenCalled()
    expect(onPayload).toHaveBeenCalledWith(null, { paging: false })
  })

  it('fetches nothing before the page has an underlying', async () => {
    const feed = createStrategyChartFeed({ read: () => null, onPayload: vi.fn() })
    await expect(feed.getBars(ask)).resolves.toEqual([])
    expect(mocks.getStrategyChart).not.toHaveBeenCalled()
  })

  it('rejects with the backend message so the chart offers a retry', async () => {
    mocks.getStrategyChart.mockResolvedValue({
      status: 'error',
      message: 'No history in this window',
    })
    const onPayload = vi.fn()
    const feed = createStrategyChartFeed({ read: () => request(), onPayload })

    // The client resolves 4xx rather than throwing, so without this the message
    // would be swallowed and the previous chart would stay up with no sign that
    // the new request failed.
    await expect(feed.getBars(ask)).rejects.toThrow('No history in this window')
    expect(onPayload).toHaveBeenCalledWith(null, { paging: false })
  })

  it('keeps the newer request displayed when an older one resolves later', async () => {
    const first = deferred<StrategyChartResponse>()
    const second = deferred<StrategyChartResponse>()
    mocks.getStrategyChart.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise)

    const onPayload = vi.fn()
    let underlying = 'BTC'
    const feed = createStrategyChartFeed({
      read: () => request({ underlying }),
      onPayload,
    })

    const a = feed.getBars(ask)
    underlying = 'ETH'
    const b = feed.getBars(ask)

    second.resolve(premium('ETH', { series: [] }))
    await b
    expect(onPayload).toHaveBeenLastCalledWith(expect.objectContaining({ underlying: 'ETH' }), {
      paging: false,
    })

    first.resolve(premium('BTC', { series: [] }))
    await a
    // The engine discards the stale bars on its own, but only after `getBars`
    // has resolved, by which time the payload channel has already fired. The
    // readout must not fall back to the instrument the chart stopped showing.
    expect(onPayload).toHaveBeenLastCalledWith(expect.objectContaining({ underlying: 'ETH' }), {
      paging: false,
    })
    expect(onPayload).not.toHaveBeenCalledWith(
      expect.objectContaining({ underlying: 'BTC' }),
      expect.anything()
    )
  })

  it('does not report a superseded failure either', async () => {
    const first = deferred<StrategyChartResponse>()
    const second = deferred<StrategyChartResponse>()
    mocks.getStrategyChart.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise)

    const onPayload = vi.fn()
    const feed = createStrategyChartFeed({ read: () => request(), onPayload })

    const a = feed.getBars(ask)
    const b = feed.getBars(ask)

    second.resolve(premium('NIFTY', { series: [] }))
    await b
    first.resolve({ status: 'error', message: 'obsolete' })

    // Resolves empty rather than rejecting: an abandoned request has no news.
    await expect(a).resolves.toEqual([])
    expect(onPayload).toHaveBeenLastCalledWith(expect.objectContaining({ underlying: 'NIFTY' }), {
      paging: false,
    })
  })

  it('marks a scroll into older history as a page', async () => {
    mocks.getStrategyChart.mockResolvedValue(premium('NIFTY', { series: [] }))
    const onPayload = vi.fn()
    const feed = createStrategyChartFeed({ read: () => request(), onPayload })

    // `before` is the exclusive time the chart already holds bars from, and is
    // the only thing that distinguishes a page from a fresh load of an old
    // range. A host that mistook one for the other would shrink every overlay
    // to the older window.
    await feed.getBars({ ...ask, from: 1_699_000_000, to: 1_700_000_000, before: 1_700_000_000 })

    expect(onPayload).toHaveBeenCalledWith(expect.anything(), { paging: true })
  })

  it('says nothing at all when a page fails', async () => {
    mocks.getStrategyChart.mockResolvedValue({ status: 'error', message: 'broker said no' })
    const onPayload = vi.fn()
    const feed = createStrategyChartFeed({ read: () => request(), onPayload })

    await expect(
      feed.getBars({ ...ask, from: 1_699_000_000, to: 1_700_000_000, before: 1_700_000_000 })
    ).rejects.toThrow('broker said no')

    // A page that could not be fetched is no news about the range already
    // drawn. The engine shows its own failed-page row; clearing the host's
    // state would blank a chart that still holds every bar it had.
    expect(onPayload).not.toHaveBeenCalled()
  })

  it('publishes the whole response, not only what became bars', async () => {
    const onPayload = vi.fn()
    mocks.getStrategyChart.mockResolvedValue(
      premium('NIFTY', { series: [], underlying_available: false })
    )
    const feed = createStrategyChartFeed({ read: () => request(), onPayload })

    await feed.getBars(ask)

    // The tab needs the entry premium, the tag and the underlying points, and
    // fetching twice for them would double every broker call.
    expect(onPayload).toHaveBeenCalledWith(
      expect.objectContaining({ entry_abs_premium: 56.75, underlying_available: false }),
      { paging: false }
    )
  })
})

describe('createMultiStrikeOIFeed', () => {
  const oi = (underlyingSeries: { time: number; value: number }[]): MultiStrikeOIResponse => ({
    status: 'success',
    data: {
      underlying: 'NIFTY',
      underlying_ltp: 23_000,
      interval: '5m',
      underlying_available: underlyingSeries.length > 0,
      underlying_series: underlyingSeries,
      legs: [],
    },
  })

  it('makes the underlying the primary series, so a study reads the index', async () => {
    mocks.getMultiStrikeOI.mockResolvedValue(
      oi([
        { time: 1_700_000_300, value: 23_010 },
        { time: 1_700_000_000, value: 23_000 },
      ])
    )
    const feed = createMultiStrikeOIFeed({ read: () => request(), onPayload: vi.fn() })

    const bars = await feed.getBars(ask)

    expect(bars.map((b) => b.close)).toEqual([23_000, 23_010])
  })

  it('still publishes the legs when the broker gives no underlying candles', async () => {
    const onPayload = vi.fn()
    mocks.getMultiStrikeOI.mockResolvedValue(oi([]))
    const feed = createMultiStrikeOIFeed({ read: () => request(), onPayload })

    // No primary bars, so studies have nothing to read and the tab says so.
    // The OI curves are overlays and still draw: the time axis is the union of
    // every series on the chart, not the primary's alone.
    await expect(feed.getBars(ask)).resolves.toEqual([])
    expect(onPayload).toHaveBeenCalledWith(
      expect.objectContaining({ underlying_available: false }),
      { paging: false }
    )
  })
})
