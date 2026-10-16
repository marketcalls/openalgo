/**
 * The widget shell: the frame it builds, the facts it owns (symbol, interval,
 * chart type, theme), the feed path, persistence, the keymap wiring, the
 * overlay stack and the dialog seam. Everything runs against the fake DOM in
 * helpers/fake-dom-widget.ts with a measured chart (applySize plus a
 * synchronous raf), the way tests/compare.test.ts does it.
 */
import { describe, it, expect, vi, beforeAll, afterEach } from 'vitest';
import { darkTheme, lightTheme, registerInterval, type Bar, type DataFeed, type BarsRequest } from '../src/index';
import {
  createWidget, registerWidgetDialog, unregisterWidgetDialog, widgetDialog, stripView, loadWindow, resolveTheme,
  SAVE_DEBOUNCE_MS, STATE_KEY, DRAWINGS_KEY_PREFIX, STORAGE_PREFIX, WIDGET_STYLE_ID, TOKEN_PREFIX, themeMode, injectWidgetStyles,
  type Widget, type WidgetOptions, type WidgetContext, type StorageLike,
} from '../src/widget/index';
import { fakeWidgetDocument, fakeContainer, fireKey, fire, ensureWindowGlobal, type FakeDocument, type FakeElement } from './helpers/fake-dom-widget';
import { chromeIconSvg } from 'openalgo-charts/draw';

beforeAll(ensureWindowGlobal);

const DAY = 86400;
const T0 = 1700000000;
const bars = (n: number, start = 100): Bar[] => Array.from({ length: n }, (_, i) => {
  const c = start + Math.sin(i / 4) * 5;
  return { time: T0 + i * DAY, open: c - 1, high: c + 2, low: c - 2, close: c, volume: 1000 + i };
});

class MemoryStorage implements StorageLike {
  public readonly map = new Map<string, string>();
  public getItem(k: string): string | null { return this.map.get(k) ?? null; }
  public setItem(k: string, v: string): void { this.map.set(k, v); }
  public removeItem(k: string): void { this.map.delete(k); }
}

const live: Widget[] = [];
afterEach(() => { for (const w of live.splice(0)) if (!w.isDestroyed) w.destroy(); });

interface Made { w: Widget; doc: FakeDocument; container: FakeElement; root: FakeElement; chartEl: FakeElement }

/** A widget in a fresh fake document, measured, painting synchronously. */
function make(opts: WidgetOptions = {}, doc: FakeDocument = fakeWidgetDocument()): Made {
  const container = fakeContainer(doc);
  const w = createWidget(container as unknown as HTMLElement, {
    document: doc as unknown as Document,
    pixelRatio: () => 1,
    raf: { schedule: (cb: () => void) => { cb(); return 1; }, cancel: () => {} },
    ...opts,
  });
  w.chart.applySize(800, 600);
  live.push(w);
  const root = w.root as unknown as FakeElement;
  root.rect = { left: 0, top: 0, width: 800, height: 600 };
  root.offsetWidth = 800;
  root.offsetHeight = 600;
  const chartEl = root.querySelector('.oac-chart') as FakeElement;
  chartEl.rect = { left: 42, top: 40, width: 758, height: 536 };
  return { w, doc, container, root, chartEl };
}

const flush = (): Promise<void> => new Promise((r) => setTimeout(r, 0));

describe('default candle density', () => {
  it('keeps spacing across screen widths, reloads and symbol changes', async () => {
    const feed: DataFeed = { getBars: async () => bars(200) };
    for (const width of [390, 1200]) {
      const { w } = make({ feed, symbol: 'SAMPLE', persist: false });
      w.chart.applySize(width, 600);
      await flush();
      expect(w.chart.timeScale.barSpacing).toBe(8);
      w.chart.setVisibleLogicalRange({ from: 0, to: 30 });
      w.setSymbol('NEXT');
      await flush();
      expect(w.chart.timeScale.barSpacing).toBe(8);
      w.setInterval('5m');
      await flush();
      expect(w.chart.timeScale.barSpacing).toBe(8);
    }
  });

  it('respects explicitly requested count and spacing preferences', async () => {
    const feed: DataFeed = { getBars: async () => bars(200) };
    const counted = make({ feed, symbol: 'SAMPLE', persist: false, navigation: { defaultVisibleBars: 50 } }).w;
    const spaced = make({ feed, symbol: 'SAMPLE', persist: false, navigation: { defaultBarSpacing: 12 } }).w;
    await flush();
    expect(counted.chart.getVisibleLogicalRange()).toEqual({ from: 149, to: 203 });
    expect(spaced.chart.timeScale.barSpacing).toBe(12);
  });

  it('drags time alone by default, so a wheel zoom after a drag still fits the price', () => {
    // A drag that also moved price switched the pane to manual scaling, and
    // every zoom after it left bars off the pane until auto was pressed again.
    expect(make().w.chart.navigationOptions().mousePan).toBe('horizontal');
    const both = make({ navigation: { mousePan: 'both' } }).w;
    expect(both.chart.navigationOptions().mousePan).toBe('both');
    const counted = make({ navigation: { defaultVisibleBars: 50 } }).w;
    expect(counted.chart.navigationOptions().mousePan).toBe('horizontal');
  });

  it('leaves the drag to the widget for a layout saved before 2.6.3, and keeps one chosen since', () => {
    // 2.6.2 wrote mousePan: 'both' into every chart state, chosen or not.
    const old = make().w.getState();
    const { savedBy, ...unstamped } = old;
    expect(typeof savedBy).toBe('string');
    const legacy = { ...unstamped, chart: { ...unstamped.chart, navigation: { ...unstamped.chart.navigation, mousePan: 'both' as const } } };
    const a = make().w;
    a.restoreState(legacy);
    expect(a.chart.navigationOptions().mousePan).toBe('horizontal');
    // Saved by this release, 'both' was somebody's choice.
    const b = make().w;
    b.restoreState({ ...legacy, savedBy: '2.6.3' });
    expect(b.chart.navigationOptions().mousePan).toBe('both');
    // And a host that asked for 'both' gets it from an old layout too.
    const c = make({ navigation: { mousePan: 'both' } }).w;
    c.restoreState(legacy);
    expect(c.chart.navigationOptions().mousePan).toBe('both');
    // A host that asked for 'horizontal' does not lose it to the recorded default.
    const d = make({ navigation: { mousePan: 'horizontal' } }).w;
    d.restoreState(legacy);
    expect(d.chart.navigationOptions().mousePan).toBe('horizontal');
  });

  it('leaves the drag to the widget for a layout saved before 2.6.3 when a reload restores it', () => {
    // A reload restores the persisted layout by its own path, not restoreState.
    const { savedBy: _stamp, ...unstamped } = make().w.getState();
    const legacy = { ...unstamped, chart: { ...unstamped.chart, navigation: { ...unstamped.chart.navigation, mousePan: 'both' as const } } };
    const reload = (state: object, opts: WidgetOptions = {}): string | undefined => {
      const store = new MemoryStorage();
      store.setItem(`${STORAGE_PREFIX}default:${STATE_KEY}`, JSON.stringify(state));
      return make({ persist: true, storage: store, ...opts }).w.chart.navigationOptions().mousePan;
    };
    expect(reload(legacy)).toBe('horizontal');
    expect(reload(legacy, { navigation: { mousePan: 'horizontal' } })).toBe('horizontal');
    expect(reload(legacy, { navigation: { mousePan: 'both' } })).toBe('both');
    expect(reload({ ...legacy, savedBy: '2.6.3' })).toBe('both');
  });

  it('zooms about the latest bar by default, and about the cursor when the host asks', () => {
    expect((make().w.chart as unknown as { _zoomAnchor: string })._zoomAnchor).toBe('right');
    expect((make({ zoomAnchor: 'cursor' }).w.chart as unknown as { _zoomAnchor: string })._zoomAnchor).toBe('cursor');
  });
});

