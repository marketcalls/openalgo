export function workspaceFixture() {
  const pane = (id: string, symbol: string, interval: string) => ({
    id, symbol, exchange: 'NSE', interval, chartType: 'candlestick',
    chart: {
      version: 1, viewport: { from: 0, to: 40 }, crosshairSnapToBar: true,
      indicators: [
        { indicatorId: 'ema', settings: { period: 9, 'plot.ema.color': '#ff0' }, paneIndex: 0, visible: true },
        { indicatorId: 'ema', settings: { period: 21, 'plot.ema.color': '#0ff' }, paneIndex: 0, visible: false },
      ],
      drawings: { version: 2, drawings: [{ id: 'line1', tool: 'hline', points: [{ time: 1700000000, price: 100 }] }] },
    },
    settings: { 'volume.showMA': true, 'volume.maPeriod': 20 },
    volume: true, magnet: 'weak' as const, stay: false,
    comparisons: [{ id: 'cmp1', symbol: 'NIFTY', exchange: 'NSE_INDEX', color: '#ace', visible: true }],
    comparisonMode: 'percent' as const,
  });
  return {
    kind: 'workspace' as const, version: 1 as const, id: 'desk', name: 'Morning desk',
    createdAt: 1000, updatedAt: 2000,
    layout: { rows: 1, columns: 2, preset: 'split', slots: [
      { paneId: 'p0', row: 0, column: 0, rowSpan: 1, columnSpan: 1 },
      { paneId: 'p1', row: 0, column: 1, rowSpan: 1, columnSpan: 1 },
    ] },
    panes: [pane('p0', 'BHEL', '5m'), pane('p1', 'RELIANCE', '1h')], activePaneId: 'p1',
    sync: { crosshair: true, viewport: true, symbol: false, interval: false },
  };
}
