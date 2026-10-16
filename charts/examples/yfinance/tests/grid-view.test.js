import { describe, it, expect } from 'vitest';
import { DataLoadingController } from '/dist/openalgo-charts.mjs';
import { parseWorkspaceDocument } from '/dist/openalgo-charts.workspace.mjs';
import { layoutIconPath } from '/dist/openalgo-charts.draw.mjs';
import { CHART_GRID_LAYOUTS, CHART_GRID_LAYOUT_NAMES } from '/dist/openalgo-charts.widget.mjs';
import {
  GRID_HANDOFF_KEY, GRID_INTERVALS, GRID_PRESET_LABELS, gridFeed, gridFeeds, gridPeriod, gridViewRefusal, presetGlyph, handOffToGrid, takeGridHandoff, readGridFile, gridDocument,
} from '../src/grid-view.js';
import { needsGridView, validateReferenceWorkspace, layoutFromWorkspace } from '../src/workspace-document.js';
import { gridFileDocument, workspaceFileDocument } from '../src/workspaces.js';

const pane = (id, symbol) => ({
  id, symbol, exchange: '', interval: '1d', chartType: 'candlestick', chart: { version: 1 }, settings: {},
  volume: true, magnet: 'off', stay: false, comparisons: [], comparisonMode: 'percent',
});
function payload(rows, columns) {
  const panes = Array.from({ length: rows * columns }, (_, i) => pane(`p${i}`, ['AAPL', 'MSFT', 'TSLA', 'NVDA'][i]));
  return { panes, activePaneId: 'p0', sync: { crosshair: true, viewport: true, symbol: false, interval: false },
    layout: { rows, columns, slots: panes.map((p, i) => ({ paneId: p.id, row: Math.floor(i / columns), column: i % columns, rowSpan: 1, columnSpan: 1 })) } };
}
class MemoryStorage {
  constructor() { this.map = new Map(); }
  getItem(key) { return this.map.has(key) ? this.map.get(key) : null; }
  setItem(key, value) { this.map.set(key, String(value)); }
  removeItem(key) { this.map.delete(key); }
}

