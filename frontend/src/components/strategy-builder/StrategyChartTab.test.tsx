import { act, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { StrategyChartResponse } from '@/api/strategy-chart'
import type { StrategyLeg } from '@/lib/strategyMath'
import StrategyChartTab from './StrategyChartTab'

const mocks = vi.hoisted(() => ({
  getIntervals: vi.fn(),
  getStrategyChart: vi.fn(),
  toastError: vi.fn(),
}))

vi.mock('@/api/strategy-chart', () => ({
  strategyChartApi: {
    getIntervals: mocks.getIntervals,
    getStrategyChart: mocks.getStrategyChart,
  },
}))

vi.mock('@/utils/toast', () => ({ showToast: { error: mocks.toastError } }))

vi.mock('lightweight-charts', () => {
  const series = { setData: vi.fn(), applyOptions: vi.fn() }
  const chart = {
    addSeries: vi.fn(() => series),
    applyOptions: vi.fn(),
    remove: vi.fn(),
    removeSeries: vi.fn(),
    subscribeCrosshairMove: vi.fn(),
    timeScale: vi.fn(() => ({ fitContent: vi.fn() })),
  }
  return {
    ColorType: { Solid: 'Solid' },
    CrosshairMode: { Normal: 0 },
    LineSeries: {},
    createChart: vi.fn(() => chart),
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

describe('StrategyChartTab request sequencing', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.clearAllMocks()
    mocks.getIntervals.mockResolvedValue({
      status: 'success',
      data: { seconds: [], minutes: ['5m'], hours: [] },
    })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('keeps request B displayed when request A resolves later', async () => {
    const requestA = deferred<StrategyChartResponse>()
    const requestB = deferred<StrategyChartResponse>()
    mocks.getStrategyChart.mockReturnValueOnce(requestA.promise).mockReturnValueOnce(requestB.promise)

    const view = render(renderTab('BTC'))
    await act(async () => vi.advanceTimersByTimeAsync(300))
    expect(mocks.getStrategyChart).toHaveBeenCalledTimes(1)

    view.rerender(renderTab('ETH'))
    await act(async () => vi.advanceTimersByTimeAsync(300))
    expect(mocks.getStrategyChart).toHaveBeenCalledTimes(2)

    await act(async () => requestB.resolve(response('ETH', 222)))
    expect(screen.getByText('222.00')).toBeInTheDocument()

    await act(async () => requestA.resolve(response('BTC', 111)))
    expect(screen.getByText('222.00')).toBeInTheDocument()
    expect(screen.queryByText('111.00')).not.toBeInTheDocument()
  })

  it('ignores an obsolete error and sends the backend-resolved reference', async () => {
    const requestA = deferred<StrategyChartResponse>()
    const requestB = deferred<StrategyChartResponse>()
    mocks.getStrategyChart.mockReturnValueOnce(requestA.promise).mockReturnValueOnce(requestB.promise)

    const view = render(renderTab('BTC'))
    await act(async () => vi.advanceTimersByTimeAsync(300))
    view.rerender(renderTab('ETH'))
    await act(async () => vi.advanceTimersByTimeAsync(300))

    expect(mocks.getStrategyChart).toHaveBeenLastCalledWith(
      expect.objectContaining({
        underlying: 'ETH',
        underlying_symbol: 'ETHUSDFUT',
        underlying_exchange: 'CRYPTO',
      })
    )

    await act(async () => requestB.resolve(response('ETH', 222)))
    await act(async () => requestA.resolve({ status: 'error', message: 'obsolete A' }))

    expect(screen.getByText('222.00')).toBeInTheDocument()
    expect(mocks.toastError).not.toHaveBeenCalledWith('obsolete A')
  })
})
