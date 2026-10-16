import { describe, expect, it, vi } from 'vitest';
import {
  migrateWidgetWorkspace, parseIndicatorTemplate, parseWorkspaceDocument, parseWorkspacePayload,
  WorkspaceDocumentError,
} from '../src/workspace/index';
import type { WorkspaceLinkChannels, WorkspaceLinkGroup, WorkspacePayload, WorkspaceSync } from '../src/workspace/documents';
import { workspaceFixture } from './helpers/workspace-fixture';
import { Chart } from '../src/core/chart';
import { createLinkGroup, type LinkOptions } from '../src/index';
import { fakeDocument } from './helpers/fake-dom';

const template = () => ({
  kind: 'indicator-template', version: 1, id: 'study-set', name: 'Trend', createdAt: 1000, updatedAt: 2000,
  indicators: workspaceFixture().panes[0].chart.indicators,
});

describe('workspace documents', () => {
  it('retains optional appearance sync and rejects invalid values', () => {
    const fixture = workspaceFixture();
    const input = { ...fixture, sync: { ...fixture.sync, appearance: true } };
    expect(parseWorkspaceDocument(input).sync).toEqual(input.sync);
    expect(() => parseWorkspaceDocument({ ...input, sync: { ...input.sync, appearance: 'yes' } })).toThrow();
  });
  it('preserves the full state emitted by an actual chart, including its settings and timezone', () => {
    const doc = fakeDocument();
    const chart = new Chart(doc.createElement('div'), { document: doc, shortcuts: false, raf: { schedule: () => 0 } });
    try {
      chart.applySize(800, 600);
      chart.addSeries('candlestick');
      chart.setTimezone('America/New_York');
      chart.setPriceScaleOptions({ mode: 'logarithmic' });
      const state = chart.getState();
      const input = workspaceFixture();
      const saved = parseWorkspaceDocument({ ...input, panes: [{ ...input.panes[0], chart: state }, input.panes[1]] });
      expect(saved.panes[0].chart).toEqual(state);
    } finally { chart.destroy(); }
  });

  it('round-trips independent panes, grid, settings, drawings and comparisons', () => {
    const input = workspaceFixture();
    const saved = parseWorkspaceDocument(JSON.stringify(input));
    expect(saved).toEqual(input);
    expect(saved.panes.map(p => p.interval)).toEqual(['5m', '1h']);
    input.panes[0].chart.indicators[0].settings.period = 999;
    expect(saved.panes[0].chart.indicators![0].settings.period).toBe(9);
    expect(parseWorkspacePayload(saved).panes).toEqual(saved.panes);
  });

  it('retains unequal grid tracks as detached portable weights', () => {
    const fixture = workspaceFixture();
    const input = { ...fixture, layout: { ...fixture.layout, rowWeights: [1], columnWeights: [1.4, 1] } };
    const saved = parseWorkspaceDocument(JSON.stringify(input));
    expect(saved.layout).toEqual(input.layout);
    const detached = parseWorkspacePayload(input);
    input.layout.columnWeights[0] = 9;
    input.layout.rowWeights[0] = 4;
    expect(detached.layout.columnWeights).toEqual([1.4, 1]);
    expect(detached.layout.rowWeights).toEqual([1]);
    const legacy = parseWorkspaceDocument(fixture);
    expect(legacy.layout).not.toHaveProperty('rowWeights');
    expect(legacy.layout).not.toHaveProperty('columnWeights');
  });

  it.each([
    { rowWeights: [] }, { rowWeights: [1, 2] }, { columnWeights: [1] },
    { columnWeights: [0, 1] }, { columnWeights: [-1, 1] },
    { columnWeights: [NaN, 1] }, { columnWeights: [Infinity, 1] },
    { columnWeights: [1001, 1] }, { columnWeights: ['2', 1] },
  ])('rejects invalid grid track weights: %j', (weights) => {
    const fixture = workspaceFixture();
    expect(() => parseWorkspaceDocument({ ...fixture, layout: { ...fixture.layout, ...weights } }))
      .toThrow(WorkspaceDocumentError);
  });

  it('projects configuration and drops nested credentials and execution state', () => {
    const input = workspaceFixture();
    Object.assign(input, { apiKey: 'secret-value', armed: true, orders: [{ id: 'live' }], unknown: 'ignored' });
    Object.assign(input.panes[0].chart.indicators[0].settings, {
      credentials: { token: 'secret-value' }, 'api_key': 'secret-value', accessToken: 'secret-value',
    });
    Object.assign(input.panes[0].chart.drawings.drawings[0], { positions: [{ account: 'secret-value' }] });
    Object.assign(input.panes[0].chart, { data: [{ close: 500 }], accountBalance: 999 });
    const text = JSON.stringify(parseWorkspaceDocument(input));
    expect(text).not.toMatch(/secret-value|armed|orders|positions|accountBalance|unknown|"data"/);
    expect(text).toContain('line1');
  });

  it('does not execute accessors and rejects non-JSON values and cycles', () => {
    const accessor = vi.fn(() => 'unsafe');
    const input = workspaceFixture();
    Object.defineProperty(input, 'extra', { enumerable: true, get: accessor });
    expect(() => parseWorkspaceDocument(input)).toThrow(WorkspaceDocumentError);
    expect(accessor).not.toHaveBeenCalled();
    for (const bad of [() => 1, NaN, Infinity, new Date(), undefined, 1n]) {
      expect(() => parseWorkspaceDocument({ ...workspaceFixture(), extra: bad })).toThrow(WorkspaceDocumentError);
    }
    const cyclic: Record<string, unknown> = workspaceFixture();
    cyclic.cycle = cyclic;
    expect(() => parseWorkspaceDocument(cyclic)).toThrow(/cycle/i);
  });

  it('discards prototype keys without polluting any returned object', () => {
    const input = JSON.parse(JSON.stringify(workspaceFixture()));
    input.panes[0].settings = JSON.parse('{"__proto__":{"polluted":true},"constructor":{"prototype":{"polluted":true}},"volume.showMA":true}');
    const saved = parseWorkspaceDocument(input);
    expect(saved.panes[0].settings).toEqual({ 'volume.showMA': true });
    expect(Object.getPrototypeOf(saved.panes[0].settings)).toBe(Object.prototype);
    expect('polluted' in {}).toBe(false);
  });

  it.each([
    ['future schema', { version: 99 }], ['wrong kind', { kind: 'orders' }],
    ['blank name', { name: '   ' }], ['long name', { name: 'x'.repeat(121) }],
    ['invalid clock', { updatedAt: -1 }], ['missing focused pane', { activePaneId: 'absent' }],
    ['empty workspace', { panes: [] }],
    ['invalid dimension', { layout: { ...workspaceFixture().layout, rows: 0 } }],
    ['fractional dimension', { layout: { ...workspaceFixture().layout, rows: 1.5 } }],
    ['invalid sync', { sync: { ...workspaceFixture().sync, interval: 'yes' } }],
  ])('rejects %s', (_name, patch) => {
    expect(() => parseWorkspaceDocument({ ...workspaceFixture(), ...patch })).toThrow(WorkspaceDocumentError);
  });

  it('rejects duplicate pane identities, invalid slots, overlaps and missing slots', () => {
    const input = workspaceFixture();
    const slots = input.layout.slots;
    const badSlots = [
      [slots[0]], [slots[0], { ...slots[1], column: 0 }],
      [slots[0], { ...slots[1], columnSpan: 2 }],
      [slots[0], { ...slots[1], paneId: 'unknown' }], [slots[0], slots[0]],
    ];
    for (const next of badSlots) {
      expect(() => parseWorkspaceDocument({ ...input, layout: { ...input.layout, slots: next } })).toThrow();
    }
    expect(() => parseWorkspaceDocument({ ...input, panes: [input.panes[0], input.panes[0]] })).toThrow();
  });

  it('rejects unsupported chart versions and malformed indicator/scale state', () => {
    for (const chart of [
      { version: 99 }, { version: 1, indicators: [{}] }, { version: 1, viewport: { from: 10, to: 1 } },
      { version: 1, panes: [{ weight: -1 }] }, { version: 1, drawings: 'not a drawing document' },
    ]) {
      const input = workspaceFixture();
      expect(() => parseWorkspaceDocument({ ...input, panes: [{ ...input.panes[0], chart }, input.panes[1]] })).toThrow();
    }
  });

  it('bounds depth, total nodes and serialized size before accepting imports', () => {
    let deep: unknown = {};
    for (let i = 0; i < 40; i++) deep = { next: deep };
    expect(() => parseWorkspaceDocument({ ...workspaceFixture(), deep })).toThrow(/depth/i);
    expect(() => parseWorkspaceDocument({ ...workspaceFixture(), huge: Array(100001).fill(1) })).toThrow(/limit/i);
    expect(() => parseWorkspaceDocument(' '.repeat(5 * 1024 * 1024 + 1))).toThrow(/limit/i);
    expect(() => parseWorkspaceDocument({ ...workspaceFixture(), text: 'x'.repeat(5 * 1024 * 1024) })).toThrow(/limit/i);
  });

  it('migrates the existing widget envelope without changing or executing its source', () => {
    const source = { version: 1, symbol: 'BHEL', exchange: 'NSE', interval: '5m', chartType: 'candlestick',
      theme: 'light', chart: workspaceFixture().panes[0].chart,
      rail: { favorites: [], magnet: 'strong', stay: true, last: {} }, armed: true,
    };
    const saved = migrateWidgetWorkspace(source, { id: 'migrated', name: 'Previous chart', now: 5000 });
    expect(saved.activePaneId).toBe('p0');
    expect(saved.layout.slots).toHaveLength(1);
    expect(saved.panes[0]).toMatchObject({ symbol: 'BHEL', interval: '5m', magnet: 'strong', stay: true, settings: { 'widget.theme': 'light' } });
    expect(saved.panes[0].chart).toEqual(source.chart);
    expect(source.armed).toBe(true);
    expect(JSON.stringify(saved)).not.toContain('armed');
    expect(() => migrateWidgetWorkspace({ version: 2 }, { id: 'x', name: 'Old', now: 0 })).toThrow();
  });
});

