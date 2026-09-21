import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { LAYOUTS } from '@/lib/chart/layouts'
import type { PreparedChartGrid } from '@/lib/trading/preparedGrid'
import type { TradingTerminal } from '@/lib/trading/terminal'
import { capturePresetWorkspace } from '@/lib/trading/workspaceGrid'
import { useWorkspaceGridTransition } from './useWorkspaceGridTransition'

const payload = () =>
  capturePresetWorkspace(
    LAYOUTS[0],
    [
      {
        id: 'saved',
        symbol: 'BHEL',
        exchange: 'NSE',
        interval: '5m',
        chartType: 'candlestick',
        chart: { version: 1 },
        settings: {},
        volume: true,
        magnet: 'off',
        stay: false,
        comparisons: [],
        comparisonMode: 'price',
      },
    ],
    'saved',
    { crosshair: true, viewport: true, symbol: false, interval: false }
  )
const ready = (grid: PreparedChartGrid) => {
  const terminal = {
    destroy: vi.fn(),
    setWorkspaceTransitionLocked: vi.fn(),
    setArmed: vi.fn(),
  } as unknown as TradingTerminal
  grid.register('saved', terminal)
  grid.initialized('saved', terminal)
  return terminal
}
afterEach(cleanup)

describe('workspace grid transition hook', () => {
  it('restores runtime state after persistence and before publication unlocks the chart', async () => {
    const order: string[] = []
    const { result } = renderHook(() =>
      useWorkspaceGridTransition('one', () => order.push('publish'), vi.fn())
    )
    let operation!: Promise<PreparedChartGrid>
    let terminal!: TradingTerminal
    const restore = vi.fn(() => {
      expect(terminal.setWorkspaceTransitionLocked).toHaveBeenLastCalledWith(true)
      order.push('runtime')
    })
    act(() => {
      operation = result.current.open(
        payload(),
        async () => {
          order.push('persist')
        },
        restore
      )
    })
    await act(async () => {
      terminal = ready(result.current.grids[0])
      await operation
    })
    expect(order).toEqual(['persist', 'runtime', 'publish'])
    expect(terminal.setWorkspaceTransitionLocked).toHaveBeenLastCalledWith(false)
  })

  it('releases the previous effect lifetime lock when StrictMode starts a fresh owner', () => {
    const lock = vi.fn()
    const { result } = renderHook(() => useWorkspaceGridTransition('one', vi.fn(), lock), {
      reactStrictMode: true,
    })
    expect(result.current.pending).toBe(false)
    expect(lock).toHaveBeenLastCalledWith(false)
  })
  it('keeps the staged component identity through persistence and publication', async () => {
    let finish!: () => void
    const persist = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          finish = resolve
        })
    )
    const publish = vi.fn(),
      lock = vi.fn()
    const { result } = renderHook(() => useWorkspaceGridTransition('one', publish, lock))
    let operation!: Promise<PreparedChartGrid>
    act(() => {
      operation = result.current.open(payload(), persist)
    })
    const staged = result.current.grids[0]
    expect(result.current.current).toBeNull()
    expect(result.current.pending).toBe(true)
    await act(async () => {
      ready(staged)
    })
    expect(persist).toHaveBeenCalledOnce()
    expect(publish).not.toHaveBeenCalled()
    await act(async () => {
      finish()
      await operation
    })
    expect(result.current.current).toBe(staged)
    expect(result.current.grids).toEqual([staged])
    expect(publish).toHaveBeenCalledWith(staged)
    expect(lock).toHaveBeenLastCalledWith(false)
  })

  it('retains the active grid after a failed write and removes the failed staging grid', async () => {
    const { result } = renderHook(() => useWorkspaceGridTransition('one', vi.fn(), vi.fn()))
    let first!: Promise<PreparedChartGrid>
    act(() => {
      first = result.current.open(payload(), async () => {})
    })
    const active = result.current.grids[0]
    await act(async () => {
      ready(active)
      await first
    })
    const failure = new Error('Storage full')
    let second!: Promise<PreparedChartGrid>
    act(() => {
      second = result.current.open(payload(), async () => {
        throw failure
      })
    })
    const staged = result.current.grids[1]
    await act(async () => {
      ready(staged)
      await expect(second).rejects.toBe(failure)
    })
    expect(result.current.current).toBe(active)
    expect(result.current.grids).toEqual([active])
    expect(active.disposed).toBe(false)
    expect(staged.disposed).toBe(true)
    expect(result.current.error).toBe('Storage full')
  })

  it('cancels pending storage on account change and refuses its late publication', async () => {
    let signal!: AbortSignal, finish!: () => void
    const publish = vi.fn()
    const { result, rerender } = renderHook(
      ({ account }) => useWorkspaceGridTransition(account, publish, vi.fn()),
      { initialProps: { account: 'one' } }
    )
    let operation!: Promise<PreparedChartGrid>
    act(() => {
      operation = result.current.open(payload(), (value) => {
        signal = value
        return new Promise<void>((resolve) => {
          finish = resolve
        })
      })
    })
    const staged = result.current.grids[0]
    await act(async () => {
      ready(staged)
    })
    const rejected = expect(operation).rejects.toThrow(/cancel/i)
    rerender({ account: 'two' })
    await act(async () => {
      await rejected
    })
    expect(signal.aborted).toBe(true)
    await act(async () => finish())
    expect(result.current.grids).toEqual([])
    expect(publish).not.toHaveBeenCalled()
    expect(staged.disposed).toBe(true)
  })
})
