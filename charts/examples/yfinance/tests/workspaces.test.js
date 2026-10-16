import { describe, it, expect } from 'vitest';
import { gridFileDocument, workspaceFileDocument } from '../src/workspaces.js';

describe('reference layout file compatibility', () => {
  it('accepts an older wrapped file with explicit source metadata as a named document', () => {
    const layout = { schema: 2, version: 1, dataset: 'MSFT|1d|1y', chartType: 'line', indicators: [] };
    const result = workspaceFileDocument(JSON.stringify({ app: 'openalgo-charts yfinance demo', layout }), 'Desk.json');
    expect(result).toMatchObject({ kind: 'workspace', name: 'Desk', panes: [{ symbol: 'MSFT', interval: '1d', chartType: 'line' }] });
  });

  it('leaves named portable documents to the existing catalog validator', () => {
    const input = { kind: 'workspace', version: 1, name: 'Source' };
    expect(workspaceFileDocument(JSON.stringify(input), 'ignored.json')).toEqual(input);
  });

  it('drops every drawing policy from an imported document, in both chart formats', () => {
    const planted = { id: 'x', tool: 'horizontal-line', paneIndex: 0, zIndex: 0, style: {}, points: [{ time: 1, price: 2 }],
      policy: { editable: false, selectable: false, listed: false } };
    const drawings = { version: 2, drawings: [planted] };
    const named = { kind: 'workspace', version: 1, name: 'Shared', panes: [{ id: 'primary', chart: { drawings } }] };
    const result = workspaceFileDocument(JSON.stringify(named), 'Shared.json');
    expect(result.panes[0].chart.drawings.drawings[0].policy).toBeUndefined();
    expect(result.panes[0].chart.drawings.drawings[0].points).toEqual(planted.points);
    const layout = { schema: 2, version: 1, dataset: 'MSFT|1d|1y', chartType: 'line', indicators: [], drawings };
    const legacy = workspaceFileDocument(JSON.stringify({ layout }), 'Desk.json');
    expect(JSON.stringify(legacy)).not.toContain('policy');
  });

  it('drops drawing policies from a grid view file, whichever page opens it', () => {
    const planted = { id: 'x', tool: 'horizontal-line', paneIndex: 0, zIndex: 0, style: {}, points: [{ time: 1, price: 2 }],
      policy: { editable: false, selectable: false, listed: false } };
    const chart = { version: 1, drawings: { version: 2, drawings: [planted] } };
    const pane = id => ({ id, symbol: 'MSFT', exchange: '', interval: '1d', chartType: 'candlestick', chart,
      settings: { 'widget.theme': 'dark' }, volume: false, magnet: 'off', stay: false, comparisons: [], comparisonMode: 'percent' });
    const grid = { kind: 'workspace', version: 1, name: 'Desk', panes: [pane('a'), pane('b')], activePaneId: 'a',
      sync: { crosshair: true, viewport: true, symbol: false, interval: false },
      layout: { rows: 2, columns: 1, slots: [{ paneId: 'a', row: 0, column: 0, rowSpan: 1, columnSpan: 1 },
        { paneId: 'b', row: 1, column: 0, rowSpan: 1, columnSpan: 1 }] } };
    const text = JSON.stringify(grid);
    // This page's own import path, after the grid view's terms are translated.
    expect(JSON.stringify(workspaceFileDocument(text, 'Desk.json'))).not.toContain('policy');
    // The hand-off to the grid view, which would otherwise honour the policy.
    const handed = gridFileDocument(text);
    expect(handed.layout.rows).toBe(2);
    expect(JSON.stringify(handed)).not.toContain('policy');
    expect(handed.panes[1].chart.drawings.drawings[0].points).toEqual(planted.points);
  });

  it('refuses an ambiguous legacy source without guessing from the live chart', () => {
    expect(() => workspaceFileDocument(JSON.stringify({ schema: 2, version: 1, dataset: 'A|B|1d|1y' }), 'Old.json')).toThrow(/source|request/i);
  });

  it('rejects invalid JSON before any chart or repository action', () => {
    expect(() => workspaceFileDocument('{invalid', 'Bad.json')).toThrow();
  });
});