/**
 * A workspace exactly as the 2.5.9 chart grid saved it: two charts on a split
 * desk with a study, a drawing each and appearance linking on. Captured by
 * running the v2.5.9 sources (`createChartGrid(...).getWorkspace()` wrapped in
 * document metadata and passed through that release's `parseWorkspaceDocument`),
 * with each drawing computed from the random-walk bars its chart held. Kept as
 * text because text is what a store hands back.
 */
const SAVED_BY_2_5_9 = [
  '{"kind":"workspace","version":1,"id":"desk-259","name":"Morning desk","createdAt":1758771900000,',
  '"updatedAt":1758772200000,"layout":{"rows":1,"columns":2,"slots":[{"paneId":"p0","row":0,"column":0,"rowSpan":1,',
  '"columnSpan":1},{"paneId":"p1","row":0,"column":1,"rowSpan":1,"columnSpan":1}],"preset":"1x2","rowWeights":[1],',
  '"columnWeights":[1,1]},"panes":[{"id":"p0","symbol":"INFY","exchange":"NSE","interval":"5m",',
  '"chartType":"candlestick","chart":{"version":1,"timezone":"Asia/Kolkata","navigation":{"mousePan":"both",',
  '"defaultVisibleBars":0,"panEnabled":true,"zoomEnabled":true,"defaultBarSpacing":8},"canvas":{},"statusLine":{},',
  '"watermark":{"visible":false,"text":"","color":"#9aa4b2","opacity":0.08,"fontSize":64},"trading":{},"events":{},',
  '"axisChrome":{"sessionClock":false,"barCountdown":false},"viewport":{"from":55,"to":123},"barSpacing":8,',
  '"grid":{"vertLines":true,"horzLines":true},"crosshairMode":"normal","crosshairSnapToBar":false,',
  '"priceOnlyAutoScale":false,"indicatorLegendCollapsed":false,"indicators":[{"indicatorId":"ema",',
  '"settings":{"length":20,"source":"close","color":"#f5a623","ma:opacity":100,"ma:width":1.5,',
  '"ma:lineStyle":"solid","ma:type":"line"},"paneIndex":0,"visible":true,"instanceId":"ema-1"}],',
  '"alerts":{"version":1,"alerts":[]},"drawings":{"version":2,"drawings":[{"tool":"trend-line",',
  '"points":[{"time":1758789600,"price":1481.62},{"time":1758807000,"price":1580.41}],"paneIndex":0,',
  '"style":{"extendLeft":false,"extendRight":false},"id":"d1","zIndex":0,"createdAt":1790666895042}]},',
  '"panes":[{"weight":1,"priceScale":{"marginTop":0.1,"marginBottom":0.1,"minMove":0,"mode":"linear",',
  '"inverted":false,"autoScale":true,"minPrecision":0,"fixedRange":null,"placement":{"side":"right","order":0}}}],',
  '"series":[{"type":"candlestick","style":{},"paneIndex":0,"priceScaleId":"right"},{"type":"line",',
  '"style":{"lineWidth":1.5,"color":"#f5a623","title":"EMA","visible":true,"lineStyle":"solid"},"paneIndex":0,',
  '"priceScaleId":"right"}]},"settings":{"widget.theme":"dark"},"volume":false,"magnet":"off","stay":false,',
  '"comparisons":[],"comparisonMode":"percent"},{"id":"p1","symbol":"RELIANCE","exchange":"NSE","interval":"5m",',
  '"chartType":"candlestick","chart":{"version":1,"timezone":"Asia/Kolkata","navigation":{"mousePan":"both",',
  '"defaultVisibleBars":0,"panEnabled":true,"zoomEnabled":true,"defaultBarSpacing":8},"canvas":{},"statusLine":{},',
  '"watermark":{"visible":false,"text":"","color":"#9aa4b2","opacity":0.08,"fontSize":64},"trading":{},"events":{},',
  '"axisChrome":{"sessionClock":false,"barCountdown":false},"viewport":{"from":55,"to":123},"barSpacing":8,',
  '"grid":{"vertLines":true,"horzLines":true},"crosshairMode":"normal","crosshairSnapToBar":false,',
  '"priceOnlyAutoScale":false,"indicatorLegendCollapsed":false,"indicators":[],"alerts":{"version":1,"alerts":[]},',
  '"drawings":{"version":2,"drawings":[{"tool":"horizontal-line","points":[{"time":1758799500,"price":3002.34}],',
  '"paneIndex":0,"style":{"showLabels":true},"id":"d2","zIndex":0,"createdAt":1790666895045}]},',
  '"panes":[{"weight":1,"priceScale":{"marginTop":0.1,"marginBottom":0.1,"minMove":0,"mode":"linear",',
  '"inverted":false,"autoScale":true,"minPrecision":0,"fixedRange":null,"placement":{"side":"right","order":0}}}],',
  '"series":[{"type":"candlestick","style":{},"paneIndex":0,"priceScaleId":"right"}]},',
  '"settings":{"widget.theme":"dark"},"volume":false,"magnet":"off","stay":false,"comparisons":[],',
  '"comparisonMode":"percent"}],"activePaneId":"p1","sync":{"crosshair":true,"viewport":true,"symbol":false,',
  '"interval":false,"appearance":true}}',
].join('');

