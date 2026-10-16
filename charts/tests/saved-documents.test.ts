/**
 * The compatibility gate, second half: what earlier releases saved still
 * loads, and saving it again changes only what is named here, each with the
 * reason. The documents in tests/fixtures/saved-documents/<version>/ were
 * written by that release as published, in a real browser, through its public
 * API (scripts/generate-saved-documents.mjs): a chart state with its studies,
 * drawings and alerts, the drawings and alert documents on their own, the
 * widget's persisted layout and its `getState`, and a workspace with the
 * catalog the repository stored it in. A change a host would not expect,
 * a field lost or a value rewritten, fails here; so does a named change that
 * no longer happens, so the list stays exact.
 */
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import '../src/indicators/index';
import { AlertController, Chart, type Bar } from '../src/index';
import { DrawingController } from '../src/draw/index';
import { createWidget, type StorageLike, type Widget } from '../src/widget/index';
import {
  WorkspaceRepository, parseWorkspaceCatalog, parseWorkspaceDocument,
  type WorkspaceCatalog, type WorkspaceStorage,
} from '../src/workspace/index';
import { BASELINES } from '../scripts/compat-packages.mjs';
import { fakeDocument } from './helpers/fake-dom';
import { ensureWindowGlobal, fakeContainer, fakeWidgetDocument, type FakeElement } from './helpers/fake-dom-widget';

type Json = unknown;
/** `import.meta.glob`, typed; the suite carries no Vite client globals. */
type Glob = { glob(pattern: string, options: { import: string; eager: true }): Record<string, Json> };
const FILES = (import.meta as unknown as Glob).glob('./fixtures/saved-documents/**/*.json', { import: 'default', eager: true });
const at = (path: string): Json => {
  const doc = FILES[`./fixtures/saved-documents/${path}.json`];
  if (doc === undefined) throw new Error(`no fixture ${path}.json`);
  return structuredClone(doc);
};
const VERSIONS = [...new Set(Object.keys(FILES).map((f) => f.split('/')[3]).filter((v): v is string => /^\d+\.\d+\.\d+$/.test(v ?? '')))];
const BARS = at('bars') as { primary: Bar[]; second: Bar[] };
/** The page's fixed clock: 2026-09-10 12:02 IST. */
const NOW_MS = Date.UTC(2026, 8, 10, 6, 32);
const NOW = Math.floor(NOW_MS / 1000);

// ---------------------------------------------------------------------------
// What may change when a document is loaded and saved again, and why.

interface Change { path: string; change: 'added' | 'removed' | 'changed' }
interface Named { path: string; change: Change['change']; why: string }

const isRecord = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v);

/** Every difference between two JSON values, at the shallowest path where it starts. */
function changes(before: Json, after: Json, path: string[] = []): Change[] {
  const here = path.join('.');
  if (Object.is(before, after)) return [];
  if (before === undefined) return [{ path: here, change: 'added' }];
  if (after === undefined) return [{ path: here, change: 'removed' }];
  if (Array.isArray(before) && Array.isArray(after)) {
    const out: Change[] = [];
    for (let i = 0; i < Math.max(before.length, after.length); i++) out.push(...changes(before[i], after[i], [...path, String(i)]));
    return out;
  }
  if (isRecord(before) && isRecord(after)) {
    const keys = [...new Set([...Object.keys(before), ...Object.keys(after)])];
    return keys.flatMap((key) => changes(before[key], after[key], [...path, key]));
  }
  return [{ path: here, change: 'changed' }];
}

/** `*` stands for one segment of the path, `**` for any number. */
function matches(pattern: string, path: string): boolean {
  const p = pattern.split('.');
  const s = path.split('.');
  const walk = (i: number, j: number): boolean => {
    if (i === p.length) return j === s.length;
    if (p[i] === '**') return j <= s.length && (walk(i + 1, j) || (j < s.length && walk(i, j + 1)));
    return j < s.length && (p[i] === '*' || p[i] === s[j]) && walk(i + 1, j + 1);
  };
  return walk(0, 0);
}

