import type { WorkspacePane } from 'openalgo-charts/workspace'
import { describe, expect, it, vi } from 'vitest'
import { LAYOUTS } from '@/lib/chart/layouts'
import { PreparedChartGrid } from './preparedGrid'
import type { TradingTerminal } from './terminal'
import { capturePresetWorkspace } from './workspaceGrid'

const pane = (id: string, interval: string): WorkspacePane => ({
  id,
  symbol: 'BHEL',
  exchange: 'NSE',
  interval,
  chartType: 'candlestick',
  chart: { version: 1 },
  settings: {},
  volume: true,
  magnet: 'off',
  stay: false,
  comparisons: [],
  comparisonMode: 'price',
})
const sync = { crosshair: true, viewport: true, symbol: false, interval: false }
const payload = () =>
  capturePresetWorkspace(LAYOUTS[1], [pane('left', '5m'), pane('right', '1h')], 'right', sync)
function terminal(id: string) {
  return {
    destroy: vi.fn(),
    setArmed: vi.fn(),
    setWorkspaceTransitionLocked: vi.fn(),
    captureWorkspacePane: vi.fn(() => pane(id, '15m')),
  } as unknown as TradingTerminal
}

describe('prepared chart grid ownership', () => {
  it('releases every terminal and link even when one terminal cleanup throws', () => {
    const grid = new PreparedChartGrid(payload())
    const left = terminal('left'),
      right = terminal('right')
    grid.register('left', left)
    grid.register('right', right)
    const releaseLinks = vi.spyOn(grid.linkGroup, 'destroy')
    vi.mocked(left.setWorkspaceTransitionLocked).mockImplementation(() => {
      throw new Error('Chart callback failed')
    })
    vi.mocked(left.destroy).mockImplementation(() => {
      throw new Error('Feed cleanup failed')
    })
    expect(() => grid.destroy()).toThrow()
    expect(left.setArmed).toHaveBeenLastCalledWith(false)
    expect(left.destroy).toHaveBeenCalledOnce()
    expect(right.destroy).toHaveBeenCalledOnce()
    expect(releaseLinks).toHaveBeenCalledOnce()
    expect(grid.terminals.size).toBe(0)
    expect(grid.disposed).toBe(true)
    expect(() => grid.destroy()).not.toThrow()
  })

  it('waits for every registered owner, keeps link channels disabled, then captures current charts', async () => {
    const grid = new PreparedChartGrid(payload())
    const left = terminal('left'),
      right = terminal('right')
    const ready = vi.fn()
    void grid.ready.then(ready)
    expect(grid.linkGroup.options()).toMatchObject({
      crosshair: false,
      viewport: false,
      symbol: false,
      interval: false,
    })
    grid.register('left', left)
    grid.register('right', right)
    grid.initialized('right', right)
    await Promise.resolve()
    expect(ready).not.toHaveBeenCalled()
    expect(() => grid.capture('right', sync)).toThrow(/ready/i)
    grid.initialized('left', left)
    await grid.ready
    grid.activate(sync)
    expect(grid.linkGroup.options().interval).toBe(false)
    expect(grid.capture('left', sync)).toMatchObject({
      activePaneId: 'left',
      panes: [{ interval: '15m' }, { interval: '15m' }],
    })
    grid.destroy()
  })

  it('ignores replaced pane readiness and disarms every terminal before publication', async () => {
    const grid = new PreparedChartGrid(payload())
    const old = terminal('left'),
      left = terminal('left'),
      right = terminal('right')
    grid.register('left', old)
    grid.register('left', null)
    grid.register('left', left)
    grid.register('right', right)
    grid.initialized('left', old)
    grid.initialized('right', right)
    expect(() => grid.activate(sync)).toThrow(/ready/i)
    grid.initialized('left', left)
    await grid.ready
    grid.setLocked(true)
    for (const owner of [left, right]) {
      expect(owner.setWorkspaceTransitionLocked).toHaveBeenLastCalledWith(true)
      expect(owner.setArmed).toHaveBeenLastCalledWith(false)
    }
    grid.destroy()
  })

  it('rejects failed preparation, releases all owners once, and refuses late callbacks', async () => {
    const grid = new PreparedChartGrid(payload())
    const left = terminal('left'),
      right = terminal('right')
    grid.register('left', left)
    grid.register('right', right)
    const failure = new Error('History unavailable')
    const rejected = expect(grid.ready).rejects.toBe(failure)
    grid.fail(failure)
    await rejected
    grid.destroy()
    grid.destroy()
    grid.initialized('left', left)
    grid.register('right', right)
    expect(left.destroy).toHaveBeenCalledOnce()
    expect(right.destroy).toHaveBeenCalledOnce()
    expect(grid.terminals.size).toBe(0)
    expect(() => grid.capture('left', sync)).toThrow(/closed/i)
  })
})