describe('the frame', () => {
  it('names drawing rows the way the rail and the properties title do', () => {
    const { w } = make();
    const at = [{ time: 1, price: 2 }];
    const line = w.draw.add({ tool: 'trend-line', paneIndex: 0, style: {}, points: at });
    const xabcd = w.draw.add({ tool: 'xabcd-pattern', paneIndex: 0, style: {}, points: at });
    expect(w.objects.get('drawing:' + line.id)?.name).toBe('Trend Line');
    expect(w.objects.get('drawing:' + xabcd.id)?.name).toBe('XABCD Pattern');
  });

  it('owns a live objects panel and routes edits to existing settings dialogs', () => {
    const { w, root, doc } = make();
    const drawing = w.draw.add({ tool: 'trend-line', paneIndex: 0, style: {}, points: [] });
    expect(w.context.objects).toBe(w.objects);
    const opener = root.querySelector('.oac-topbar__objects')!;
    expect(opener).not.toBeNull();
    fire(opener, 'click');
    expect(root.querySelector('.oac-objects-content')).not.toBeNull();
    expect(doc.head.children[0].textContent).toContain('.oac-objects__row');
    expect(w.objects.openSettings('drawing:' + drawing.id)).toBe(true);
    expect(root.querySelector('.oac-props')).not.toBeNull();
    w.context.overlays.closeAll();
    expect(w.openObjects()).toBe(true);
    w.destroy();
    expect(w.objects.list()).toEqual([]);
    expect(w.openObjects()).toBe(false);
  });

  it('builds a top bar, a stage with the rail and the chart, a status line and a toast host', () => {
    const { root, container } = make();
    expect(container.children[0]).toBe(root);
    expect(root.tagName).toBe('DIV');
    expect(root.classList.contains('oac-widget')).toBe(true);
    expect(root.dataset.theme).toBe('dark');
    expect(root.querySelector('.oac-topbar')).not.toBeNull();
    expect(root.querySelector('.oac-stage .oac-rail')).not.toBeNull();
    expect(root.querySelector('.oac-stage .oac-chart')).not.toBeNull();
    expect(root.querySelector('.oac-statusline')).not.toBeNull();
    expect(root.querySelector('.oac-toasts')).not.toBeNull();
    expect(root.querySelector('.oac-layer')).not.toBeNull();
  });

  it('keeps linked branding in host chrome current with chart branding', () => {
    const { w, root } = make();
    const link = root.querySelector('.oac-topbar__branding') as FakeElement;
    expect(link).not.toBeNull();
    expect(link.tagName).toBe('A');
    expect(link.getAttribute('href')).toBe('https://openalgo.in');
    expect(link.getAttribute('target')).toBe('_blank');
    expect(link.getAttribute('rel')).toContain('noopener');
    expect(link.getAttribute('aria-label')).toBe('Chart by OpenAlgo');

    w.chart.setBranding(false);
    expect(root.querySelector('.oac-topbar__branding')).toBeNull();

    w.chart.setBranding({ href: 'https://charts.example.test', label: 'Charts provider' });
    const customLink = root.querySelector('.oac-topbar__branding') as FakeElement;
    expect(customLink.getAttribute('href')).toBe('https://charts.example.test');
    expect(customLink.textContent).toBe('Charts provider');
    expect(customLink.getAttribute('aria-label')).toBe('Charts provider');

    const off = make({ branding: false } as WidgetOptions);
    expect(off.root.querySelector('.oac-topbar__branding')).toBeNull();
  });

  it('injects one stylesheet per document however many widgets share it', () => {
    const doc = fakeWidgetDocument();
    make({}, doc);
    make({}, doc);
    expect(doc.head.children.filter((c) => c.id === WIDGET_STYLE_ID)).toHaveLength(1);
    expect(doc.head.children[0].textContent).toContain('.oac-widget');
    // Extra rules ride the same sheet, and only the first call decides its text.
    const other = fakeWidgetDocument();
    injectWidgetStyles(other as unknown as Document, '.oac-widget .extra { color: red; }');
    injectWidgetStyles(other as unknown as Document, '.oac-widget .later { color: blue; }');
    const sheets = other.head.children.filter((c) => c.id === WIDGET_STYLE_ID);
    expect(sheets).toHaveLength(1);
    expect(sheets[0].textContent).toContain('.extra');
    expect(sheets[0].textContent).not.toContain('.later');
  });

  it('paints the theme tokens onto the root from the chart theme', () => {
    const { root } = make();
    expect(root.style.getPropertyValue(TOKEN_PREFIX + 'bg')).toBe(darkTheme.background);
    expect(root.style.getPropertyValue(TOKEN_PREFIX + 'buy')).toBe(darkTheme.upColor);
    expect(root.style.getPropertyValue(TOKEN_PREFIX + 'acc')).toBe(darkTheme.lineColor);
  });

  it('hides the pieces a host turns off', () => {
    const { root } = make({ rail: false, topbar: false, statusline: false });
    expect((root.querySelector('.oac-rail') as FakeElement).hidden).toBe(true);
    expect((root.querySelector('.oac-topbar') as FakeElement).hidden).toBe(true);
    expect((root.querySelector('.oac-statusline') as FakeElement).hidden).toBe(true);
    // No rail means no rail buttons, not an empty rail with listeners.
    expect(root.querySelectorAll('.oac-rail__btn')).toHaveLength(0);
  });

  it('resolves a selector against the document it is given', () => {
    const doc = fakeWidgetDocument();
    const el = fakeContainer(doc);
    el.id = 'host';
    const w = createWidget('#host', { document: doc as unknown as Document, raf: { schedule: () => 1 } });
    live.push(w);
    expect(el.children[0]).toBe(w.root as unknown as FakeElement);
    expect(() => createWidget('#nope', { document: doc as unknown as Document })).toThrow(/no element matches/);
  });
});

