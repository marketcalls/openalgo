import { act, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { MultiStrikeOIResponse } from '@/api/strategy-chart'
import type { StrategyLeg } from '@/lib/strategyMath'
import MultiStrikeOITab from './MultiStrikeOITab'

const mocks = vi.hoisted(() => ({
  getIntervals: vi.fn(),
  getMultiStrikeOI: vi.fn(),
  toastError: vi.fn(),
}))

vi.mock('@/api/strategy-chart', () => ({
  strategyChartApi: {
    getIntervals: mocks.getIntervals,
    getMultiStrikeOI: mocks.getMultiStrikeOI,
  },
}))

vi.mock('@/utils/toast', () => ({ showToast: { error: mocks.toastError } }))

vi.mock('lightweight-charts', () => {
  const makeSeries = () => ({ setData: vi.fn(), applyOptions: vi.fn() })
  const chart = {
    addSeries: vi.fn(makeSeries),
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

function response(underlying: string, ltp: number): MultiStrikeOIResponse {
  return {
    status: 'success',
    data: {
      underlying,
      underlying_ltp: ltp,
      interval: '5m',
      underlying_available: true,
      underlying_series: [{ time: 1_700_000_000, value: ltp }],
      legs: [
        {
          symbol: LEG.symbol,
          exchange: 'CRYPTO',
          side: 'BUY',
          strike: 100,
          option_type: 'CE',
          expiry: '27AUG26',
          has_oi: true,
          series: [{ time: 1_700_000_000, value: 1_000 }],
        },
      ],
    },
  }
}

function renderTab(underlying: string) {
  return (
    <MultiStrikeOITab
      underlying={underlying}
      exchange="CRYPTO"
      underlyingSymbol={`${underlying}USDFUT`}
      underlyingExchange="CRYPTO"
      legs={[LEG]}
      optionExchange="CRYPTO"
    />
  )
}

describe('MultiStrikeOITab request sequencing', () => {
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
    const requestA = deferred<MultiStrikeOIResponse>()
    const requestB = deferred<MultiStrikeOIResponse>()
    mocks.getMultiStrikeOI.mockReturnValueOnce(requestA.promise).mockReturnValueOnce(requestB.promise)

    const view = render(renderTab('BTC'))
    await act(async () => vi.advanceTimersByTimeAsync(300))
    expect(mocks.getMultiStrikeOI).toHaveBeenCalledTimes(1)

    view.rerender(renderTab('ETH'))
    await act(async () => vi.advanceTimersByTimeAsync(300))
    expect(mocks.getMultiStrikeOI).toHaveBeenCalledTimes(2)

    await act(async () => requestB.resolve(response('ETH', 222)))
    expect(screen.getByText('222.00')).toBeInTheDocument()

    await act(async () => requestA.resolve(response('BTC', 111)))
    expect(screen.getByText('222.00')).toBeInTheDocument()
    expect(screen.queryByText('111.00')).not.toBeInTheDocument()
  })

  it('sends the backend-resolved reference with the OI request', async () => {
    mocks.getMultiStrikeOI.mockResolvedValue(response('BTC', 111))
    render(renderTab('BTC'))

    await act(async () => vi.advanceTimersByTimeAsync(300))

    expect(mocks.getMultiStrikeOI).toHaveBeenCalledWith(
      expect.objectContaining({
        underlying: 'BTC',
        underlying_symbol: 'BTCUSDFUT',
        underlying_exchange: 'CRYPTO',
      })
    )
  })
})
