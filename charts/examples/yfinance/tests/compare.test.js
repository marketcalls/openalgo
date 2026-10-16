import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createChart } from '/dist/openalgo-charts.mjs';
import { fakeDocument } from '../../../tests/helpers/fake-dom';
import { initCompare, openCompare, addCompareSymbol, removeComparison, setCompareMode, syncComparisons,
  comparisonSnapshot, restoreComparisons } from '../src/compare.js';
import { fetchBars } from '../src/feed.js';

vi.mock('../src/feed.js', () => ({ fetchBars: vi.fn() }));
vi.mock('../src/toolbar.js', () => ({ renderToolbar: vi.fn() }));
vi.mock('../src/persist.js', () => ({ autosave: vi.fn() }));

const bars = [{ time: 1, open: 20, high: 21, low: 19, close: 20 }, { time: 2, open: 20, high: 23, low: 20, close: 22 }];
let app, nodes, charts;
function deferred() {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return { promise, resolve };
}

beforeEach(() => {
  vi.clearAllMocks();
  const node = () => ({ innerHTML: '', textContent: '', hidden: true, value: '',
    appendChild: vi.fn(), addEventListener: vi.fn(), focus: vi.fn(), style: {}, setAttribute: vi.fn() });
  nodes = new Map();
  vi.stubGlobal('document', { getElementById: id => {
    if (!nodes.has(id)) nodes.set(id, node());
    return nodes.get(id);
  }, createElement: node });
  charts = [1, 2].map(() => {
    const doc = fakeDocument();
    const chart = createChart(doc.createElement('div'), { document: doc, shortcuts: false,
      raf: { schedule: () => 1, cancel: () => {} }, timezone: 'UTC' });
    chart.addSeries('candlestick').setData(bars);
    return chart;
  });
  app = { chart: charts[0], chart2: charts[1], focusPane: 2,
    req: { symbol: 'AAPL', interval: '1d', period: '1y' },
    p2: { symbol: 'MSFT', interval: '1h', period: '1mo' },
    comparisons: [], comparisons2: [], cmpMode: 'percentage', cmpMode2: 'percentage' };
  fetchBars.mockResolvedValue(bars);
  initCompare(app);
});
afterEach(() => { charts.forEach(chart => chart.destroy()); vi.unstubAllGlobals(); });