/** Only the named changes happened, and every named change happened. */
function expectOnlyNamed(before: Json, after: Json, named: readonly Named[]): void {
  const found = changes(before, after);
  const unnamed = found.filter((c) => !named.some((n) => n.change === c.change && matches(n.path, c.path)));
  const stale = named.filter((n) => !found.some((c) => n.change === c.change && matches(n.path, c.path)));
  expect(unnamed.map((c) => `${c.change} ${c.path}`), 'a change no one named').toEqual([]);
  expect(stale.map((n) => `${n.change} ${n.path}: ${n.why}`), 'a named change that no longer happens').toEqual([]);
}

/** The same changes one level down, inside a document that holds a chart state. */
const under = (prefix: string, list: readonly Named[]): Named[] => list.map((n) => ({ ...n, path: `${prefix}.${n.path}` }));

/**
 * Fields a chart state has saved since 2.5.4, each written on save with the
 * value a 2.5.1 chart had. `scripts/generate-saved-documents.mjs --self` shows
 * 2.5.1 does not add them to its own documents; 2.6.0 does not change them.
 */
const SAVED_SINCE_254: readonly Named[] = [
  { path: 'navigation.panEnabled', change: 'added', why: 'the pan switch (2.5.4), on, as a 2.5.1 chart pans' },
  { path: 'navigation.zoomEnabled', change: 'added', why: 'the zoom switch (2.5.4), on, as a 2.5.1 chart zooms' },
  { path: 'panes.*.priceScale.minPrecision', change: 'added', why: 'the scale precision floor (2.5.4), which an older state left to the scale it landed on' },
  { path: 'panes.*.priceScale.fixedRange', change: 'added', why: 'the declared auto-fit band (2.5.4), null where the scale has none' },
  { path: 'panes.*.priceScale.placement', change: 'added', why: 'the axis side and order (2.5.4), the default placement a 2.5.1 axis had' },
  { path: 'panes.1.priceScale.indicatorRange', change: 'added', why: 'who owns the RSI pane\'s fixed range (2.5.4): the study, not a range the user pinned' },
  { path: 'priceOnlyAutoScale', change: 'added', why: 'the auto-fit preference (2.5.4), at its default' },
  { path: 'indicatorLegendCollapsed', change: 'added', why: 'the study legend preference (2.5.4), at its default' },
];
/** 2.6.0's study timeframe input, a7922a74: empty is the chart's own interval, the only one a study computed on before. */
const TIMEFRAME: Named = { path: 'indicators.*.settings.timeframe', change: 'added', why: 'the study timeframe input (2.6.0), empty, the chart\'s own interval' };
/** Restoring applies the saved `grid`, which the chart mirrors whole into its canvas options. 2.5.1 and 2.6.0 do the same to their own documents (`--self`). */
const GRID_MIRROR = 'restoring the saved grid mirrors it whole into the canvas options, as 2.5.1 and 2.6.0 do on their own documents';
/** The unit tests' fake DOM lays the widget out at another plot width than the browser that wrote the layout. */
const PLOT_WIDTH = 'bar spacing is the saved view in pixels per bar, and the fake DOM\'s plot is narrower than the browser\'s; the view itself round-trips';
/** The widget's own reads and writes on start, the same in 2.5.1 and 2.6.0 (`--self`). */
const WIDGET_START: readonly Named[] = [
  { path: 'oac-widget:compat:state.chart.viewport.from', change: 'changed', why: 'a widget whose host sets its bars itself has no load for the saved view to wait for, so it keeps the default view, as 2.5.1 and 2.6.0 do' },
  { path: 'oac-widget:compat:state.chart.viewport.to', change: 'changed', why: 'as viewport.from' },
  { path: 'oac-widget:compat:state.chart.barSpacing', change: 'changed', why: 'as viewport.from' },
  { path: 'oac-widget:compat:state.chart.canvas.grid', change: 'added', why: GRID_MIRROR },
  { path: 'oac-widget:compat:rail', change: 'added', why: 'the rail writes the preferences it restored under their own key, as 2.5.1 and 2.6.0 do' },
];
/** 2.6.3 stamps a widget state with the version that wrote it, which tells its restore a drag was chosen rather than recorded by default. */
const SAVED_BY = 'the writer\'s version (2.6.3), which tells a later restore that a recorded drag was chosen, not the old default';
/** An unstamped widget state recorded the engine's default drag, so the widget restores its own (2.6.3). */
const DRAG: Named = { path: 'chart.navigation.mousePan', change: 'changed', why: 'every state before 2.6.3 recorded the default \'both\', chosen or not, so an unstamped one restores with the widget\'s own drag, \'horizontal\'' };
/** What `openWorkspace`, the write this test makes, changes in any catalog. */
const OPENED: readonly Named[] = [
  { path: 'revision', change: 'changed', why: 'every committed change moves the catalog one revision on' },
  { path: 'activeWorkspaceId', change: 'changed', why: 'opening a layout makes it the active one' },
  { path: 'recentWorkspaceIds.0', change: 'added', why: 'opening a layout puts it at the head of the recent list' },
];