describe('theme', () => {
  it('switches the chart palette, the root mode and the tokens, and tells listeners', () => {
    const { w, root } = make();
    const seen = vi.fn();
    w.on('theme', seen);
    w.setTheme('light');
    expect(w.theme()).toBe('light');
    expect(w.chart.theme()).toBe(lightTheme);
    expect(root.dataset.theme).toBe('light');
    expect(root.style.getPropertyValue(TOKEN_PREFIX + 'bg')).toBe(lightTheme.background);
    expect(seen).toHaveBeenCalledWith({ theme: 'light', chartTheme: lightTheme });
    expect(w.context.theme).toBe('light');
    expect(w.context.chartTheme).toBe(lightTheme);
  });

  it('takes a full ChartTheme and judges its mode from the background', () => {
    const custom = { ...darkTheme, background: '#f4f6fa', lineColor: '#aa00aa' };
    const { w, root } = make({ theme: custom });
    expect(w.theme()).toBe('light');
    expect(themeMode(custom)).toBe('light');
    expect(w.chart.theme()).toBe(custom);
    expect(root.style.getPropertyValue(TOKEN_PREFIX + 'acc')).toBe('#aa00aa');
    expect(resolveTheme(undefined)).toEqual({ theme: darkTheme, name: 'dark' });
  });
});

describe('symbol, interval and chart type', () => {
  it('publishes symbol and interval changes and reflects them in the chrome', () => {
    const { w, root } = make({ symbol: 'infy', exchange: 'NSE', interval: '5m' });
    expect(w.symbol()).toBe('INFY');
    const sym = vi.fn();
    const iv = vi.fn();
    const chartSaw = vi.fn();
    w.on('symbol', sym);
    w.on('interval', iv);
    w.chart.on('symbol', chartSaw);
    w.setSymbol('reliance');
    expect(sym).toHaveBeenCalledWith({ symbol: 'RELIANCE', exchange: 'NSE' });
    expect(chartSaw).toHaveBeenCalledWith({ symbol: 'RELIANCE', exchange: 'NSE' });
    expect((root.querySelector('.oac-sym__input') as FakeElement).value).toBe('RELIANCE');
    expect(root.querySelector('.oac-statusline__sym')?.textContent).toBe('NSE:RELIANCE');
    w.setInterval('1h');
    expect(iv).toHaveBeenCalledWith({ interval: '1h' });
    expect(root.querySelector('.oac-statusline__iv')?.textContent).toBe('1h');
    const on = root.querySelectorAll('.oac-pills > button[aria-pressed="true"]');
    expect(on).toHaveLength(1);
    expect(on[0].dataset.interval).toBe('1h');
    // The same value again is not a change.
    w.setSymbol('RELIANCE');
    expect(sym).toHaveBeenCalledTimes(1);
    expect(() => w.setInterval('  ')).toThrow(/must not be empty/);
  });

  it('refuses an interval code nothing recognises, and takes one the host registered', () => {
    const { w } = make();
    expect(() => w.setInterval('1wk')).toThrow(/unknown interval "1wk"/);
    expect(() => make({ interval: '1wk' })).toThrow(/unknown interval/);
    expect(() => make({ intervals: ['5m', 'MN'] })).toThrow(/unknown interval "MN"/);
    const off = registerInterval({ code: '1wk', bucketing: { mode: 'interval', seconds: 7 * DAY } });
    try {
      w.setInterval('1wk');
      expect(w.interval()).toBe('1wk');
      // The registered code joins the default pills of a new widget.
      const b = make();
      expect(b.root.querySelectorAll('.oac-pills > button').map((x) => x.dataset.interval)).toContain('1wk');
      // A saved code this build no longer knows falls back to the default rather than a wrong frame.
      const store = new MemoryStorage();
      store.setItem(`${STORAGE_PREFIX}default:${STATE_KEY}`, JSON.stringify({ version: 1, symbol: 'A', interval: 'MN' }));
      expect(make({ persist: true, storage: store }).w.interval()).toBe('1d');
    } finally {
      off();
    }
  });

  it('offers the default pills plus the current interval, or exactly the list the host gives', () => {
    const a = make({ interval: '2h' });
    expect(a.root.querySelectorAll('.oac-pills > button').map((b) => b.dataset.interval)).toEqual(['1m', '5m', '15m', '1h', '1d', '1w', '2h']);
    const b = make({ intervals: ['5m', '1d'], interval: '1d' });
    expect(b.root.querySelectorAll('.oac-pills > button').map((x) => x.textContent)).toEqual(['5m', 'D']);
    // Each name carries the text the pill shows.
    expect(b.root.querySelectorAll('.oac-pills > button').map((x) => x.getAttribute('aria-label'))).toEqual(['Interval 5m', 'Interval D']);
    (b.root.querySelector('.oac-pills > button[data-interval="5m"]') as FakeElement).click();
    expect(b.w.interval()).toBe('5m');
  });

  it('swaps the primary series type and keeps its data', () => {
    const { w, root } = make();
    w.series.setData(bars(20));
    const layout = vi.fn();
    w.on('layout', layout);
    w.setChartType('line');
    expect(w.chartType()).toBe('line');
    expect(w.chart.primarySeriesInfo()?.type).toBe('line');
    expect(w.chart.primarySeries()?.getData()).toHaveLength(20);
    expect(layout).toHaveBeenCalledWith({ reason: 'chartType', chartType: 'line' });
    expect(root.querySelector('.oac-topbar__type')?.textContent).toContain('Line');
    expect(() => w.setChartType('nonsense')).toThrow(/not a registered chart type/);
    expect(() => make({ chartType: 'nonsense' })).toThrow(/not a registered chart type/);
  });
});