/** A desk of three charts in two named groups and one chart in none. */
function groupedDesk() {
  const fixture = workspaceFixture();
  const third = { ...fixture.panes[1], id: 'p2', symbol: 'SBIN' };
  return {
    ...fixture,
    layout: { rows: 1, columns: 3, slots: [
      ...fixture.layout.slots, { paneId: 'p2', row: 0, column: 2, rowSpan: 1, columnSpan: 1 },
    ] },
    panes: [{ ...fixture.panes[0], linkGroup: 'a' }, { ...fixture.panes[1], linkGroup: 'b' }, third] as
      Array<(typeof fixture.panes)[number] & { linkGroup?: string }>,
    sync: {
      crosshair: false, viewport: false, symbol: false, interval: false,
      groups: [
        { id: 'a', name: 'Intraday', crosshair: true, viewport: true, symbol: true, interval: false,
          chartType: true, drawings: true, whenMissing: 'hide' },
        { id: 'b', name: 'Swing', crosshair: true, viewport: false, symbol: false, interval: true, appearance: true },
        { id: 'c', name: 'Spare', crosshair: false, viewport: false, symbol: false, interval: false },
      ],
    },
  };
}

describe('workspace link channels and groups', () => {
  it('reads a workspace saved by 2.5.9 unchanged, and writes it back byte for byte', () => {
    const document = parseWorkspaceDocument(SAVED_BY_2_5_9);
    expect(document).toEqual(JSON.parse(SAVED_BY_2_5_9));
    expect(JSON.stringify(document)).toBe(SAVED_BY_2_5_9);
    expect(document.sync).not.toHaveProperty('groups');
    expect(document.sync).not.toHaveProperty('chartType');
    expect(document.sync).not.toHaveProperty('drawings');
    expect(document.sync).not.toHaveProperty('whenMissing');
    for (const pane of document.panes) expect(pane).not.toHaveProperty('linkGroup');
    const payload = parseWorkspacePayload(SAVED_BY_2_5_9);
    expect(parseWorkspacePayload(JSON.stringify(payload))).toEqual(payload);
  });

  it('keeps the four channel flags a host has always written, with nothing added', () => {
    const fixture = workspaceFixture();
    // Typed the way a host that builds `sync` itself types it; `tsc` holds the line.
    const sync: WorkspacePayload['sync'] = { crosshair: false, viewport: true, symbol: true, interval: false };
    const parsed = parseWorkspacePayload({ ...fixture, sync });
    expect(parsed.sync).toEqual(sync);
    expect(Object.keys(parsed.sync)).toEqual(['crosshair', 'viewport', 'symbol', 'interval']);
    // A host that wrote no sync at all still reads as the engine's defaults.
    const { sync: _omitted, ...bare } = fixture;
    expect(parseWorkspacePayload(bare).sync).toEqual({ crosshair: true, viewport: true, symbol: false, interval: false });
  });

  it('round-trips the chart type, drawings and missing-bar channels of the one desk group', () => {
    const fixture = workspaceFixture();
    const sync: WorkspaceSync = { ...fixture.sync, appearance: false, chartType: true, drawings: true, whenMissing: 'hide' };
    const parsed = parseWorkspaceDocument({ ...fixture, sync });
    expect(parsed.sync).toEqual(sync);
    expect(parseWorkspaceDocument(JSON.stringify(parsed))).toEqual(parsed);
  });

  it('round-trips named groups, a chart in none, and a group with no chart yet', () => {
    const input = groupedDesk();
    const parsed = parseWorkspaceDocument(input);
    expect(parsed.sync).toEqual(input.sync);
    expect(parsed.panes.map(pane => pane.linkGroup)).toEqual(['a', 'b', undefined]);
    expect(parsed.panes[2]).not.toHaveProperty('linkGroup');
    expect(parseWorkspaceDocument(JSON.stringify(parsed))).toEqual(parsed);
    // Detached: the parsed groups are not the caller's objects.
    input.sync.groups[0].symbol = false;
    input.sync.groups[0].name = 'Changed';
    expect(parsed.sync.groups?.[0]).toMatchObject({ symbol: true, name: 'Intraday' });
  });

  it('reads a group\'s absent flags as the engine defaults and drops what is not a channel', () => {
    const input = groupedDesk();
    Object.assign(input.sync.groups[2], { color: '#ff0000' });
    delete (input.sync.groups[2] as Partial<WorkspaceLinkGroup>).crosshair;
    delete (input.sync.groups[2] as Partial<WorkspaceLinkGroup>).viewport;
    const [, , spare] = parseWorkspacePayload(input).sync.groups!;
    expect(spare).toEqual({ id: 'c', name: 'Spare', crosshair: true, viewport: true, symbol: false, interval: false });
  });

  it('describes each group in the same terms the engine takes, so a group opens as a link group', () => {
    const parsed = parseWorkspacePayload(groupedDesk());
    const { id: _id, name: _name, ...channels } = parsed.sync.groups![0];
    const options: LinkOptions = channels satisfies WorkspaceLinkChannels;
    const group = createLinkGroup(options);
    expect(group.options()).toEqual({
      crosshair: true, viewport: true, symbol: true, interval: false, chartType: true,
      appearance: false, drawings: true, whenMissing: 'hide',
    });
    group.destroy();
  });

  it.each([
    ['a chart type flag that is not a boolean', { chartType: 'yes' }],
    ['a drawings flag that is not a boolean', { drawings: 1 }],
    ['an unknown missing-bar policy', { whenMissing: 'skip' }],
    ['groups that are not a list', { groups: {} }],
    ['more groups than a desk has charts', { groups: Array.from({ length: 17 }, (_, i) => ({ id: `g${i}`, name: `G${i}` })) }],
  ])('rejects %s in sync', (_name, patch) => {
    const fixture = workspaceFixture();
    expect(() => parseWorkspaceDocument({ ...fixture, sync: { ...fixture.sync, ...patch } })).toThrow(WorkspaceDocumentError);
  });

  it.each([
    ['a blank id', (d: ReturnType<typeof groupedDesk>) => { d.sync.groups[0].id = '  '; }],
    ['an id over 100 characters', (d: ReturnType<typeof groupedDesk>) => { d.sync.groups[2].id = 'x'.repeat(101); }],
    ['a duplicate id', (d: ReturnType<typeof groupedDesk>) => { d.sync.groups[1].id = 'a'; }],
    ['a blank name', (d: ReturnType<typeof groupedDesk>) => { d.sync.groups[0].name = ''; }],
    ['a name over 120 characters', (d: ReturnType<typeof groupedDesk>) => { d.sync.groups[0].name = 'n'.repeat(121); }],
    ['a channel flag that is not a boolean', (d: ReturnType<typeof groupedDesk>) => {
      (d.sync.groups[1] as unknown as Record<string, unknown>).interval = 'on';
    }],
    ['a group that is not a record', (d: ReturnType<typeof groupedDesk>) => {
      (d.sync.groups as unknown[])[2] = 'Spare';
    }],
    ['a chart naming a group the desk does not declare', (d: ReturnType<typeof groupedDesk>) => { d.panes[1].linkGroup = 'z'; }],
    ['a chart naming a group while the desk declares none', (d: ReturnType<typeof groupedDesk>) => {
      delete (d.sync as { groups?: unknown }).groups;
    }],
    ['a group reference that is not a string', (d: ReturnType<typeof groupedDesk>) => {
      (d.panes[0] as unknown as Record<string, unknown>).linkGroup = 1;
    }],
  ])('rejects %s', (_name, spoil) => {
    const input = groupedDesk();
    spoil(input);
    expect(() => parseWorkspaceDocument(input)).toThrow(WorkspaceDocumentError);
  });
});