/** The named changes for one document, by the release that wrote it. A release not listed may change nothing. */
const CHANGES: Record<string, Record<string, readonly Named[]>> = {
  'chart-state': {
    '2.5.1': [...SAVED_SINCE_254, TIMEFRAME, { path: 'canvas.grid.horzLines', change: 'added', why: GRID_MIRROR }],
    '2.6.0': [{ path: 'canvas.grid.horzLines', change: 'added', why: GRID_MIRROR }],
  },
  'widget-state': {
    '2.5.1': [
      ...under('chart', [...SAVED_SINCE_254, TIMEFRAME]),
      { path: 'chart.canvas.grid', change: 'added', why: GRID_MIRROR },
      { path: 'chart.barSpacing', change: 'changed', why: PLOT_WIDTH },
      { path: 'panels', change: 'added', why: 'the panel dock (2.5.3), closed, as a 2.5.1 widget had none' },
      { path: 'savedBy', change: 'added', why: SAVED_BY },
      DRAG,
    ],
    '2.6.0': [
      { path: 'chart.canvas.grid', change: 'added', why: GRID_MIRROR },
      { path: 'chart.barSpacing', change: 'changed', why: PLOT_WIDTH },
      { path: 'savedBy', change: 'added', why: SAVED_BY },
      DRAG,
    ],
  },
  'widget-storage': {
    '2.5.1': [
      ...WIDGET_START,
      ...under('oac-widget:compat:state.chart', [...SAVED_SINCE_254, TIMEFRAME]),
      { path: 'oac-widget:compat:state.panels', change: 'added', why: 'the panel dock (2.5.3), closed, as a 2.5.1 widget had none' },
      { path: 'oac-widget:compat:state.savedBy', change: 'added', why: SAVED_BY },
      ...under('oac-widget:compat:state', [DRAG]),
      { path: 'oac-widget:compat:drawings:NSE:RELIANCE', change: 'added', why: 'drawings are kept per instrument since 2.5.9: the layout\'s own drawings are copied under the instrument it was saved on, and stay in the layout too' },
    ],
    '2.6.0': [...WIDGET_START, { path: 'oac-widget:compat:state.savedBy', change: 'added', why: SAVED_BY }, ...under('oac-widget:compat:state', [DRAG])],
  },
  'workspace-catalog': { '2.5.1': OPENED, '2.6.0': OPENED },
};
const named = (doc: string, version: string): readonly Named[] => CHANGES[doc]?.[version] ?? [];

// ---------------------------------------------------------------------------
// Hosts, built the way the page built them.

function makeChart(): Chart {
  const chart = new Chart(fakeDocument().createElement('div'), {
    document: fakeDocument(),
    pixelRatio: () => 1,
    shortcuts: false,
    raf: { schedule: (cb: () => void) => { cb(); return 1; }, cancel: () => {} },
  });
  chart.applySize(960, 600);
  chart.addSeries('candlestick').setData(BARS.primary);
  return chart;
}