describe('the feed', () => {
  const feedOf = (impl: (req: BarsRequest) => Promise<Bar[]>, sub?: DataFeed['subscribeBars']): DataFeed & { calls: BarsRequest[] } => {
    const calls: BarsRequest[] = [];
    return { calls, getBars: (req) => { calls.push(req); return impl(req); }, subscribeBars: sub };
  };

  it('loads bars for the symbol and interval, fits the view, and reports the count', async () => {
    const feed = feedOf(async () => bars(30));
    const data = vi.fn();
    const { w, root } = make({ feed, symbol: 'INFY', exchange: 'NSE', interval: '1d', lookbackBars: 30, now: () => (T0 + 40 * DAY) * 1000 });
    w.on('data', data);
    expect(root.querySelector('.oac-statusline__msg')?.textContent).toBe('Loading INFY 1d');
    await flush();
    expect(feed.calls[0]).toMatchObject({ symbol: 'INFY', exchange: 'NSE', interval: '1d' });
    expect(feed.calls[0].to).toBe(T0 + 40 * DAY);
    expect(feed.calls[0].from).toBe(T0 + 10 * DAY);
    expect(w.chart.primarySeries()?.getData()).toHaveLength(30);
    expect(data).toHaveBeenCalledWith({ symbol: 'INFY', interval: '1d', bars: 30 });
    expect(root.querySelector('.oac-statusline__msg')?.textContent).toBe('30 bars');
  });

  it('keeps the preferred visible bar count across symbol and interval loads', async () => {
    const feed = feedOf(() => Promise.resolve(bars(200)));
    const { w } = make({ feed, symbol: 'INFY', navigation: { defaultVisibleBars: 50 } });
    await flush();
    expect(w.chart.getVisibleLogicalRange()).toEqual({ from: 149, to: 203 });
    w.setSymbol('RELIANCE');
    await flush();
    expect(w.chart.getVisibleLogicalRange()).toEqual({ from: 149, to: 203 });
    w.setInterval('5m');
    await flush();
    expect(w.chart.getVisibleLogicalRange()).toEqual({ from: 149, to: 203 });
    expect(w.chart.primarySeries()?.getData()).toHaveLength(200);
  });

  it('drops a slow answer that arrives after a faster one for the next symbol', async () => {
    let release: (() => void) | null = null;
    const feed = feedOf((req) => {
      if (req.symbol === 'SLOW') return new Promise((r) => { release = () => r(bars(5, 500)); });
      return Promise.resolve(bars(10, 100));
    });
    const { w } = make({ feed, symbol: 'SLOW' });
    w.setSymbol('FAST');
    await flush();
    expect(w.chart.primarySeries()?.getData()).toHaveLength(10);
    (release as unknown as () => void)();
    await flush();
    // The stale bars for SLOW never land under FAST's name.
    expect(w.chart.primarySeries()?.getData()).toHaveLength(10);
    expect(w.chart.primarySeries()?.getData()[0].close).toBeCloseTo(100, 0);
  });

  it('feeds live bars through subscribeBars and lets go on the next load', async () => {
    let push: ((b: Bar) => void) | null = null;
    const unsub = vi.fn();
    const feed = feedOf(async () => bars(3), (_req, onBar) => { push = onBar; return unsub; });
    const { w } = make({ feed, symbol: 'X' });
    await flush();
    (push as unknown as (b: Bar) => void)({ time: T0 + 3 * DAY, open: 1, high: 2, low: 0.5, close: 1.5 });
    expect(w.chart.primarySeries()?.getData()).toHaveLength(4);
    w.setInterval('1h');
    expect(unsub).toHaveBeenCalledTimes(1);
    await flush();
    w.destroy();
    expect(unsub).toHaveBeenCalledTimes(2);
  });

  it('reports a failed load on the status line, as a toast and as an event, and leaves the chart alone', async () => {
    const feed = feedOf(async () => { throw new Error('rate limited'); });
    const { w, root } = make({ feed, symbol: 'X' });
    const data = vi.fn();
    w.on('data', data);
    await flush();
    const msg = root.querySelector('.oac-statusline__msg') as FakeElement;
    expect(msg.textContent).toBe('Could not load X 1d');
    expect(msg.classList.contains('is-error')).toBe(true);
    expect(root.querySelector('.oac-toast--error')?.textContent).toContain('rate limited');
    expect(data).toHaveBeenCalledWith({ symbol: 'X', interval: '1d', bars: 0, error: 'rate limited' });
  });

  it('sizes the load window from the interval, and falls back to years for a calendar code', () => {
    expect(loadWindow('5m', 100, 10_000)).toEqual({ from: 10_000 - 100 * 300, to: 10_000 });
    expect(loadWindow('MN', 100, 10_000).from).toBe(10_000 - 5 * 365 * DAY);
  });
});

