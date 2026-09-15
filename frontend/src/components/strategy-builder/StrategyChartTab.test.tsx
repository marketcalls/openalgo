import { act, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { StrategyChartResponse } from '@/api/strategy-chart'
import type { StrategyLeg } from '@/lib/strategyMath'
import { fakeWidgetState, moveCrosshair } from '@/test/fakeChart'
import StrategyChartTab from './StrategyChartTab'

const mocks = vi.hoisted(() => ({
  getIntervals: vi.fn(),
  getStrategyChart: vi.fn(),
  toastError: vi.fn(),
  chartState: { current: null as ReturnType<typeof fakeWidgetState> | null },
}))

vi.mock('@/api/strategy-chart', () => ({
  strategyChartApi: {
    getIntervals: mocks.getIntervals,
    getStrategyChart: mocks.getStrategyChart,
  },
}))

vi.mock('@/utils/toast', () => ({ showToast: { error: mocks.toastError } }))

// The chart is what calls the feed, so it is faked rather than stubbed out: a
// tab tested against a chart that never fetches would pass with its feed wired
// to nothing.
vi.mock('@/components/chart/OpenAlgoChart', async () => {
  const { fakeOpenAlgoChart: build } = await import('@/test/fakeChart')
  return {
    OpenAlgoChart: (props: Record<string, unknown>) => {
      const Component = build(mocks.chartState.current!)
      return Component(props as never)
    },
  }
})

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

const LEG: StrategyLeg = {
  id: 'leg',
  segment: 'OPTION',
  side: 'BUY',
  lots: 1,
  lotSize: 25,
  expiry: '27AUG26',
  strike: 100,
  optionType: 'CE',
  price: 10,
  iv: 20,
  active: true,
  symbol: 'TEST27AUG26100CE',
}

function response(underlying: string, ltp: number): StrategyChartResponse {
  return {
    status: 'success',
    data: {
      underlying,
      underlying_ltp: ltp,
      interval: '5m',
      tag: 'debit',
      entry_net_premium: -10,
      entry_abs_premium: 10,
      legs_used: 1,
      underlying_available: true,
      series: [{ time: 1_700_000_000, underlying: ltp, net_premium: -10, combined_premium: 10 }],
    },
  }
}

function renderTab(underlying: string) {
  return (
    <StrategyChartTab
      underlying={underlying}
      exchange="CRYPTO"
      underlyingSymbol={`${underlying}USDFUT`}
      underlyingExchange="CRYPTO"
      legs={[LEG]}
      optionExchange="CRYPTO"
    />
  )
}

beforeEach(() => {
  vi.useFakeTimers()
  vi.clearAllMocks()
  mocks.chartState.current = fakeWidgetState()
  mocks.getIntervals.mockResolvedValue({
    status: 'success',
    data: { seconds: [], minutes: ['5m'], hours: [] },
  })
})

afterEach(() => {
  vi.useRealTimers()
})

describe('StrategyChartTab request sequencing', () => {
  it('keeps request B displayed when request A resolves later', async () => {
    const requestA = deferred<StrategyChartResponse>()
    const requestB = deferred<StrategyChartResponse>()
    mocks.getStrategyChart
      .mockReturnValueOnce(requestA.promise)
      .mockReturnValueOnce(requestB.promise)

    const view = render(renderTab('BTC'))
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })
    expect(mocks.getStrategyChart).toHaveBeenCalledTimes(1)

    view.rerender(renderTab('ETH'))
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })
    expect(mocks.getStrategyChart).toHaveBeenCalledTimes(2)

    await act(async () => {
      requestB.resolve(response('ETH', 222))
      await requestB.promise
    })
    expect(screen.getByText('222.00')).toBeInTheDocument()

    await act(async () => {
      requestA.resolve(response('BTC', 111))
      await requestA.promise
    })
    expect(screen.getByText('222.00')).toBeInTheDocument()
    expect(screen.queryByText('111.00')).not.toBeInTheDocument()
  })

  it('sends the backend-resolved underlying reference', async () => {
    mocks.getStrategyChart.mockResolvedValue(response('ETH', 222))

    const view = render(renderTab('BTC'))
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })
    view.rerender(renderTab('ETH'))
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })

    expect(mocks.getStrategyChart).toHaveBeenLastCalledWith(
      expect.objectContaining({
        underlying: 'ETH',
        underlying_symbol: 'ETHUSDFUT',
        underlying_exchange: 'CRYPTO',
        interval: '5m',
      })
    )
  })

  it('fetches once on a first view, not twice', async () => {
    mocks.getStrategyChart.mockResolvedValue(response('BTC', 111))

    render(renderTab('BTC'))
    // Past the debounce that covers leg edits: the chart loads once as it is
    // built, and the host must not reload for the same request on top of it.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(600)
    })

    expect(mocks.getStrategyChart).toHaveBeenCalledTimes(1)
  })
})