function chartHost(): { chart: Chart; draw: DrawingController; alerts: AlertController } {
  const chart = makeChart();
  const draw = new DrawingController(chart);
  const alerts = new AlertController(chart, { drawings: draw, now: () => NOW });
  return { chart, draw, alerts };
}

class MemoryStorage implements StorageLike {
  public readonly map: Map<string, string>;
  public constructor(entries: Record<string, Json> = {}) {
    this.map = new Map(Object.entries(entries).map(([k, v]) => [k, JSON.stringify(v)]));
  }
  public getItem(k: string): string | null { return this.map.get(k) ?? null; }
  public setItem(k: string, v: string): void { this.map.set(k, v); }
  public removeItem(k: string): void { this.map.delete(k); }
  /** Not `entries`: a store with that method is taken for an asynchronous one. */
  public dump(): Record<string, Json> { return Object.fromEntries([...this.map].map(([k, v]) => [k, JSON.parse(v) as Json])); }
}

const widgets: Widget[] = [];
beforeAll(ensureWindowGlobal);
// The page's clock, for what reads the time itself (the widget's alerts,
// which expire an alert a week after the fixture was written).
beforeEach(() => { vi.useFakeTimers({ toFake: ['Date'], now: NOW_MS }); });
afterEach(() => {
  for (const w of widgets.splice(0)) if (!w.isDestroyed) w.destroy();
  vi.useRealTimers();
});

/** A widget on the instrument the page saved, so a layout lands on its own dataset and keeps its view. */
function makeWidget(storage: StorageLike, instrument: { symbol?: string; exchange?: string; interval?: string } = {}): Widget {
  const doc = fakeWidgetDocument();
  const widget = createWidget(fakeContainer(doc, 960, 600) as unknown as HTMLElement, {
    document: doc as unknown as Document,
    pixelRatio: () => 1,
    raf: { schedule: (cb: () => void) => { cb(); return 1; }, cancel: () => {} },
    mobile: 'never',
    persist: 'compat',
    storage,
    now: () => NOW_MS,
    ...instrument,
  });
  widget.chart.applySize(960, 600);
  (widget.root as unknown as FakeElement).rect = { left: 0, top: 0, width: 960, height: 600 };
  widgets.push(widget);
  return widget;
}

/** A workspace store over one catalog, checking revisions the way the contract asks. */
function catalogStorage(seed: Json = null): WorkspaceStorage & { stored(): Json } {
  let stored: Json = seed === null ? null : structuredClone(seed);
  return {
    stored: () => stored,
    read: async () => (stored === null ? null : structuredClone(stored)),
    write: async (_namespace: string, catalog: WorkspaceCatalog, expectedRevision: number) => {
      const current = isRecord(stored) && typeof stored.revision === 'number' ? stored.revision : 0;
      if (current !== expectedRevision) throw new Error(`revision ${current}, not ${expectedRevision}`);
      stored = structuredClone(catalog);
    },
  };
}

// ---------------------------------------------------------------------------

it('has documents from every release the gate compares against', () => {
  // A release added to BASELINES needs its documents: run scripts/generate-saved-documents.mjs.
  expect([...VERSIONS].sort()).toEqual(BASELINES.map((b) => b.version).sort());
});