describe('state and persistence', () => {
  it('round-trips through getState and restoreState, drawings included', () => {
    const a = make({ symbol: 'A', interval: '5m' });
    a.w.series.setData(bars(20));
    a.w.draw.add({ tool: 'horizontal-line', points: [{ time: T0 + 5 * DAY, price: 100 }], style: {}, paneIndex: 0 });
    a.w.setTheme('light');
    const state = a.w.getState();
    expect(state).toMatchObject({ version: 1, symbol: 'A', interval: '5m', chartType: 'candlestick', theme: 'light' });
    expect(JSON.parse(JSON.stringify(state))).toEqual(state);

    const b = make();
    b.w.series.setData(bars(20));
    const report = b.w.restoreState(state);
    expect(report.applied).toBe(true);
    expect(report.chart?.applied).toBe(true);
    expect(b.w.symbol()).toBe('A');
    expect(b.w.interval()).toBe('5m');
    expect(b.w.theme()).toBe('light');
    expect(b.w.draw.drawings()).toHaveLength(1);
    expect(b.w.draw.drawings()[0].tool).toBe('horizontal-line');
    expect(b.w.restoreState('junk')).toEqual({ applied: false, reason: 'not a widget state object' });
    expect(b.w.restoreState({ version: 9 }).applied).toBe(false);
  });

  it('stripView keeps the workspace and drops what described the old view', () => {
    const { w } = make();
    w.series.setData(bars(20));
    const state = w.getState().chart;
    const stripped = stripView(state) as unknown as Record<string, unknown>;
    expect(stripped.viewport).toBeUndefined();
    expect(stripped.barSpacing).toBeUndefined();
    const pane = (stripped.panes as Array<{ priceScale: Record<string, unknown> }>)[0];
    expect(pane.priceScale.autoScale).toBe(true);
    expect(pane.priceScale.range).toBeUndefined();
    expect((state as unknown as Record<string, unknown>).viewport).toBeDefined();
  });

  it('stripView clears every axis viewport without mutating saved preferences', () => {
    const { w } = make();
    const state = w.getState().chart;
    const pinned = {
      marginTop: 0.1, marginBottom: 0.2, minMove: 0.01, minPrecision: 3,
      mode: 'linear' as const, inverted: true, autoScale: false,
      range: { min: 10, max: 90 }, fixedRange: { min: 0, max: 100 },
      ratioLock: { barSpacing: 8, height: 400 },
    };
    state.panes = [{ weight: 1, priceScale: { ...pinned }, scales: { left: { ...pinned }, 'overlay:score': { ...pinned } } }];
    const stripped = stripView(state);
    for (const scale of [stripped.panes![0].priceScale, ...Object.values(stripped.panes![0].scales!)]) {
      expect(scale).toMatchObject({ autoScale: true, inverted: true, minPrecision: 3, fixedRange: { min: 0, max: 100 } });
      expect(scale?.range).toBeUndefined();
      expect(scale?.ratioLock).toBeUndefined();
    }
    expect(state.panes[0].scales!['overlay:score']).toEqual(pinned);
    expect(state.panes[0].priceScale).toEqual(pinned);
  });

  it('persists the layout under a namespaced key after a debounce, and a new widget picks it up', async () => {
    vi.useFakeTimers();
    try {
      const store = new MemoryStorage();
      const a = make({ persist: 'desk', storage: store, symbol: 'A', interval: '15m' });
      a.w.series.setData(bars(20));
      a.w.draw.add({ tool: 'horizontal-line', points: [{ time: T0 + 5 * DAY, price: 100 }], style: {}, paneIndex: 0 });
      a.w.setTheme('light');
      // The drawing is written at once, under its instrument; the layout waits for the debounce.
      expect([...store.map.keys()]).toEqual([`${STORAGE_PREFIX}desk:${DRAWINGS_KEY_PREFIX}A`]);
      vi.advanceTimersByTime(SAVE_DEBOUNCE_MS + 1);
      const key = `${STORAGE_PREFIX}desk:${STATE_KEY}`;
      expect(store.map.has(key)).toBe(true);
      const saved = JSON.parse(store.map.get(key) as string);
      expect(saved).toMatchObject({ symbol: 'A', interval: '15m', theme: 'light' });

      const b = make({ persist: 'desk', storage: store });
      expect(b.w.symbol()).toBe('A');
      expect(b.w.interval()).toBe('15m');
      expect(b.w.theme()).toBe('light');
      expect(b.w.draw.drawings()).toHaveLength(1);
      // An explicit option outranks the saved fact, and the layout still
      // applies, all but its drawings: those are A's, kept for A.
      const c = make({ persist: 'desk', storage: store, symbol: 'Z' });
      expect(c.w.symbol()).toBe('Z');
      expect(c.w.draw.drawings()).toHaveLength(0);
      expect(c.w.instrumentDrawings?.document({ symbol: 'A', exchange: '' })?.drawings).toHaveLength(1);
      // Nothing persists without the option.
      const d = make({ storage: store });
      expect(d.w.context.storage.enabled).toBe(false);
      d.w.setTheme('light');
      vi.advanceTimersByTime(SAVE_DEBOUNCE_MS + 1);
      expect(JSON.parse(store.map.get(key) as string).theme).toBe('light');
      expect(store.map.size).toBe(3);
    } finally {
      vi.useRealTimers();
    }
  });

  it('flushes a pending save on destroy', () => {
    const store = new MemoryStorage();
    const { w } = make({ persist: true, storage: store });
    w.setInterval('1h');
    w.destroy();
    expect(JSON.parse(store.map.get(`${STORAGE_PREFIX}default:${STATE_KEY}`) as string).interval).toBe('1h');
  });

  it('writes a pending save when the page goes away, and stops listening once destroyed', () => {
    // The fake document has no window, and the flush listens on the window.
    const doc = fakeWidgetDocument();
    const listeners = new Map<string, Set<() => void>>();
    (doc as unknown as { defaultView: unknown }).defaultView = {
      addEventListener: (type: string, fn: () => void) => { listeners.set(type, (listeners.get(type) ?? new Set()).add(fn)); },
      removeEventListener: (type: string, fn: () => void) => { listeners.get(type)?.delete(fn); },
    };
    const pagehide = (): void => { for (const fn of [...(listeners.get('pagehide') ?? [])]) fn(); };
    const store = new MemoryStorage();
    const key = `${STORAGE_PREFIX}default:${STATE_KEY}`;
    const { w } = make({ persist: true, storage: store }, doc);
    w.setInterval('1h');
    // Still inside the debounce: only the page going away writes it now.
    expect(store.map.has(key)).toBe(false);
    pagehide();
    expect(JSON.parse(store.map.get(key) as string).interval).toBe('1h');
    w.destroy();
    store.map.delete(key);
    pagehide();
    expect(store.map.has(key)).toBe(false);
    expect(listeners.get('pagehide')?.size ?? 0).toBe(0);
  });
});