describe('StrategyChartTab chart wiring', () => {
  it('draws the premium through the feed and the underlying as an overlay', async () => {
    mocks.getStrategyChart.mockResolvedValue(response('BTC', 111))
    render(renderTab('BTC'))
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })

    // The premium is not an overlay: it reaches the chart as the feed's bars,
    // which is what makes an indicator added from the picker a study of the
    // spread. The only series the host creates is the underlying.
    const overlays = mocks.chartState.current!.series
    expect(overlays).toHaveLength(1)
    expect(overlays[0].options).toMatchObject({ type: 'line', priceScaleId: 'left' })
    expect(overlays[0].data).toEqual([{ time: 1_700_000_000, value: 111 }])
  })

  it('gives the tab its own saved workspace and no built-in top bar', async () => {
    mocks.getStrategyChart.mockResolvedValue(response('BTC', 111))
    render(renderTab('BTC'))
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })

    const host = screen.getByTestId('openalgo-chart')
    // Its own namespace, or the two tabs would share one set of indicators.
    expect(host.dataset.persistKey).toBe('strategybuilder:strategy-chart')
    // The host draws the timeframe and day controls, so the engine's own bar
    // would be a second copy of them.
    expect(host.dataset.topbar).toBe('false')
    expect(host.dataset.chartType).toBe('line')
  })

  it('reports a failed load where the reader can see it', async () => {
    mocks.getStrategyChart.mockResolvedValue({
      status: 'error',
      message: 'No history in this window',
    })
    render(renderTab('BTC'))
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })

    expect(screen.getByText('No history in this window')).toBeInTheDocument()
  })

  it('says so when the broker has no candles for the underlying', async () => {
    const res = response('BTC', 111)
    res.data!.underlying_available = false
    mocks.getStrategyChart.mockResolvedValue(res)
    render(renderTab('BTC'))
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })

    expect(screen.getByText(/does not return 5m candles/)).toBeInTheDocument()
  })

  it('reads out both series at the bar under the crosshair', async () => {
    mocks.getStrategyChart.mockResolvedValue(response('BTC', 111))
    render(renderTab('BTC'))
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })

    await act(async () => {
      moveCrosshair(mocks.chartState.current!, 1_700_000_000)
    })

    const tip = screen.getByTestId('chart-tooltip')
    expect(tip).toHaveTextContent('BTC')
    expect(tip).toHaveTextContent('111.00')
    expect(tip).toHaveTextContent('Strategy (Debit)')
    expect(tip).toHaveTextContent('10.00')

    // Off the data the box goes away rather than freezing on the last bar it
    // saw, which would read as a live value while the cursor is elsewhere.
    await act(async () => {
      moveCrosshair(mocks.chartState.current!, null)
    })
    expect(screen.queryByTestId('chart-tooltip')).not.toBeInTheDocument()
  })

  it('shows no readout over a bar the series has no point for', async () => {
    mocks.getStrategyChart.mockResolvedValue(response('BTC', 111))
    render(renderTab('BTC'))
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })

    await act(async () => {
      moveCrosshair(mocks.chartState.current!, 1_699_000_000)
    })

    // An empty frame over a gap invites the reader to believe a number is
    // missing rather than that the strategy had no price then.
    expect(screen.queryByTestId('chart-tooltip')).not.toBeInTheDocument()
  })

  it('leaves the legend as a plain on/off switch', async () => {
    mocks.getStrategyChart.mockResolvedValue(response('BTC', 111))
    render(renderTab('BTC'))
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })

    const strategy = screen.getByRole('button', { name: /^Strategy$/ })
    expect(strategy).toHaveAttribute('aria-pressed', 'true')
    await act(async () => {
      strategy.click()
    })
    expect(screen.getByRole('button', { name: /^Strategy$/ })).toHaveAttribute(
      'aria-pressed',
      'false'
    )
    expect(mocks.chartState.current!.primaryStyle.visible).toBe(false)
  })

  it('keeps the underlying overlay when older history pages in', async () => {
    const recent = response('BTC', 111)
    mocks.getStrategyChart.mockResolvedValueOnce(recent)
    render(renderTab('BTC'))
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })
    expect(mocks.chartState.current!.series[0].data).toHaveLength(1)

    // What the engine sends once the reader scrolls past the left edge: an
    // older window, carrying only the bars before what is already held.
    const older = response('BTC', 111)
    older.data!.series = [
      { time: 1_699_000_000, underlying: 105, net_premium: -9, combined_premium: 9 },
    ]
    mocks.getStrategyChart.mockResolvedValueOnce(older)
    await act(async () => {
      await mocks.chartState.current!.pageOlder()
    })

    // The chart prepends the older bars to its own series. The overlay has to
    // grow the same way: replacing it would leave the underlying drawn only
    // over the older window while the premium spans both.
    expect(mocks.chartState.current!.series[0].data).toEqual([
      { time: 1_699_000_000, value: 105 },
      { time: 1_700_000_000, value: 111 },
    ])
  })

  it('keeps what is on screen when paging older history fails', async () => {
    mocks.getStrategyChart.mockResolvedValueOnce(response('BTC', 111))
    render(renderTab('BTC'))
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })

    mocks.getStrategyChart.mockResolvedValueOnce({ status: 'error', message: 'broker said no' })
    await act(async () => {
      await mocks.chartState.current!.pageOlder()
    })

    // A page that could not be fetched is no news about the range already
    // drawn. Clearing here would blank the overlay and the readout under a
    // chart that still holds every bar it had.
    expect(mocks.chartState.current!.series[0].data).toHaveLength(1)
    expect(screen.getByText('111.00')).toBeInTheDocument()
  })

  it('asks for nothing until there is an active option leg', async () => {
    render(
      <StrategyChartTab
        underlying="BTC"
        exchange="CRYPTO"
        legs={[{ ...LEG, active: false }]}
        optionExchange="CRYPTO"
      />
    )
    await act(async () => {
      await vi.advanceTimersByTimeAsync(600)
    })

    expect(screen.getByText(/Add at least one active option leg/)).toBeInTheDocument()
    expect(mocks.getStrategyChart).not.toHaveBeenCalled()
  })
})