describe.each(VERSIONS)('documents saved by %s', (version) => {
  it('chart state: restores its studies, drawings and alerts, and saves them again', () => {
    const golden = at(`${version}/chart-state`) as Record<string, unknown>;
    const { chart, draw, alerts } = chartHost();
    const report = chart.restoreState(golden);
    expect(report.applied, report.reason).toBe(true);
    expect(chart.indicators().length).toBe((golden.indicators as unknown[]).length);
    expect(draw.drawings().length).toBe(((golden.drawings as { drawings: unknown[] }).drawings).length);
    expect(alerts.list().length).toBe(((golden.alerts as { alerts: unknown[] }).alerts).length);
    expectOnlyNamed(golden, JSON.parse(JSON.stringify(chart.getState())), named('chart-state', version));
  });

  it('drawings document: loads every drawing and saves it again', () => {
    const golden = at(`${version}/drawings`) as { drawings: unknown[] };
    const { draw } = chartHost();
    draw.fromJSON(golden);
    expect(draw.drawings().length).toBe(golden.drawings.length);
    expectOnlyNamed(golden, JSON.parse(JSON.stringify(draw.toJSON())), named('drawings', version));
  });

  it('alert list: loads every alert onto the studies and drawings it watches, and saves it again', () => {
    const golden = at(`${version}/alerts`) as { alerts: unknown[] };
    const { chart, draw, alerts } = chartHost();
    // A host restores what the alerts watch first: an alert whose study or
    // drawing is missing is removed with an `alert:removed` event, by design.
    const state = at(`${version}/chart-state`) as { version: number; indicators: unknown[] };
    expect(chart.restoreState({ version: state.version, indicators: state.indicators }).applied).toBe(true);
    draw.fromJSON(at(`${version}/drawings`));
    alerts.fromJSON(golden);
    expect(alerts.list().length).toBe(golden.alerts.length);
    expectOnlyNamed(golden, JSON.parse(JSON.stringify(alerts.toJSON())), named('alerts', version));
  });

  it('widget layout: the persisted layout restores on start, and the widget saves it again', () => {
    const golden = at(`${version}/widget-storage`) as Record<string, Json>;
    const storage = new MemoryStorage(golden);
    const widget = makeWidget(storage);
    widget.series.setData(BARS.primary);
    const state = golden['oac-widget:compat:state'] as {
      symbol: string; interval: string; chart: { indicators: unknown[]; drawings: { drawings: unknown[] }; alerts: { alerts: unknown[] } };
    };
    expect([widget.symbol(), widget.interval()]).toEqual([state.symbol, state.interval]);
    expect(widget.chart.indicators().length).toBe(state.chart.indicators.length);
    expect(widget.draw.drawings().length).toBe(state.chart.drawings.drawings.length);
    expect(widget.alerts.list().length).toBe(state.chart.alerts.alerts.length);
    widget.destroy(); // writes the layout, as leaving the page does
    expectOnlyNamed(golden, storage.dump(), named('widget-storage', version));
  });

  it('widget state: restoreState applies what getState returned, and getState returns it again', () => {
    const golden = at(`${version}/widget-state`) as Record<string, unknown>;
    const widget = makeWidget(new MemoryStorage(), { symbol: 'RELIANCE', exchange: 'NSE', interval: '5m' });
    widget.series.setData(BARS.primary);
    const report = widget.restoreState(golden);
    expect(report.applied, report.reason).toBe(true);
    expectOnlyNamed(golden, JSON.parse(JSON.stringify(widget.getState())), named('widget-state', version));
  });

  it('workspace document: parses, imports and exports again', async () => {
    const golden = at(`${version}/workspace`) as Record<string, unknown>;
    expect(parseWorkspaceDocument(golden).panes.length).toBe(2);
    const repo = new WorkspaceRepository(catalogStorage(), 'compat', { now: () => NOW_MS, id: () => golden.id as string });
    const imported = await repo.importDocument(golden);
    const exported = JSON.parse(await repo.exportDocument('workspace', imported.id)) as Json;
    expectOnlyNamed(golden, exported, named('workspace', version));
  });

  it('workspace catalog: the repository reads it and writes it back', async () => {
    const golden = at(`${version}/workspace-catalog`) as { workspaces: Array<{ id: string }> };
    expect(parseWorkspaceCatalog(golden).workspaces.length).toBe(1);
    const storage = catalogStorage(golden);
    const repo = new WorkspaceRepository(storage, 'compat', { now: () => NOW_MS });
    const catalog = await repo.load();
    // Opening the saved layout is the smallest write a host makes to the catalog.
    await repo.openWorkspace(catalog.workspaces[0]!.id);
    expectOnlyNamed(golden, storage.stored(), named('workspace-catalog', version));
  });
});