describe('keyboard', () => {
  it('arms a tool from its chord while the pointer is over the widget, and Escape leaves it', () => {
    const { w, root, chartEl } = make();
    // Outside the widget nothing fires.
    fireKey(root.ownerDocument.body, 't', { altKey: true });
    expect(w.draw.activeTool()).toBeNull();
    fire(root, 'pointerenter');
    fireKey(chartEl, 't', { altKey: true });
    expect(w.draw.activeTool()).toBe('trend-line');
    expect(chartEl.style.getPropertyValue('--oac-tool-cursor')).toContain('url(');
    fireKey(chartEl, 'Escape');
    expect(w.draw.activeTool()).toBeNull();
    expect(chartEl.style.getPropertyValue('--oac-tool-cursor')).toBe('');
  });

  it('routes the editing keys through the tier mapping and declines what means nothing now', () => {
    const { w, root, chartEl } = make();
    w.series.setData(bars(20));
    fire(root, 'pointerenter');
    const d = w.draw.add({ tool: 'horizontal-line', points: [{ time: T0 + 5 * DAY, price: 100 }], style: {}, paneIndex: 0 });
    expect(w.draw.drawings()).toHaveLength(1);
    const undo = fireKey(chartEl, 'z', { ctrlKey: true });
    expect(w.draw.drawings()).toHaveLength(0);
    expect(undo.defaultPrevented).toBe(true);
    fireKey(chartEl, 'z', { ctrlKey: true, shiftKey: true });
    expect(w.draw.drawings()).toHaveLength(1);
    // An arrow with nothing selected is the chart's pan, not a nudge.
    const pan = fireKey(chartEl, 'ArrowLeft');
    expect(pan.defaultPrevented).toBe(false);
    w.draw.select(d.id);
    const before = w.draw.get(d.id)?.points[0].price as number;
    fireKey(chartEl, 'ArrowUp');
    expect(w.draw.get(d.id)?.points[0].price).toBeGreaterThan(before);
    fireKey(chartEl, 'Delete');
    expect(w.draw.drawings()).toHaveLength(0);
  });

  it('opens the shortcuts panel on ? and closes it on Escape', () => {
    const { w, root, chartEl } = make();
    fire(root, 'pointerenter');
    fireKey(chartEl, '?', { shiftKey: true });
    const panel = root.querySelector('.oac-keys-dialog') as FakeElement;
    expect(panel).not.toBeNull();
    expect(w.context.overlays.size()).toBe(1);
    expect(panel.querySelectorAll('.oac-head').map((h) => h.textContent)).toEqual(expect.arrayContaining(['Drawing', 'Drawing tools', 'Chart', 'Tool rail']));
    expect(panel.querySelectorAll('.oac-keys__row.is-shadowed')).toHaveLength(2);
    // With the panel open, a tool chord goes nowhere.
    fireKey(panel, 't', { altKey: true });
    expect(w.draw.activeTool()).toBeNull();
    fireKey(panel, 'Escape');
    expect(w.context.overlays.size()).toBe(0);
    expect(root.querySelector('.oac-keys-dialog')).toBeNull();
  });

  it('records the two chords the draw tier and the engine both claim', () => {
    const { w } = make();
    const chart = w.context.keymap.conflicts().filter((c) => c.source === 'chart').map((c) => c.combo).sort();
    expect(chart).toEqual(['Alt+h', 'Alt+v']);
    expect(w.context.keymap.conflicts().filter((c) => c.source === 'widget')).toEqual([]);
  });
});

describe('overlays', () => {
  it('positions a popover under its anchor inside the widget, closes on outside press, and hands focus back', () => {
    const { w, root, doc } = make();
    const anchor = root.querySelector('.oac-topbar__type') as FakeElement;
    anchor.rect = { left: 300, top: 46, width: 90, height: 28 };
    anchor.focus();
    const panel = doc.createElement('div');
    panel.offsetWidth = 200;
    panel.offsetHeight = 100;
    const btn = doc.createElement('button');
    panel.appendChild(btn);
    const onClose = vi.fn();
    w.context.openOverlay(panel as unknown as HTMLElement, { anchor: anchor as unknown as HTMLElement, onClose });
    expect(panel.parentElement?.classList.contains('oac-layer')).toBe(true);
    expect(panel.style.left).toBe('300px');
    expect(panel.style.top).toBe(`${46 + 28 + 4}px`);
    expect(anchor.getAttribute('aria-expanded')).toBe('true');
    expect(doc.activeElement).toBe(btn);
    // A press inside stays; one outside closes.
    fire(btn, 'pointerdown');
    expect(w.context.overlays.size()).toBe(1);
    fire(doc.body, 'pointerdown');
    expect(w.context.overlays.size()).toBe(0);
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(anchor.getAttribute('aria-expanded')).toBe('false');
    expect(doc.activeElement).toBe(anchor);
  });

  it('centres a dialog over a scrim, traps Tab inside it, and Escape closes only the newest', () => {
    const { w, root, doc } = make();
    const dialog = doc.createElement('div');
    const a = doc.createElement('button');
    const b = doc.createElement('button');
    dialog.appendChild(a);
    dialog.appendChild(b);
    w.context.openOverlay(dialog as unknown as HTMLElement);
    expect(dialog.classList.contains('oac-dialog')).toBe(true);
    expect(dialog.getAttribute('aria-modal')).toBe('true');
    expect(root.querySelector('.oac-scrim')).not.toBeNull();
    expect(doc.activeElement).toBe(a);
    b.focus();
    fireKey(b, 'Tab');
    expect(doc.activeElement).toBe(a);
    fireKey(a, 'Tab', { shiftKey: true });
    expect(doc.activeElement).toBe(b);
    // A press outside a modal changes nothing.
    fire(doc.body, 'pointerdown');
    expect(w.context.overlays.size()).toBe(1);
    const pop = doc.createElement('div');
    w.context.openOverlay(pop as unknown as HTMLElement, { anchor: b as unknown as HTMLElement, placement: 'below' });
    expect(w.context.overlays.size()).toBe(2);
    fireKey(pop, 'Escape');
    expect(w.context.overlays.size()).toBe(1);
    expect(w.context.overlays.top()).toBe(dialog);
    w.context.overlays.closeAll();
    expect(root.querySelector('.oac-scrim')).toBeNull();
  });

  it('keeps closing popovers on an outside press when one onClose closes an older one', () => {
    const { w, doc } = make();
    const panel = (): HTMLElement => doc.createElement('div') as unknown as HTMLElement;
    const closeFirst = w.context.openOverlay(panel(), { placement: 'below' });
    w.context.openOverlay(panel(), { placement: 'below' });
    // The newest takes the oldest with it, the way a submenu can close the chain it opened from.
    w.context.openOverlay(panel(), { placement: 'below', onClose: closeFirst });
    expect(w.context.overlays.size()).toBe(3);
    expect(() => fire(doc.body, 'pointerdown')).not.toThrow();
    expect(w.context.overlays.size()).toBe(0);
  });
});

