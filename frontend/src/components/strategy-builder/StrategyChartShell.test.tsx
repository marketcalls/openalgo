import { act, render, screen } from '@testing-library/react'
import type { Bar } from 'openalgo-charts'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fakeWidgetState, moveCrosshair } from '@/test/fakeChart'
import { StrategyChartShell } from './StrategyChartShell'

const mocks = vi.hoisted(() => ({
  chartState: { current: null as ReturnType<typeof fakeWidgetState> | null },
  toastError: vi.fn(),
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

const BAR: Bar = { time: 1_700_000_000, open: 1, high: 1, low: 1, close: 1 }

function renderShell(overrides: Record<string, unknown> = {}) {
  const props = {
    feed: { getBars: async (): Promise<Bar[]> => [BAR] },
    symbol: 'NIFTY PREMIUM',
    exchange: 'NFO',
    interval: '5m',
    intervals: ['5m', '15m'],
    onIntervalChange: vi.fn(),
    days: '3',
    onDaysChange: vi.fn(),
    reloadKey: 'a',
    busy: false,
    onBusyChange: vi.fn(),
    persistKey: 'test:shell',
    onReady: vi.fn(),
    ...overrides,
  }
  const view = render(<StrategyChartShell {...(props as never)} />)
  return { view, props }
}

beforeEach(() => {
  vi.useFakeTimers()
  vi.clearAllMocks()
  mocks.chartState.current = fakeWidgetState()
})

afterEach(() => {
  vi.useRealTimers()
})

describe('StrategyChartShell loading state', () => {
  it('never raises busy for the load the chart runs on its own', async () => {
    const { props } = renderShell()
    await act(async () => {
      await vi.advanceTimersByTimeAsync(600)
    })

    // The chart's first load starts inside its own construction and can finish
    // before this component has mounted its effects. A flag raised here would
    // then never be lowered, because the event that lowers it has already been
    // and gone, and the button would read Loading over a finished chart for as
    // long as the tab stayed open.
    expect(props.onBusyChange).not.toHaveBeenCalledWith(true)
  })

  it('raises and lowers busy around a reload it asked for', async () => {
    const { view, props } = renderShell()
    await act(async () => {
      await vi.advanceTimersByTimeAsync(600)
    })
    ;(props.onBusyChange as ReturnType<typeof vi.fn>).mockClear()

    view.rerender(<StrategyChartShell {...(props as never)} reloadKey="b" />)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(300)
    })

    // Both edges in one place, which is the only way the flag stays honest.
    expect(props.onBusyChange).toHaveBeenCalledWith(true)
    expect(props.onBusyChange).toHaveBeenLastCalledWith(false)
  })

  it('debounces a burst of request changes into one reload', async () => {
    const getBars = vi.fn(async (): Promise<Bar[]> => [BAR])
    const { view, props } = renderShell({ feed: { getBars } })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(600)
    })
    expect(getBars).toHaveBeenCalledTimes(1)

    // A template pick rewrites the legs several times in a few milliseconds.
    for (const key of ['b', 'c', 'd']) {
      view.rerender(<StrategyChartShell {...(props as never)} reloadKey={key} />)
      await act(async () => {
        await vi.advanceTimersByTimeAsync(50)
      })
    }
    await act(async () => {
      await vi.advanceTimersByTimeAsync(600)
    })

    expect(getBars).toHaveBeenCalledTimes(2)
  })
})

describe('StrategyChartShell crosshair readout', () => {
  it('hides the box when the tab has nothing to say about that bar', async () => {
    renderShell({ tooltip: () => null })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
      moveCrosshair(mocks.chartState.current!, 1_700_000_000)
    })

    expect(screen.queryByTestId('chart-tooltip')).not.toBeInTheDocument()
  })

  it('stays out of the way of the pointer', async () => {
    renderShell({
      tooltip: () => [{ label: 'Strategy', value: '56.75', color: '#a78bfa' }],
    })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
      moveCrosshair(mocks.chartState.current!, 1_700_000_000)
    })

    // The engine takes pointer capture on its canvas to pan. A box under the
    // cursor that accepted events would swallow the drag every time the
    // crosshair passed beneath it.
    expect(screen.getByTestId('chart-tooltip').className).toContain('pointer-events-none')
  })
})

describe('StrategyChartShell controls', () => {
  it('offers no replay, because neither chart is price history', async () => {
    renderShell()
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })

    expect(screen.queryByRole('button', { name: /replay/i })).not.toBeInTheDocument()
  })
})