describe('grid view feed', () => {
  it('asks the history endpoint for each widget interval by the period the source serves', async () => {
    const asked = [];
    const feed = gridFeed({ getBars: async req => { asked.push(req); return []; } });
    const signal = new AbortController().signal;
    for (const interval of GRID_INTERVALS) await feed.getBars({ symbol: 'AAPL', exchange: '', interval, from: 0, to: 1, signal });
    expect(asked.map(req => [req.interval, req.period])).toEqual([
      ['1m', '5d'], ['5m', '1mo'], ['15m', '1mo'], ['1h', '6mo'], ['1d', '5y'], ['1wk', '10y'],
    ]);
    expect(asked.every(req => req.signal === signal && req.symbol === 'AAPL')).toBe(true);
  });

  it('loads the history period a layout saved wherever the interval can serve it', async () => {
    const asked = [];
    const source = { getBars: async req => { asked.push([req.interval, req.period]); return []; } };
    const signal = new AbortController().signal;
    const cases = [['1d', '10y'], ['1h', '1y'], ['5m', '5y'], ['1m', '5d'], ['1d', undefined], ['1w', 'max'], ['1d', 'toString'], ['1d', '1y'], ['1w', '1y']];
    for (const [interval, period] of cases) await gridFeed(source, { period }).getBars({ symbol: 'AAPL', exchange: '', interval, signal });
    // Five years of 5m bars is more than the source keeps, so that chart loads its usual month.
    // A year of daily bars is under 500 candles, so that chart loads its usual five years;
    // a weekly chart has no such floor and keeps the year.
    expect(asked).toEqual([['1d', '10y'], ['1h', '1y'], ['5m', '1mo'], ['1m', '5d'], ['1d', '5y'], ['1wk', 'max'], ['1d', '5y'], ['1d', '5y'], ['1wk', '1y']]);
    expect(gridPeriod('1h', '2y')).toBe('6mo');
    for (const short of ['1d', '5d', '1mo', '3mo', '6mo', 'ytd', '1y', '2y']) expect(gridPeriod('1d', short)).toBe('5y');
    expect(['5y', '10y', 'max'].map(long => gridPeriod('1d', long))).toEqual(['5y', '10y', 'max']);
  });

  it('gives the charts of one period one feed, so they still share a request', async () => {
    const asked = [];
    const feeds = gridFeeds({}, { getBars: async req => { asked.push(req.period); return []; } });
    const long = feeds({ id: 'a', historyPeriod: 'max' });
    expect(feeds({ id: 'b', historyPeriod: 'max' })).toBe(long);
    expect(feeds({ id: 'c' })).toBe(feeds({ id: 'd' }));
    expect(feeds({ id: 'c' })).not.toBe(long);
    await long.getBars({ symbol: 'AAPL', exchange: '', interval: '1d' });
    await feeds({ id: 'c' }).getBars({ symbol: 'AAPL', exchange: '', interval: '1d' });
    expect(asked).toEqual(['max', '5y']);
  });

  it('tells history paging there is nothing older, so a left edge downloads nothing again', async () => {
    const asked = [];
    const bars = Array.from({ length: 50 }, (_, i) => ({ time: 1_700_000_000 + i * 86400, open: 1, high: 2, low: 0.5, close: 1.5 }));
    const feed = gridFeed({ getBars: async req => { asked.push(req.period); return bars.map(bar => ({ ...bar })); } });
    const controller = new DataLoadingController(feed);
    await controller.load({ symbol: 'AAPL', exchange: '', interval: '1d', from: 1_700_000_000, to: 1_705_000_000 });
    for (let i = 0; i < 3; i++) await controller.loadMore();
    expect(asked).toEqual(['5y']);
    expect(controller.getState()).toMatchObject({ hasMore: false, historyStatus: 'exhausted' });
    controller.destroy();
  });

  it('holds requests until the hand-off is applied, and drops the ones cancelled meanwhile', async () => {
    const asked = [];
    let release;
    const ready = new Promise(resolve => { release = resolve; });
    const feed = gridFeed({ getBars: async req => { asked.push(req.symbol); return []; } }, { ready });
    const replaced = new AbortController();
    const first = feed.getBars({ symbol: 'OLD', exchange: '', interval: '1d', signal: replaced.signal });
    const second = feed.getBars({ symbol: 'NEW', exchange: '', interval: '1d', signal: new AbortController().signal });
    await Promise.resolve();
    expect(asked).toEqual([]);
    replaced.abort();
    release();
    await expect(first).rejects.toMatchObject({ name: 'AbortedError' });
    await second;
    expect(asked).toEqual(['NEW']);
  });
});