describe('dialogs and the toolbar', () => {
  it('opens a registered dialog with the context and renders the button disabled without one', () => {
    // The dialog tier registers its mounts when imported; this test owns the
    // registry for its duration and puts back what it found.
    const prevSettings = widgetDialog('settings');
    const prevPicker = widgetDialog('indicatorPicker');
    unregisterWidgetDialog('settings');
    unregisterWidgetDialog('indicatorPicker');
    try {
      const first = make();
      const settings = first.root.querySelector('.oac-topbar .oac-btn[aria-label="Chart settings"]') as FakeElement;
      expect(settings.classList.contains('is-off')).toBe(true);
      expect(settings.getAttribute('aria-disabled')).toBe('true');
      expect(first.w.openSettings()).toBe(false);
      expect(first.w.openIndicatorPicker()).toBe(false);
      const mount = vi.fn((_ctx: WidgetContext) => ({ close: () => {} }));
      const off = registerWidgetDialog('settings', mount);
      try {
        const { w, root } = make();
        const btn = root.querySelector('.oac-topbar .oac-btn[aria-label="Chart settings"]') as FakeElement;
        expect(btn.classList.contains('is-off')).toBe(false);
        btn.click();
        expect(mount).toHaveBeenCalledWith(w.context, btn);
        expect(w.openSettings()).toBe(true);
        expect(w.openIndicatorPicker()).toBe(false);
        // A widget built before the registration sees it on its next refresh.
        first.w.setTheme('light');
        expect(settings.classList.contains('is-off')).toBe(false);
      } finally {
        off();
      }
    } finally {
      if (prevSettings !== null) registerWidgetDialog('settings', prevSettings);
      if (prevPicker !== null) registerWidgetDialog('indicatorPicker', prevPicker);
    }
  });

  it('captures the chart as PNG through the engine and as SVG through a download', () => {
    const { w, root } = make();
    w.series.setData(bars(10));
    const png = vi.spyOn(w.chart, 'takeScreenshot').mockReturnValue({ toDataURL: () => 'data:image/png;base64,' } as unknown as HTMLCanvasElement);
    const svg = vi.spyOn(w.chart, 'exportSVG');
    const capture = root.querySelector('.oac-topbar .oac-btn[aria-label="Capture chart"]') as FakeElement;
    capture.click();
    const rows = root.querySelectorAll('.oac-menu .oac-menu__row');
    expect(rows.map((r) => r.querySelector('.oac-menu__label')?.textContent)).toEqual(['Download PNG', 'Download SVG', 'Copy image', 'Download chart data (CSV)']);
    // No clipboard in this runtime: the row says so and is disabled rather than dead.
    expect(rows[2].getAttribute('aria-disabled')).toBe('true');
    rows[0].click();
    expect(png).toHaveBeenCalledTimes(1);
    expect(root.querySelector('.oac-statusline__msg')?.textContent).toBe('Saved a PNG of the chart');
    capture.click();
    root.querySelectorAll('.oac-menu .oac-menu__row')[1].click();
    expect(svg).toHaveBeenCalledTimes(1);
    // Node has Blob but no object URLs: the row reports rather than throws.
    expect(root.querySelector('.oac-statusline__msg')?.textContent).toMatch(/Saved an SVG|cannot save files/);
  });

  it('disables CSV while its managed source is loading even with retained bars', () => {
    const { w, root } = make({ feed: { getBars: () => new Promise(() => {}) }, symbol: 'PENDING' });
    w.series.setData(bars(3));
    (root.querySelector('.oac-topbar .oac-btn[aria-label="Capture chart"]') as FakeElement).click();
    const item = root.querySelectorAll('.oac-menu .oac-menu__row')
      .find(row => row.querySelector('.oac-menu__label')?.textContent === 'Download chart data (CSV)');
    expect(item?.getAttribute('aria-disabled')).toBe('true');
  });

  it('lists the price-series chart types in the menu and applies a pick', () => {
    const { w, root } = make();
    (root.querySelector('.oac-topbar__type') as FakeElement).click();
    const labels = root.querySelectorAll('.oac-menu .oac-menu__row').map((r) => r.querySelector('.oac-menu__label')?.textContent);
    expect(labels).toEqual(expect.arrayContaining(['Candles', 'Line', 'Area', 'Baseline']));
    expect(labels).not.toContain('Histogram');
    expect(root.querySelector('.oac-menu .oac-menu__row[aria-checked="true"] .oac-menu__label')?.textContent).toBe('Candles');
    const area = root.querySelectorAll('.oac-menu .oac-menu__row').find((r) => r.textContent === 'Area') as FakeElement;
    area.click();
    expect(w.chartType()).toBe('area');
    expect(w.context.overlays.size()).toBe(0);
  });

  it('commits a typed symbol on Enter and offers the host search results as the user types', () => {
    vi.useFakeTimers();
    try {
      const search = vi.fn((q: string) => [{ symbol: q.toUpperCase() + 'BANK', exchange: 'NSE', name: 'A bank' }, { symbol: q.toUpperCase(), exchange: 'BSE' }]);
      const { w, root, doc } = make({ symbol: 'INFY', symbolSearch: search });
      const input = root.querySelector('.oac-sym__input') as FakeElement;
      input.focus();
      input.value = 'hdfc';
      fire(input, 'input');
      expect(search).not.toHaveBeenCalled();
      vi.advanceTimersByTime(200);
      expect(search).toHaveBeenCalledWith('hdfc', { signal: expect.any(AbortSignal) });
      return Promise.resolve().then(() => {
        const rows = root.querySelectorAll('.oac-sym__results .oac-menu__row');
        expect(rows).toHaveLength(2);
        expect(rows[0].textContent).toBe('NSE:HDFCBANKA bank');
        // The caret stays in the box; the arrows move the highlight.
        expect(doc.activeElement).toBe(input);
        fireKey(input, 'ArrowDown');
        fireKey(input, 'Enter');
        expect(w.symbol()).toBe('HDFC');
        expect(w.exchange()).toBe('BSE');
        expect(w.context.overlays.size()).toBe(0);
        input.focus();
        input.value = 'tcs';
        fireKey(input, 'Enter');
        expect(w.symbol()).toBe('TCS');
      });
    } finally {
      vi.useRealTimers();
    }
  });
});

