import {
  parseWorkspacePayload,
  type WorkspacePane,
  type WorkspacePayload,
} from 'openalgo-charts/workspace'
import type { LayoutPreset } from '@/lib/chart/layouts'

export interface WorkspaceGridGeometry {
  rows: string
  columns: string
  areas: string
  panes: { id: string; area: string; pane: WorkspacePane }[]
}

/** Imported names never become CSS; validated integer slots determine every area. */
export function workspaceGridGeometry(input: WorkspacePayload): WorkspaceGridGeometry {
  const payload = parseWorkspacePayload(input)
  const { layout } = payload
  const panes = payload.panes.map((pane, index) => ({ id: pane.id, area: `cell${index}`, pane }))
  const areas = new Map(panes.map((pane) => [pane.id, pane.area]))
  const cells = Array.from({ length: layout.rows }, () => Array<string>(layout.columns).fill('.'))
  for (const slot of layout.slots) {
    for (let row = slot.row; row < slot.row + slot.rowSpan; row++) {
      for (let column = slot.column; column < slot.column + slot.columnSpan; column++) {
        cells[row][column] = areas.get(slot.paneId)!
      }
    }
  }
  const tracks = (count: number, weights?: number[]) =>
    Array.from({ length: count }, (_, index) => `${weights?.[index] ?? 1}fr`).join(' ')
  return {
    rows: tracks(layout.rows, layout.rowWeights),
    columns: tracks(layout.columns, layout.columnWeights),
    areas: cells.map((row) => `"${row.join(' ')}"`).join(' '),
    panes,
  }
}

/** Capturing an unnamed grid is its migration boundary; no legacy key is rewritten. */
export function capturePresetWorkspace(
  preset: LayoutPreset,
  panes: WorkspacePane[],
  activePaneId: string,
  sync: WorkspacePayload['sync']
): WorkspacePayload {
  if (panes.length !== preset.cells.length)
    throw new Error('Every grid pane must be ready before saving')
  const rows = [...preset.areas.matchAll(/"([^"]+)"/g)].map((match) => match[1].trim().split(/\s+/))
  const rowWeights = preset.rows
    .trim()
    .split(/\s+/)
    .map((track) => Number(track.replace(/fr$/, '')))
  const columnWeights = preset.cols
    .trim()
    .split(/\s+/)
    .map((track) => Number(track.replace(/fr$/, '')))
  if (rows.length !== rowWeights.length || rows.some((row) => row.length !== columnWeights.length))
    throw new Error('Invalid chart grid preset')
  const slots = preset.cells.map((cell, index) => {
    const occupied: { row: number; column: number }[] = []
    rows.forEach((row, rowIndex) =>
      row.forEach((name, column) => {
        if (name === cell) occupied.push({ row: rowIndex, column })
      })
    )
    if (!occupied.length) throw new Error('Missing chart grid area')
    const row = Math.min(...occupied.map((position) => position.row))
    const column = Math.min(...occupied.map((position) => position.column))
    const rowSpan = Math.max(...occupied.map((position) => position.row)) - row + 1
    const columnSpan = Math.max(...occupied.map((position) => position.column)) - column + 1
    if (occupied.length !== rowSpan * columnSpan)
      throw new Error('Chart grid area must be rectangular')
    return { paneId: panes[index].id, row, column, rowSpan, columnSpan }
  })
  return parseWorkspacePayload({
    panes,
    activePaneId,
    sync,
    layout: {
      preset: preset.id,
      rows: rowWeights.length,
      columns: columnWeights.length,
      rowWeights,
      columnWeights,
      slots,
    },
  })
}