describe('indicator template documents', () => {
  it('retains duplicate instances, plot styles, visibility and custom descriptor identities', () => {
    const input = template();
    input.indicators.push({ ...input.indicators[0], indicatorId: 'custom-study', paneIndex: 1 });
    const parsed = parseIndicatorTemplate(input);
    expect(parsed.indicators).toEqual(input.indicators);
    input.indicators[0].settings.period = 500;
    expect(parsed.indicators[0].settings.period).toBe(9);
  });

  it('accepts an intentionally empty template and trims its name', () => {
    expect(parseIndicatorTemplate({ ...template(), indicators: [], name: '  Clear studies  ' }))
      .toMatchObject({ indicators: [], name: 'Clear studies' });
  });

  it.each([
    [{ indicatorId: '', settings: {}, paneIndex: 0 }],
    [{ indicatorId: 'ema', settings: [], paneIndex: 0 }],
    [{ indicatorId: 'ema', settings: {}, paneIndex: -1 }],
    [{ indicatorId: 'ema', settings: {}, paneIndex: 0, visible: 'yes' }],
    Array(257).fill({ indicatorId: 'ema', settings: {}, paneIndex: 0 }),
  ])('rejects malformed or oversized indicator arrays', (...entries) => {
    expect(() => parseIndicatorTemplate({ ...template(), indicators: entries })).toThrow();
  });
});
