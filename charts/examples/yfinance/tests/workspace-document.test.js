import { describe, it, expect } from 'vitest';
import { parseAlertsDocument } from '/dist/openalgo-charts.mjs';
import { workspaceFromLayout, layoutFromWorkspace, validateReferenceWorkspace } from '../src/workspace-document.js';
import { primaryLayoutSelection } from '../src/persist.js';

function state(symbol = 'AAPL') {
  return { version: 1, timezone: 'America/New_York', viewport: { from: 4, to: 45 }, barSpacing: 7,
    grid: { vertLines: false, horzLines: true }, crosshairSnapToBar: true,
    indicators: [
      { instanceId: 'fast', indicatorId: 'ema', settings: { period: 9, 'plot.ema.color': '#ff0000' }, paneIndex: 0, visible: true },
      { instanceId: 'slow', indicatorId: 'ema', settings: { period: 21 }, paneIndex: 0, visible: false },
      { instanceId: 'custom', indicatorId: 'host-study', settings: { length: 5 }, paneIndex: 2 },
    ],
    drawings: { version: 2, drawings: [{ id: 'level', tool: 'hline', points: [{ time: 1700000000, price: 101 }] }] },
    alerts: parseAlertsDocument({ version: 1, alerts: [{ id: 'fired', source: { kind: 'drawing', drawingId: 'level' },
      scope: { symbol, interval: '1d' }, state: 'triggered', repeat: 'once' }] }),
  };
}

/** Options as the box settings dialogs write them. */
const PF_QUARTER = { mode: 'percent', percent: 0.25, reversal: 2, method: 'close' };
const RENKO_ATR = { mode: 'atr', atrMultiplier: 1.5, atrPeriod: 14, method: 'hl' };
const transformKeys = settings => Object.keys(settings).filter(key => key.startsWith('reference.transform.'));

function layout() {
  return { schema: 2, ...state(), dataset: 'AAPL|1d|1y',
    request: { symbol: 'AAPL', interval: '1d', period: '1y', account: 'private' },
    chartType: 't:point-figure', transforms: { 'point-figure': PF_QUARTER, renko: RENKO_ATR }, volume: false,
    volumeSettings: { 'volume.visible': false, 'volume.showMA': true, 'volume.maPeriod': 14, 'volume.maColor': '#aabbcc' },
    comparisons: [{ symbol: 'MSFT', color: '#abcdef', hidden: true }],
    compareMode: 'indexed-to-100', compareBaseMode: 'logarithmic', focusPane: 2,
    linkOptions: { crosshair: true, viewport: false, symbol: false, interval: true, whenMissing: 'hide' },
    secondary: { request: { symbol: 'TSLA', interval: '15m', period: '1mo' }, chartType: 'line', transforms: { renko: RENKO_ATR }, width: 35,
      state: { ...state('TSLA'), timezone: 'Asia/Kolkata' },
      volumeSettings: { 'volume.visible': true, 'volume.showMA': false },
      comparisons: [{ symbol: 'GOOGL', color: '#123456', hidden: false }], compareMode: 'none', compareBaseMode: 'linear' },
    orders: [{ id: 'private' }], positions: [{ symbol: 'AAPL' }], credentials: { key: 'private' },
  };
}

