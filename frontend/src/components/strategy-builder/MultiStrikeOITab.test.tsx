import { act, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { MultiStrikeOILeg, MultiStrikeOIResponse } from '@/api/strategy-chart'
import type { StrategyLeg } from '@/lib/strategyMath'
import { fakeWidgetState, moveCrosshair } from '@/test/fakeChart'
import MultiStrikeOITab, { formatOI } from './MultiStrikeOITab'

const mocks = vi.hoisted(() => ({
  getIntervals: vi.fn(),
  getMultiStrikeOI: vi.fn(),
  toastError: vi.fn(),
  chartState: { current: null as ReturnType<typeof fakeWidgetState> | null },
}))

vi.mock('@/api/strategy-chart', () => ({
  strategyChartApi: {
    getIntervals: mocks.getIntervals,
    getMultiStrikeOI: mocks.getMultiStrikeOI,
  },
}))

vi.mock('@/utils/toast', () => ({ showToast: { error: mocks.toastError } }))

vi.mock('@/components/chart/OpenAlgoChart', async () => {
  const { fakeOpenAlgoChart: build } = await import('@/test/fakeChart')
  return {
    OpenAlgoChart: (props: Record<string, unknown>) => {
      const Component = build(mocks.chartState.current!)
      return Component(props as never)
    },
  }
})

function leg(overrides: Partial<StrategyLeg> = {}): StrategyLeg {
  return {
    id: 'leg',
    segment: 'OPTION',
    side: 'BUY',
    lots: 1,
    lotSize: 25,
    expiry: '27AUG26',
    strike: 23_100,
    optionType: 'CE',
    price: 10,
    iv: 20,
    active: true,
    symbol: 'NIFTY27AUG2623100CE',
    ...overrides,
  }
}

function oiLeg(overrides: Partial<MultiStrikeOILeg> = {}): MultiStrikeOILeg {
  return {
    symbol: 'NIFTY27AUG2623100CE',
    exchange: 'NFO',
    side: 'BUY',
    strike: 23_100,
    option_type: 'CE',
    expiry: '27AUG26',
    has_oi: true,
    series: [{ time: 1_700_000_000, value: 4_500_000 }],
    ...overrides,
  }
}

function response(legs: MultiStrikeOILeg[], underlyingAvailable = true): MultiStrikeOIResponse {
  return {
    status: 'success',
    data: {
      underlying: 'NIFTY',
      underlying_ltp: 23_000,
      interval: '5m',
      underlying_available: underlyingAvailable,
      underlying_series: underlyingAvailable ? [{ time: 1_700_000_000, value: 23_000 }] : [],
      legs,
    },
  }
}

function renderTab(legs: StrategyLeg[]) {
  return (
    <MultiStrikeOITab
      underlying="NIFTY"
      exchange="NSE_INDEX"
      underlyingSymbol="NIFTY"
      underlyingExchange="NSE_INDEX"
      legs={legs}
      optionExchange="NFO"
    />
  )
}

const settle = () =>
  act(async () => {
    await vi.advanceTimersByTimeAsync(0)
  })

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

describe('formatOI', () => {
  it('reads open interest in the units it is quoted in', () => {
    // Eight-digit contract counts make an unreadable axis.
    expect(formatOI(45_000_000)).toBe('4.50Cr')
    expect(formatOI(4_500_000)).toBe('45.00L')
    expect(formatOI(4_500)).toBe('4.5K')
    expect(formatOI(450)).toBe('450')
    expect(formatOI(Number.NaN)).toBe('-')
  })
})

describe('MultiStrikeOITab chart wiring', () => {
  it('puts each leg on its own curve, off the axis the underlying uses', async () => {
    mocks.getMultiStrikeOI.mockResolvedValue(
      response([
        oiLeg(),
        oiLeg({
          symbol: 'NIFTY27AUG2623200CE',
          strike: 23_200,
          series: [{ time: 1_700_000_000, value: 3_200_000 }],
        }),
      ])
    )
    render(renderTab([leg(), leg({ id: 'b', symbol: 'NIFTY27AUG2623200CE', strike: 23_200 })]))
    await settle()

    const series = mocks.chartState.current!.series
    expect(series).toHaveLength(2)
    for (const line of series) {
      // The left axis, because the right one carries the underlying: one scale
      // for a five-figure index and an eight-figure contract count draws the
      // index as a flat line along the bottom.
      expect(line.options).toMatchObject({ type: 'line', priceScaleId: 'left' })
      // Contract counts, not rupees, so the axis carries its own formatter.
      expect(line.options.priceFormat).toMatchObject({ type: 'custom' })
    }
    expect(series[0].data).toEqual([{ time: 1_700_000_000, value: 4_500_000 }])
    expect(series[1].data).toEqual([{ time: 1_700_000_000, value: 3_200_000 }])
  })

  it('keeps two legs on the same contract apart', async () => {
    // A long and a short of one strike are two legs of the strategy and two
    // entries in the legend. Keyed by symbol they collapsed into one curve,
    // which left one of the two toggles moving nothing.
    mocks.getMultiStrikeOI.mockResolvedValue(
      response([oiLeg({ side: 'BUY' }), oiLeg({ side: 'SELL' })])
    )
    render(renderTab([leg(), leg({ id: 'b', side: 'SELL' })]))
    await settle()

    expect(mocks.chartState.current!.series).toHaveLength(2)
  })

  it('drops the curve for a leg that was removed', async () => {
    mocks.getMultiStrikeOI.mockResolvedValueOnce(
      response([oiLeg(), oiLeg({ symbol: 'NIFTY27AUG2623200CE', strike: 23_200 })])
    )
    const view = render(
      renderTab([leg(), leg({ id: 'b', symbol: 'NIFTY27AUG2623200CE', strike: 23_200 })])
    )
    await settle()
    expect(mocks.chartState.current!.series.filter((s) => !s.removed)).toHaveLength(2)

    mocks.getMultiStrikeOI.mockResolvedValueOnce(response([oiLeg()]))
    view.rerender(renderTab([leg()]))
    await act(async () => {
      await vi.advanceTimersByTimeAsync(600)
    })

    expect(mocks.chartState.current!.series.filter((s) => !s.removed)).toHaveLength(1)
  })

  it('reuses a curve across a refresh that returns the same legs', async () => {
    mocks.getMultiStrikeOI.mockResolvedValue(response([oiLeg()]))
    render(renderTab([leg()]))
    await settle()
    expect(mocks.chartState.current!.series).toHaveLength(1)

    mocks.getMultiStrikeOI.mockResolvedValue(
      response([oiLeg({ series: [{ time: 1_700_000_300, value: 4_600_000 }] })])
    )
    await act(async () => {
      screen.getByRole('button', { name: /refresh/i }).click()
      await vi.advanceTimersByTimeAsync(0)
    })

    // One series, re-pointed. Recreating it on every poll would flicker.
    expect(mocks.chartState.current!.series).toHaveLength(1)
    expect(mocks.chartState.current!.series[0].data).toEqual([
      { time: 1_700_000_300, value: 4_600_000 },
    ])
  })

  it('gives the tab its own workspace, separate from the strategy chart', async () => {
    mocks.getMultiStrikeOI.mockResolvedValue(response([oiLeg()]))
    render(renderTab([leg()]))
    await settle()

    expect(screen.getByTestId('openalgo-chart').dataset.persistKey).toBe(
      'strategybuilder:multi-strike-oi'
    )
  })

  it('says how many legs came back without open interest', async () => {
    mocks.getMultiStrikeOI.mockResolvedValue(
      response([oiLeg({ has_oi: false, series: [] }), oiLeg({ side: 'SELL' })])
    )
    render(renderTab([leg(), leg({ id: 'b', side: 'SELL' })]))
    await settle()

    expect(screen.getByText(/1 leg returned no OI history/)).toBeInTheDocument()
  })

  it('draws the OI curves even when the broker has no underlying candles', async () => {
    mocks.getMultiStrikeOI.mockResolvedValue(response([oiLeg()], false))
    render(renderTab([leg()]))
    await settle()

    // The primary series is empty, so studies have nothing to read and the tab
    // says so. The overlays still draw: the time axis is the union of every
    // series on the chart, not the primary's alone.
    expect(mocks.chartState.current!.series).toHaveLength(1)
    expect(mocks.chartState.current!.series[0].data).toHaveLength(1)
    expect(screen.getByText(/does not return 5m candles/)).toBeInTheDocument()
  })

  it('reports a failed load where the reader can see it', async () => {
    mocks.getMultiStrikeOI.mockResolvedValue({
      status: 'error',
      message: 'Broker returned no open interest',
    })
    render(renderTab([leg()]))
    await settle()

    expect(screen.getByText('Broker returned no open interest')).toBeInTheDocument()
  })

  it('reads out the underlying and every visible leg at the crosshair', async () => {
    mocks.getMultiStrikeOI.mockResolvedValue(
      response([
        oiLeg(),
        oiLeg({
          symbol: 'NIFTY27AUG2623200CE',
          strike: 23_200,
          series: [{ time: 1_700_000_000, value: 3_200_000 }],
        }),
      ])
    )
    render(renderTab([leg(), leg({ id: 'b', symbol: 'NIFTY27AUG2623200CE', strike: 23_200 })]))
    await settle()

    await act(async () => {
      moveCrosshair(mocks.chartState.current!, 1_700_000_000)
    })

    const tip = screen.getByTestId('chart-tooltip')
    expect(tip).toHaveTextContent('NIFTY 27 AUG 23100 CALL')
    expect(tip).toHaveTextContent('45.00L')
    expect(tip).toHaveTextContent('32.00L')
    expect(tip).toHaveTextContent('23,000.00')
  })

  it('leaves a hidden leg out of the readout', async () => {
    mocks.getMultiStrikeOI.mockResolvedValue(response([oiLeg()]))
    render(renderTab([leg()]))
    await settle()

    await act(async () => {
      screen.getByRole('button', { name: /23100 CALL/ }).click()
    })
    await act(async () => {
      moveCrosshair(mocks.chartState.current!, 1_700_000_000)
    })

    // The box says what the chart is drawing, so a hidden curve is absent
    // rather than greyed.
    const tip = screen.getByTestId('chart-tooltip')
    expect(tip).not.toHaveTextContent('45.00L')
    expect(tip).toHaveTextContent('23,000.00')
  })

  it('asks for nothing until there is an active option leg', async () => {
    render(renderTab([leg({ active: false })]))
    await act(async () => {
      await vi.advanceTimersByTimeAsync(600)
    })

    expect(screen.getByText(/Add at least one active option leg/)).toBeInTheDocument()
    expect(mocks.getMultiStrikeOI).not.toHaveBeenCalled()
  })
})