describe('grid view documents', () => {
  it('tells the main page which valid layouts only the grid view can show', () => {
    expect(needsGridView(payload(2, 2))).toBe(true);
    expect(needsGridView(payload(1, 3))).toBe(true);
    expect(needsGridView(payload(2, 1))).toBe(true);
    expect(needsGridView(payload(1, 2))).toBe(false);
    expect(needsGridView(payload(1, 1))).toBe(false);
    expect(needsGridView({ layout: 1 })).toBe(false);
    expect(() => validateReferenceWorkspace(payload(2, 2))).toThrow(/grid view/);
    expect(gridFileDocument(JSON.stringify(payload(2, 2)))).toMatchObject({ layout: { rows: 2, columns: 2 } });
    expect(gridFileDocument(JSON.stringify(payload(1, 2)))).toBeNull();
    expect(gridFileDocument('{not json')).toBeNull();
  });

  it('hands a layout to the grid view once and survives a refusing store', () => {
    const storage = new MemoryStorage();
    expect(handOffToGrid(payload(2, 2), storage)).toBe(true);
    expect(JSON.parse(storage.getItem(GRID_HANDOFF_KEY)).layout.rows).toBe(2);
    const text = takeGridHandoff(storage);
    expect(readGridFile(text).panes).toHaveLength(4);
    expect(takeGridHandoff(storage)).toBeNull();
    const refusing = { setItem() { throw new Error('quota'); }, getItem() { throw new Error('blocked'); }, removeItem() {} };
    expect(handOffToGrid(payload(2, 2), refusing)).toBe(false);
    expect(takeGridHandoff(refusing)).toBeNull();
  });

  it('names what the grid view cannot open before the main page hands it over', () => {
    expect(gridViewRefusal(payload(2, 2))).toBe('');
    const compared = payload(2, 2);
    compared.panes[1].comparisons = [{ id: 'c', symbol: 'QQQ', exchange: '', visible: true }];
    expect(gridViewRefusal(compared)).toMatch(/MSFT: comparison symbols/);
    const monthly = payload(2, 2);
    monthly.panes[2].interval = '1mo';
    expect(gridViewRefusal(monthly)).toMatch(/TSLA: the grid view has no 1mo interval/);
    const weekly = payload(2, 2);
    for (const pane of weekly.panes) pane.interval = '1wk';
    weekly.sync.interval = true;
    expect(gridViewRefusal(weekly)).toBe('');
    expect(readGridFile(JSON.stringify(weekly)).panes.map(pane => pane.interval)).toEqual(['1w', '1w', '1w', '1w']);
    const periods = payload(2, 2);
    periods.panes[0].historyPeriod = '5y';
    expect(gridViewRefusal(periods)).toBe('');
    periods.panes[3].historyPeriod = 'forever';
    expect(gridViewRefusal(periods)).toMatch(/NVDA: the grid view cannot load a forever history period/);
    periods.panes[3].historyPeriod = 'constructor';
    expect(gridViewRefusal(periods)).toMatch(/cannot load a constructor history period/);
    const linked = payload(2, 2);
    linked.sync.symbol = true;
    expect(gridViewRefusal(linked)).toMatch(/linked by symbol/);
    expect(() => readGridFile(JSON.stringify(monthly))).toThrow(/1mo/);
  });

  it('checks saved link groups one by one: two groups may show two instruments, one group may not', () => {
    const grouped = payload(2, 2);
    grouped.sync.groups = [
      { id: 'a', name: 'Tech', crosshair: true, viewport: true, symbol: true, interval: false },
      { id: 'b', name: 'Cars', crosshair: true, viewport: false, symbol: true, interval: false, chartType: true },
    ];
    grouped.panes.forEach((pane, i) => { pane.linkGroup = i < 2 ? 'a' : 'b'; pane.symbol = i < 2 ? 'AAPL' : 'TSLA'; });
    expect(gridViewRefusal(grouped)).toBe('');
    expect(readGridFile(JSON.stringify(grouped)).sync.groups).toHaveLength(2);
    grouped.panes[1].symbol = 'MSFT';
    expect(gridViewRefusal(grouped)).toMatch(/linked by symbol/);
    grouped.panes[1].symbol = 'AAPL';
    grouped.panes[3].chartType = 'line';
    expect(gridViewRefusal(grouped)).toMatch(/linked by chart type/);
  });

  it('reads complete documents and bare payloads, and refuses malformed files before any chart changes', () => {
    const document = gridDocument(payload(2, 2), { name: 'Desk', now: 5 });
    expect(document).toMatchObject({ kind: 'workspace', version: 1, id: 'grid-5', name: 'Desk', createdAt: 5 });
    expect(parseWorkspaceDocument(JSON.stringify(document)).layout.rows).toBe(2);
    expect(readGridFile(JSON.stringify(document)).panes).toHaveLength(4);
    expect(readGridFile(JSON.stringify(payload(1, 3))).layout.columns).toBe(3);
    expect(() => readGridFile('{"panes":[]}')).toThrow();
    expect(() => gridDocument({ ...payload(1, 1), activePaneId: 'missing' })).toThrow();
  });

  it('opens on the main page a one or two chart layout the grid view exported', () => {
    const exported = gridDocument(payload(1, 2));
    for (const pane of exported.panes) {
      pane.settings = { 'widget.theme': 'light' };
      // A window counted in the grid view's bars, which are not this page's.
      pane.chart = { version: 1, viewport: { from: 450, to: 525 }, barSpacing: 12, indicators: [] };
    }
    exported.panes[0].interval = '1w';
    // A period the main page saved at 1d, on a chart the grid view moved to 1h.
    Object.assign(exported.panes[1], { interval: '1h', historyPeriod: '5y' });
    const text = JSON.stringify(exported);
    expect(() => layoutFromWorkspace(JSON.parse(text))).toThrow();
    const layout = layoutFromWorkspace(workspaceFileDocument(text, 'grid.json'));
    expect(layout.request).toEqual({ symbol: 'AAPL', interval: '1wk', period: '1y' });
    expect(layout.secondary.request).toEqual({ symbol: 'MSFT', interval: '1h', period: '1y' });
    expect([layout.viewport, layout.barSpacing, layout.secondary.state.viewport]).toEqual([undefined, undefined, undefined]);
    expect(layout.indicators).toEqual([]);
    // A document of the main page's own keeps its strict checks untouched.
    const own = gridDocument(payload(1, 2));
    own.panes[0].interval = '1w';
    own.panes[1].historyPeriod = 'max';
    own.panes[1].interval = '5m';
    expect(workspaceFileDocument(JSON.stringify(own), 'own.json')).toEqual(own);
  });

  it('opens a grid layout on the main page with the page range nearest each server period it saved', () => {
    // Per interval: the server's periods the main page has no range for, and the range each opens with.
    const nearest = { '1d': '1mo', '5d': '1mo', '3mo': '6mo', ytd: '1y', '2y': '1y', '10y': '5y' };
    const expected = {
      '5m': { '1d': '1mo', '5d': '1mo', '3mo': '1mo', ytd: '1mo', '2y': '1mo', '10y': '1mo' },
      '15m': { '1d': '1mo', '5d': '1mo', '3mo': '1mo', ytd: '1mo', '2y': '1mo', '10y': '1mo' },
      '1h': { ...nearest, '10y': '1y' },
      // Every nearest range under five years is raised to the daily floor.
      '1d': { '1d': '5y', '5d': '5y', '3mo': '5y', ytd: '5y', '2y': '5y', '10y': '5y' },
      '1w': nearest,
    };
    const opened = {};
    for (const [interval, periods] of Object.entries(expected)) {
      opened[interval] = {};
      for (const period of Object.keys(periods)) {
        const exported = gridDocument(payload(1, 1));
        Object.assign(exported.panes[0], { interval, historyPeriod: period, settings: { 'widget.theme': 'dark' } });
        opened[interval][period] = layoutFromWorkspace(workspaceFileDocument(JSON.stringify(exported), 'grid.json')).request.period;
      }
    }
    expect(opened).toEqual(expected);
  });

  it('names every layout the grid offers as the picker does, and draws its glyph from its own slots', () => {
    const ids = Object.keys(CHART_GRID_LAYOUTS);
    expect(ids).toHaveLength(26);
    expect(Object.keys(GRID_PRESET_LABELS)).toEqual(ids);
    for (const id of ids) {
      expect(GRID_PRESET_LABELS[id]).toBe(CHART_GRID_LAYOUT_NAMES[id]);
      const { rows, columns, slots } = CHART_GRID_LAYOUTS[id];
      expect(presetGlyph(id)).toContain(`<path d="${layoutIconPath(rows, columns, slots)}"/>`);
    }
    expect(GRID_PRESET_LABELS['corner-7']).toBe('Large corner, seven around');
    // A large chart spanning two cells is one pane in its glyph: no divider runs through it.
    expect(presetGlyph('left-2')).not.toBe(presetGlyph('2x2'));
    expect(presetGlyph('hand-made')).toBe('');
    expect(presetGlyph('constructor')).toBe('');
  });
});