describe('comparison chart ownership', () => {
  it('captures the selected request and chart through an asynchronous add and focus change', async () => {
    const pending = deferred();
    fetchBars.mockReturnValue(pending.promise);
    const added = addCompareSymbol(' tsla ');
    app.focusPane = 1;
    pending.resolve(bars);
    await added;
    expect(fetchBars).toHaveBeenCalledWith('TSLA', '1h', '1mo', expect.objectContaining({ timezone: 'UTC', signal: expect.any(AbortSignal) }));
    expect(app.comparisons).toHaveLength(0);
    expect(app.comparisons2).toHaveLength(1);
    expect(app.chart.panes()[0].series()).toHaveLength(1);
    expect(app.chart2.panes()[0].series()).toHaveLength(2);
  });

  it('keeps the dialog mode and removal on its original chart after selection changes', async () => {
    openCompare();
    await addCompareSymbol('TSLA');
    app.focusPane = 1;
    setCompareMode('indexed-to-100');
    expect(app.cmpMode2).toBe('indexed-to-100');
    expect(app.cmpMode).toBe('percentage');
    removeComparison(app.comparisons2[0]);
    expect(app.chart2.panes()[0].series()).toHaveLength(1);
    expect(app.comparisons2).toHaveLength(0);
  });

  it.each(['request', 'timezone', 'destroy'])('discards a response after its owner changes: %s', async change => {
    const pending = deferred();
    fetchBars.mockReturnValue(pending.promise);
    const added = addCompareSymbol('TSLA');
    if (change === 'request') app.p2.interval = '5m';
    if (change === 'timezone') app.chart2.setTimezone('Asia/Kolkata');
    if (change === 'destroy') { app.chart2.destroy(); app.chart2 = null; }
    pending.resolve(bars);
    await added;
    expect(app.comparisons).toHaveLength(0);
    expect(app.comparisons2).toHaveLength(0);
    if (change === 'destroy') expect(fetchBars.mock.calls[0][3].signal.aborted).toBe(true);
  });

  it('deduplicates concurrent additions on one chart', async () => {
    const pending = deferred();
    fetchBars.mockReturnValue(pending.promise);
    const first = addCompareSymbol('tsla');
    const second = addCompareSymbol('TSLA');
    pending.resolve(bars);
    await Promise.all([first, second]);
    expect(fetchBars).toHaveBeenCalledOnce();
    expect(app.comparisons2).toHaveLength(1);
  });

  it('does not add a source while that chart is loading or unavailable', async () => {
    app.loading2 = true;
    await addCompareSymbol('TSLA');
    app.loading2 = false;
    app.loadFailed2 = true;
    await addCompareSymbol('TSLA');
    expect(fetchBars).not.toHaveBeenCalled();
  });

  it('does not resurrect a restored source removed while its history is loading', async () => {
    const pending = deferred();
    fetchBars.mockReturnValue(pending.promise);
    const spec = { symbol: 'TSLA', color: '#e6b53c', bars: [] };
    app.comparisons2.push(spec);
    const synced = syncComparisons(2);
    removeComparison(spec, 2);
    pending.resolve(bars);
    await synced;
    expect(fetchBars).toHaveBeenCalledOnce();
    expect(app.comparisons2).toHaveLength(0);
    expect(app.chart2.panes()[0].series()).toHaveLength(1);
  });

  it.each(['empty', 'error'])('clears stale prices when a different interval returns %s', async result => {
    await addCompareSymbol('TSLA');
    app.p2.interval = '5m';
    if (result === 'empty') fetchBars.mockResolvedValueOnce([]);
    else fetchBars.mockRejectedValueOnce(new Error('History unavailable'));
    await syncComparisons(2);
    const spec = app.comparisons2[0];
    expect(spec.handle.series.getData().filter(bar => Number.isFinite(bar.close))).toHaveLength(0);
    expect(spec.byTime.size).toBe(0);
    expect(spec.error).toBe(result === 'empty' ? 'No data for this interval' : 'History unavailable');
  });

  it('asks for a comparison in its chart session and fetches it again when the session changes', async () => {
    app.p2.session = 'extended';
    await addCompareSymbol('TSLA');
    expect(fetchBars).toHaveBeenLastCalledWith('TSLA', '1h', '1mo', expect.objectContaining({ variant: { session: 'extended' } }));
    app.p2.session = 'regular';
    await syncComparisons(2);
    expect(fetchBars).toHaveBeenCalledTimes(2);
    expect(fetchBars.mock.calls[1][3].variant).toBeUndefined();
  });

  it('restores hidden sources, independent scale modes and legacy colours without runtime handles', async () => {
    await addCompareSymbol('TSLA');
    setCompareMode('indexed-to-100');
    app.chart2.emit('click', { id: 'cmp:TSLA::hide' });
    const saved = comparisonSnapshot(2);
    expect(saved).toEqual({ comparisons: [{ symbol: 'TSLA', color: '#e6b53c', hidden: true }],
      compareMode: 'indexed-to-100', compareBaseMode: 'linear' });
    restoreComparisons({ ...saved, comparisons: [...saved.comparisons, { symbol: 'TSLA' }, null,
      { symbol: 'MSFT', color: '#f00' }] }, 1);
    await syncComparisons(1);
    expect(app.comparisons.map(spec => spec.symbol)).toEqual(['TSLA', 'MSFT']);
    expect(app.comparisons[0].hidden).toBe(true);
    expect(app.comparisons[1].color).toBe('#f00');
    expect(app.chart.panes()[0].priceScale.options.mode).toBe('indexed-to-100');
    for (const spec of app.comparisons.slice()) removeComparison(spec, 1);
    expect(app.chart.panes()[0].priceScale.options.mode).toBe('linear');
    expect(app.comparisons2).toHaveLength(1);
  });
});
