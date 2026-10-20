import type { WorkspacePane, WorkspacePayload } from 'openalgo-charts/workspace'
import { describe, expect, it } from 'vitest'
import { LAYOUTS } from '@/lib/chart/layouts'
import { capturePresetWorkspace, workspaceGridGeometry } from './workspaceGrid'

function pane(id: string): WorkspacePane {
  return {
    id,
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
  }
}
const sync = { crosshair: true, viewport: false, symbol: false, interval: false }
const preset = (id: string) => LAYOUTS.find((layout) => layout.id === id)!

describe('portable chart grid geometry', () => {
  it('captures unequal preset tracks, spans, selected pane and independent link channels', () => {
    const result = capturePresetWorkspace(
      preset('oneTwo'),
      [pane('p0'), pane('p1'), pane('p2')],
      'p2',
      sync
    )
    expect(result.layout).toEqual({
      preset: 'oneTwo',
      rows: 2,
      columns: 2,
      rowWeights: [1, 1],
      columnWeights: [1.4, 1],
      slots: [
        { paneId: 'p0', row: 0, column: 0, rowSpan: 2, columnSpan: 1 },
        { paneId: 'p1', row: 0, column: 1, rowSpan: 1, columnSpan: 1 },
        { paneId: 'p2', row: 1, column: 1, rowSpan: 1, columnSpan: 1 },
      ],
    })
    expect(result.activePaneId).toBe('p2')
    expect(result.sync).toEqual(sync)
  })

  it.each(LAYOUTS)('round trips all cells in the $id preset', (layout) => {
    const panes = layout.cells.map((_, i) => pane(`p${i}`))
    const payload = capturePresetWorkspace(layout, panes, 'p0', sync)
    const grid = workspaceGridGeometry(payload)
    expect(grid.panes.map((p) => p.id)).toEqual(panes.map((p) => p.id))
    expect(grid.rows).toBe(layout.rows)
    expect(grid.columns).toBe(layout.cols)
  })

  it('uses explicit imported geometry even when its preset name describes a different grid', () => {
    const payload = capturePresetWorkspace(
      preset('cols2'),
      [pane('left'), pane('right')],
      'right',
      sync
    )
    payload.layout.preset = 'single'
    payload.layout.columnWeights = [3, 2]
    expect(workspaceGridGeometry(payload)).toMatchObject({
      columns: '3fr 2fr',
      rows: '1fr',
      areas: '"cell0 cell1"',
      panes: [
        { id: 'left', area: 'cell0' },
        { id: 'right', area: 'cell1' },
      ],
    })
  })

  it('generates CSS area names rather than interpreting imported pane IDs as CSS', () => {
    const payload = capturePresetWorkspace(
      preset('cols2'),
      [pane('name; color:red'), pane('other"{}')],
      'other"{}',
      sync
    )
    expect(workspaceGridGeometry(payload).areas).toBe('"cell0 cell1"')
  })

  it('restores legacy documents with equal tracks and keeps input detached', () => {
    const payload = capturePresetWorkspace(
      preset('cols2'),
      [pane('left'), pane('right')],
      'left',
      sync
    )
    delete payload.layout.columnWeights
    const grid = workspaceGridGeometry(payload)
    expect(grid.columns).toBe('1fr 1fr')
    payload.panes[0].symbol = 'CHANGED'
    expect(grid.panes[0].pane.symbol).toBe('BHEL')
  })

  it('refuses an incomplete preset capture instead of saving a partial grid', () => {
    expect(() => capturePresetWorkspace(preset('grid4'), [pane('p0')], 'p0', sync)).toThrow(
      /pane|grid/i
    )
    expect(() =>
      capturePresetWorkspace(preset('single'), [pane('p0'), pane('p1')], 'p0', sync)
    ).toThrow(/pane|grid/i)
    expect(() => capturePresetWorkspace(preset('single'), [pane('p0')], 'missing', sync)).toThrow(
      /pane/i
    )
  })

  it('rejects malformed spans and weights before returning renderable geometry', () => {
    const payload = capturePresetWorkspace(preset('cols2'), [pane('p0'), pane('p1')], 'p0', sync)
    payload.layout.slots[1].column = 0
    expect(() => workspaceGridGeometry(payload)).toThrow()
    payload.layout.slots[1].column = 1
    payload.layout.columnWeights = [1, 0]
    expect(() => workspaceGridGeometry(payload)).toThrow()
  })

  it('supports the complete document limit without silently dropping charts', () => {
    const panes = Array.from({ length: 16 }, (_, i) => pane(`p${i}`))
    const payload: WorkspacePayload = {
      panes,
      activePaneId: 'p15',
      sync,
      layout: {
        rows: 4,
        columns: 4,
        slots: panes.map((p, i) => ({
          paneId: p.id,
          row: Math.floor(i / 4),
          column: i % 4,
          rowSpan: 1,
          columnSpan: 1,
        })),
      },
    }
    expect(workspaceGridGeometry(payload).panes).toHaveLength(16)
    expect(workspaceGridGeometry(payload).rows).toBe('1fr 1fr 1fr 1fr')
  })
})