describe('the status line', () => {
  it.each([true, false])('preserves instrument capability across interval changes (managed feed: %s)', managed => {
    const { w } = make({ symbol: 'CONTRACT', exchange: 'NFO',
      ...(managed ? { feed: { getBars: async () => bars(2) } } : {}),
    });
    w.chart.setDataContext({ ...w.chart.getDataContext(), hasOpenInterest: true });
    w.setInterval('5m');
    expect(w.chart.hasOpenInterest).toBe(true);
    expect(w.chart.getDataContext()?.interval).toBe('5m');
    w.setSymbol('CASH', 'NSE');
    expect(w.chart.hasOpenInterest).toBeUndefined();
  });

  it('shows an opted-in OI zero, hides missing readings and reacts to instrument capability', () => {
    const { w, root } = make({ locale: 'en-US' });
    const bar = { ...bars(1)[0], oi: 0 };
    const field = () => root.querySelector('.oac-statusline__oi') as FakeElement;
    const hover = (b: Bar) => w.chart.emit('crosshair:move', {
      time: b.time, index: 0, price: b.close, bar: b, point: { x: 10, y: 10 }, paneIndex: 0,
    });
    hover(bar);
    expect(field()).not.toBeNull();
    expect(field().hidden).toBe(true);
    w.chart.setStatusLineOptions({ openInterest: true });
    hover({ ...bar });
    expect(field().hidden).toBe(false);
    expect(root.querySelector('.oac-statusline__oi b')?.textContent).toBe('0');
    w.chart.setDataContext({ hasOpenInterest: false });
    expect(field().hidden).toBe(true);
    w.chart.setDataContext({ hasOpenInterest: true });
    expect(field().hidden).toBe(false);
    hover({ ...bar, oi: undefined });
    expect(field().hidden).toBe(true);
    hover({ ...bar, oi: 1_500_000 });
    expect(root.querySelector('.oac-statusline__oi b')?.textContent).toBe('1.5M');
  });

  it('shows the hovered bar in the engine fields and follows the chart switches', () => {
    const { w, root } = make({ locale: 'de-DE' });
    w.series.setData(bars(20));
    const bar = { time: T0 + 3 * DAY, open: 100, high: 104.5, low: 98, close: 102.25, volume: 1234567 };
    w.chart.emit('crosshair:move', { time: bar.time, index: 3, price: 101, bar, point: { x: 10, y: 10 }, paneIndex: 0 });
    const text = (sel: string): string => root.querySelector(sel)?.textContent ?? '';
    expect(text('.oac-statusline__o b')).toBe('100,00');
    expect(text('.oac-statusline__c b')).toBe('102,25');
    expect(text('.oac-statusline__chg b')).toBe('+2,25 (+2,25%)');
    expect((root.querySelector('.oac-statusline__chg') as FakeElement).classList.contains('is-up')).toBe(true);
    // Compared through the same formatter: the locale's group separator is a
    // non-breaking space, which a literal in the test would not carry.
    expect(text('.oac-statusline__vol b')).toBe(new Intl.NumberFormat('de-DE', { notation: 'compact', maximumFractionDigits: 2 }).format(1234567));
    expect(text('.oac-statusline__time')).toContain('Nov');
    expect(text('.oac-statusline__tz')).toBe('Asia/Kolkata');
    w.chart.setStatusLineOptions({ chartValues: false, volume: false });
    w.chart.emit('crosshair:move', { time: bar.time, index: 3, price: 101, bar: { ...bar, close: 99 }, point: { x: 10, y: 10 }, paneIndex: 0 });
    expect((root.querySelector('.oac-statusline__o') as FakeElement).hidden).toBe(true);
    expect((root.querySelector('.oac-statusline__vol') as FakeElement).hidden).toBe(true);
    expect((root.querySelector('.oac-statusline__chg') as FakeElement).hidden).toBe(false);
    expect((root.querySelector('.oac-statusline__chg') as FakeElement).classList.contains('is-down')).toBe(true);
    // The pointer leaving falls back to the last bar rather than a blank row.
    w.chart.setStatusLineOptions({ chartValues: true });
    w.chart.emit('crosshair:move', { time: null, index: null, price: null, bar: null, point: null, paneIndex: null });
    const last = bars(20)[19];
    expect(text('.oac-statusline__c b')).toBe(new Intl.NumberFormat('de-DE', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(last.close));
  });

  it('carries the shell status messages and the bus hears them', () => {
    const { w, root } = make();
    const seen = vi.fn();
    w.on('status', seen);
    w.context.status('hello', 'error');
    const msg = root.querySelector('.oac-statusline__msg') as FakeElement;
    expect(msg.textContent).toBe('hello');
    expect(msg.classList.contains('is-error')).toBe(true);
    expect(seen).toHaveBeenCalledWith({ text: 'hello', kind: 'error' });
  });
});

describe('toasts and the bus', () => {
  it('stacks toasts newest last, drops the oldest past the limit, and keeps errors until dismissed', () => {
    vi.useFakeTimers();
    try {
      const { w, root } = make();
      for (let i = 0; i < 6; i++) w.context.toast(`note ${i}`);
      const host = root.querySelector('.oac-toasts') as FakeElement;
      expect(host.children.map((c) => c.textContent)).toEqual(['note 1', 'note 2', 'note 3', 'note 4', 'note 5']);
      const err = w.context.toast('broken', 'error');
      vi.advanceTimersByTime(10_000);
      expect(host.children.map((c) => c.textContent)).toEqual(['broken']);
      const node = err.node as unknown as FakeElement;
      expect(node.classList.contains('oac-toast--error')).toBe(true);
      (node.querySelector('.oac-toast__x') as FakeElement).click();
      expect(node.classList.contains('is-out')).toBe(true);
      vi.advanceTimersByTime(200);
      expect(host.children).toHaveLength(0);
    } finally {
      vi.useRealTimers();
    }
  });

  it('a listener that throws does not silence the others or leave the shell half-updated', () => {
    const store = new MemoryStorage();
    const { w, root } = make({ persist: true, storage: store });
    const after = vi.fn();
    w.on('interval', () => { throw new Error('host bug'); });
    w.on('interval', after);
    expect(() => w.setInterval('1h')).toThrow('host bug');
    expect(after).toHaveBeenCalledWith({ interval: '1h' });
    expect(w.interval()).toBe('1h');
    expect(root.querySelector('.oac-statusline__iv')?.textContent).toBe('1h');
    w.destroy();
    expect(JSON.parse(store.map.get(`${STORAGE_PREFIX}default:${STATE_KEY}`) as string).interval).toBe('1h');
  });

  it('the theme button shows the theme a click would switch to, as a sun or a moon', () => {
    const { w, root } = make();
    const btn = root.querySelector('.oac-topbar__theme') as FakeElement;
    const glyph = (): string | undefined => btn.querySelector('.oac-glyph')?.innerHTML;
    expect(glyph()).toBe(chromeIconSvg('sun'));
    expect(btn.textContent).toBe('');
    btn.click();
    expect(w.theme()).toBe('light');
    expect(glyph()).toBe(chromeIconSvg('moon'));
    expect(btn.getAttribute('aria-label')).toBe('Switch to the dark theme');
  });
});

describe('destroy', () => {
  it('takes down the chart, the chrome, the keymap and the root, once', () => {
    const { w, root, container, chartEl } = make();
    fire(root, 'pointerenter');
    const off = vi.fn();
    w.on('symbol', off);
    w.destroy();
    expect(w.isDestroyed).toBe(true);
    expect(w.chart.isDestroyed).toBe(true);
    expect(container.children).toHaveLength(0);
    fireKey(chartEl, 't', { altKey: true });
    expect(w.draw.activeTool()).toBeNull();
    expect(() => w.destroy()).not.toThrow();
  });
});
