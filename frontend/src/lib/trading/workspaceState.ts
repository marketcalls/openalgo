import { parseWorkspacePayload, type WorkspacePane } from 'openalgo-charts/workspace'

/** Validate before constructing a terminal or touching its preference namespace. */
export function parseTerminalWorkspacePane(input: unknown): WorkspacePane {
  if (!input || typeof input !== 'object' || Array.isArray(input))
    throw new Error('Workspace pane must be a record')
  const identity = Object.getOwnPropertyDescriptor(input, 'id')
  if (!identity || !('value' in identity)) throw new Error('Workspace pane needs a plain ID')
  const id: unknown = identity.value
  const pane = parseWorkspacePayload({
    layout: {
      rows: 1,
      columns: 1,
      slots: [{ paneId: id, row: 0, column: 0, rowSpan: 1, columnSpan: 1 }],
    },
    activePaneId: id,
    panes: [input],
  }).panes[0]
  return pane
}

/** Each preparation owns a detached preference map; no browser write is made. */
export function createWorkspacePanePreferences(
  input: WorkspacePane,
  namespace: string
): Pick<Storage, 'getItem' | 'setItem'> {
  const pane = parseTerminalWorkspacePane(input)
  const grid = pane.chart.grid
  const values = new Map(
    Object.entries({
      symbol: JSON.stringify({ symbol: pane.symbol, exchange: pane.exchange }),
      interval: pane.interval,
      ctype: pane.chartType,
      grid: `${grid?.vertLines === false ? '0' : '1'}${grid?.horzLines === false ? '0' : '1'}`,
      vol: pane.volume ? '1' : '0',
      magnet: pane.magnet === 'off' ? '0' : '1',
      'magnet-mode': pane.magnet,
      stay: pane.stay ? '1' : '0',
      chartsettings: JSON.stringify(pane.settings),
      indicators: JSON.stringify({ version: 2, indicators: pane.chart.indicators ?? [] }),
      draw: JSON.stringify(pane.chart.drawings ?? { version: 2, drawings: [] }),
      alerts: JSON.stringify(pane.chart.alerts ?? { version: 1, alerts: [] }),
      comparisons: JSON.stringify({ mode: pane.comparisonMode, items: pane.comparisons }),
    }).map(([key, value]) => [`${namespace}-${key}`, value])
  )
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => {
      values.set(key, value)
    },
  }
}

export interface WorkspacePaneSupport {
  chartTypes: ReadonlySet<string>
  intervals: ReadonlySet<string>
  indicators: ReadonlySet<string>
}

/** A named layout must never silently substitute another type, interval or study. */
export function validateWorkspacePaneSupport(
  pane: WorkspacePane,
  support: WorkspacePaneSupport
): void {
  if (!support.chartTypes.has(pane.chartType))
    throw new Error(`Unsupported workspace chart type: ${pane.chartType}`)
  if (!support.intervals.has(pane.interval))
    throw new Error(`Unsupported workspace interval: ${pane.interval}`)
  const missing = [
    ...new Set((pane.chart.indicators ?? []).map((study) => study.indicatorId)),
  ].filter((id) => !support.indicators.has(id))
  if (missing.length) throw new Error(`Unavailable workspace studies: ${missing.join(', ')}`)
}