describe('reference workspace documents', () => {
  it('saves a chart on extended hours as the engine variant and reopens it on extended hours', () => {
    const original = layout();
    original.secondary.request = { ...original.secondary.request, session: 'extended' };
    const saved = workspaceFromLayout(original);
    expect(saved.panes[0]).not.toHaveProperty('variant');
    expect(saved.panes[1].variant).toEqual({ session: 'extended' });
    const restored = layoutFromWorkspace(saved);
    expect(restored.request).not.toHaveProperty('session');
    expect(restored.secondary.request.session).toBe('extended');
  });
  it('refuses a variant this source cannot serve instead of reopening another series', () => {
    const saved = workspaceFromLayout(layout());
    const secondary = saved.panes[1];
    for (const variant of [{ adjustment: 'raw' }, { session: 'extended', currency: 'USD' }]) {
      expect(() => validateReferenceWorkspace({ ...saved, panes: [saved.panes[0], { ...secondary, variant }] }), JSON.stringify(variant)).toThrow();
    }
    // Regular hours by name are this source's default series.
    expect(layoutFromWorkspace({ ...saved, panes: [saved.panes[0], { ...secondary, variant: { session: 'regular' } }] }).secondary.request)
      .not.toHaveProperty('session');
    // Extended hours for a daily chart, which this source has none of.
    expect(() => validateReferenceWorkspace({ ...saved, panes: [{ ...saved.panes[0], interval: '1d', variant: { session: 'extended' } }, secondary] }))
      .toThrow(/not available/);
  });
  it.each(['priceOnlyAutoScale', 'indicatorLegendCollapsed'])('retains independent %s choices in both chart slots', preference => {
    const original = layout();
    original[preference] = true;
    original.secondary.state[preference] = false;
    const restored = layoutFromWorkspace(workspaceFromLayout(original));
    expect(restored[preference]).toBe(true);
    expect(restored.secondary.state[preference]).toBe(false);
  });
  it('keeps a price pane moved below its studies in either chart slot', () => {
    const original = layout();
    const panes = [{ weight: 0.32, priceScale: { marginTop: 0.1, marginBottom: 0.1, minMove: 0, mode: 'linear', inverted: false, autoScale: true } },
      { weight: 1, priceScale: { marginTop: 0.1, marginBottom: 0.1, minMove: 0.01, mode: 'linear', inverted: false, autoScale: true } }];
    Object.assign(original, { version: 2, panes, primaryPane: 1 });
    original.secondary.state = { ...original.secondary.state, version: 2, panes, primaryPane: 1 };
    const saved = workspaceFromLayout(original);
    expect(saved.panes.map(pane => [pane.chart.version, pane.chart.primaryPane])).toEqual([[2, 1], [2, 1]]);
    const restored = layoutFromWorkspace(saved);
    expect([restored.version, restored.primaryPane]).toEqual([2, 1]);
    expect(restored.secondary.state.primaryPane).toBe(1);
    // A layout with its price pane on top is written exactly as before.
    expect('primaryPane' in layoutFromWorkspace(workspaceFromLayout(layout()))).toBe(false);
  });
  it('round-trips independent information dock choices and widths', () => {
    const original = layout();
    original.inspection = { panel: 'data', width: 280 };
    original.secondary.inspection = { panel: 'objects', width: 340 };
    const saved = workspaceFromLayout(original);
    expect(layoutFromWorkspace(saved)).toMatchObject({
      inspection: original.inspection, secondary: { inspection: original.secondary.inspection },
    });
  });
  it('round-trips independent legend button sizes and defaults legacy layouts', () => {
    const original = layout();
    original.legendIconSize = 24;
    original.secondary.legendIconSize = 12;
    const saved = workspaceFromLayout(original);
    expect(saved.panes.map(pane => pane.settings['reference.legendIconSize'])).toEqual([24, 12]);
    expect(layoutFromWorkspace(saved)).toMatchObject({ legendIconSize: 24, secondary: { legendIconSize: 12 } });
    expect(layoutFromWorkspace(workspaceFromLayout(layout())).legendIconSize).toBe(16);
  });

  it.each([11, 29, '24', null])('rejects invalid named workspace legend sizes (%s)', value => {
    const saved = workspaceFromLayout(layout());
    saved.panes[0].settings['reference.legendIconSize'] = value;
    expect(() => validateReferenceWorkspace(saved)).toThrow();
  });
  it('round-trips both source selections, host settings, ownership and split geometry', () => {
    const original = layout();
    const document = workspaceFromLayout(original, { magnet: 'strong', stay: true });
    expect(document.layout.columnWeights).toEqual([65, 35]);
    expect(document.activePaneId).toBe(document.layout.slots[1].paneId);
    const restored = layoutFromWorkspace(document);
    // The layout saved its daily chart over one year, before daily charts loaded five.
    expect(restored).toMatchObject({ request: { symbol: 'AAPL', interval: '1d', period: '5y' },
      chartType: original.chartType, transforms: original.transforms, timezone: 'America/New_York',
      compareMode: 'indexed-to-100', compareBaseMode: 'logarithmic', comparisons: original.comparisons,
      focusPane: 2, linkOptions: original.linkOptions, volume: false, volumeSettings: original.volumeSettings,
      magnet: 'strong', stay: true,
      secondary: { ...original.secondary, volumeSettings: original.secondary.volumeSettings } });
    expect(workspaceFromLayout(restored, { magnet: restored.magnet, stay: restored.stay })).toEqual(document);
  });

  it('keeps each transform option as a scalar setting of its own and reads it back', () => {
    const saved = workspaceFromLayout(layout());
    expect(saved.panes[0].settings).toMatchObject({ 'reference.transform.point-figure.mode': 'percent',
      'reference.transform.point-figure.percent': 0.25, 'reference.transform.point-figure.reversal': 2,
      'reference.transform.point-figure.method': 'close', 'reference.transform.renko.atrMultiplier': 1.5 });
    expect(saved.panes[0].settings).not.toHaveProperty('reference.pfmode');
    expect(layoutFromWorkspace(saved).transforms).toEqual({ 'point-figure': PF_QUARTER, renko: RENKO_ATR });
    expect(layoutFromWorkspace(saved).secondary.transforms).toEqual({ renko: RENKO_ATR });
  });

  it('opens a workspace saved with the old box mode on the options that mode drew', () => {
    // A layout of the old shape, converted now: its box mode becomes options.
    const legacy = layout(); delete legacy.transforms; legacy.pfmode = 'fixed';
    expect(layoutFromWorkspace(workspaceFromLayout(legacy)).transforms)
      .toEqual({ 'point-figure': { mode: 'fixed', boxSize: 0, reversal: 3, method: 'hl' } });
    // A workspace stored by the old page holds the mode as a setting.
    const saved = workspaceFromLayout(layout());
    for (const key of transformKeys(saved.panes[0].settings)) delete saved.panes[0].settings[key];
    saved.panes[0].settings['reference.pfmode'] = 'percent';
    const restored = layoutFromWorkspace(saved);
    expect(restored.pfmode).toBe('percent');
    // Every reader of a layout takes the mode through the same migration.
    expect(primaryLayoutSelection(restored).transforms).toEqual({ 'point-figure': { mode: 'percent', percent: 1, reversal: 3, method: 'hl' } });
  });

  it('preserves repeated/custom study identities, styles, grouping and triggered anchored alerts without sharing objects', () => {
    const original = layout();
    const saved = workspaceFromLayout(original);
    const restored = layoutFromWorkspace(saved);
    expect(restored.indicators).toEqual(original.indicators);
    expect(restored.drawings).toEqual(original.drawings);
    expect(restored.alerts).toEqual(original.alerts);
    expect(restored.secondary.state.alerts.alerts[0]).toMatchObject({ state: 'triggered', repeat: 'once', source: { drawingId: 'level' } });
    original.indicators[0].settings.period = 100;
    restored.indicators[1].settings.period = 200;
    expect(saved.panes[0].chart.indicators.map(item => item.settings.period)).toEqual([9, 21, undefined]);
    expect(JSON.stringify(saved)).not.toMatch(/private|credentials|orders|positions|account/);
  });

  it('uses slots rather than pane-array order and rejects geometry the host cannot render', () => {
    const saved = workspaceFromLayout(layout());
    saved.panes.reverse(); saved.layout.slots.reverse();
    expect(layoutFromWorkspace(saved)).toMatchObject({ request: { symbol: 'AAPL' }, secondary: { request: { symbol: 'TSLA' } }, focusPane: 2 });
    saved.layout.rows = 2; saved.layout.columns = 1; delete saved.layout.columnWeights;
    saved.layout.slots.forEach((slot, i) => { slot.row = i; slot.column = 0; });
    expect(() => layoutFromWorkspace(saved)).toThrow(/horizontal|geometry/i);
  });

  it('supports one chart and legacy dataset recovery without inventing a missing source', () => {
    const source = layout(); delete source.secondary; delete source.request; delete source.chartType; delete source.transforms;
    const saved = workspaceFromLayout(source);
    expect(saved.panes).toHaveLength(1);
    // The legacy key names a daily year, which opens at the five year daily floor.
    expect(saved.panes[0]).toMatchObject({ symbol: 'AAPL', chartType: 'candlestick', historyPeriod: '5y' });
    expect(layoutFromWorkspace(saved)).toMatchObject({ focusPane: 1, request: { symbol: 'AAPL', interval: '1d', period: '5y' } });
    expect(layoutFromWorkspace(saved).secondary).toBeUndefined();
    expect(() => workspaceFromLayout({ ...source, dataset: 'A|B|1d|1y' })).toThrow(/source|request/i);
  });

  it('raises a period saved under the interval floor, and still refuses one past its cap', () => {
    const saved = workspaceFromLayout(layout());
    const opened = (interval, historyPeriod) => {
      Object.assign(saved.panes[0], { interval, historyPeriod });
      return validateReferenceWorkspace(saved).panes[0].historyPeriod;
    };
    // More history than was saved, over the same view: the chart opens rather than being refused.
    expect(opened('1d', '1y')).toBe('5y');
    expect(layoutFromWorkspace(saved).request).toMatchObject({ interval: '1d', period: '5y' });
    expect(['1mo', '6mo'].map(period => opened('1d', period))).toEqual(['5y', '5y']);
    expect(opened('1mo', '1y')).toBe('5y');
    // The ranges an interval serves are kept as saved.
    expect(['5y', 'max'].map(period => opened('1d', period))).toEqual(['5y', 'max']);
    expect(opened('1h', '6mo')).toBe('6mo');
    // Less history than was saved would reopen as some other view.
    for (const [interval, period] of [['1h', '5y'], ['15m', '6mo'], ['5m', 'max']]) {
      Object.assign(saved.panes[0], { interval, historyPeriod: period });
      expect(() => validateReferenceWorkspace(saved), `${interval} ${period}`).toThrow(/unavailable at this interval/);
    }
  });

  it('keeps legacy volume visibility when a partial settings object does not repeat it', () => {
    const source = layout(); delete source.volumeSettings['volume.visible'];
    expect(workspaceFromLayout(source).panes[0].volume).toBe(false);
  });

  it.each([18.01, 33.333333333333, 42.857142857142854, 77.99])('keeps fractional split widths stable across repeated saves (%s)', width => {
    const source = layout(); source.secondary.width = width;
    const saved = workspaceFromLayout(source);
    expect(workspaceFromLayout(layoutFromWorkspace(saved))).toEqual(saved);
  });

  it.each([
    pane => { pane.interval = '2m'; },
    pane => { pane.historyPeriod = '2y'; },
    pane => { pane.historyPeriod = '1y'; pane.interval = '5m'; },
    pane => { pane.chartType = 'unavailable'; },
    pane => { pane.chart.timezone = 'Unknown/Zone'; },
    pane => { pane.exchange = 'unsupported-exchange'; },
    pane => { pane.comparisons[0].exchange = 'unsupported-exchange'; },
    pane => { for (const key of transformKeys(pane.settings)) delete pane.settings[key]; pane.settings['reference.pfmode'] = 'unknown'; },
    pane => { pane.settings['reference.transform.point-figure.mode'] = 'cubic'; },
    pane => { pane.settings['reference.transform.point-figure.reversal'] = 0; },
    pane => { pane.settings['reference.transform.renko.reversal'] = 3; },
    pane => { pane.settings['reference.transform.kagi.reversal'] = 2; },
    pane => { pane.settings['reference.transform.__proto__.mode'] = 'fixed'; },
    pane => { pane.settings['reference.compareMode'] = 'unknown'; },
    pane => { pane.settings['reference.futureOption'] = true; },
    pane => { pane.settings['volume.maPeriod'] = 0; },
  ])('rejects unsupported source or host settings before restoration', change => {
    const saved = workspaceFromLayout(layout()); change(saved.panes[0]);
    expect(() => validateReferenceWorkspace(saved)).toThrow();
  });

  it('rejects layouts whose shared drawing rail or comparison sources cannot be represented honestly', () => {
    const saved = workspaceFromLayout(layout());
    saved.panes[1].magnet = 'weak';
    expect(() => validateReferenceWorkspace(saved)).toThrow(/shared.*rail/i);
    saved.panes[1].magnet = saved.panes[0].magnet;
    saved.panes[0].comparisons.push({ ...saved.panes[0].comparisons[0], id: 'duplicate', symbol: 'msft' });
    expect(() => validateReferenceWorkspace(saved)).toThrow(/duplicate.*comparison/i);
  });
});
