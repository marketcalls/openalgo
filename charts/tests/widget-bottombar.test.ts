/**
 * The widget's bottom bar: preset ranges that set the interval, size the
 * fetch in trading sessions and place the view; Go to beside them; the market
 * status from the instrument calendar, a clock in the chart's zone that opens
 * the timezone choice, and price scale toggles that follow the scale. Also
 * the option that turns it off, the phone layout's sheet that stands in for
 * it, the session shading attached from the calendar, and the status line
 * that says the market status when there is no bar to.
 */
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import type { Bar, BarsRequest, DataFeed } from '../src/index';
import { SessionCalendar } from '../src/feed/instrument';
import { zonedWallClockToUtcSeconds } from '../src/feed/time';
import { SessionShade } from '../src/primitives/session-shade';
import {
  createChartGrid, createWidget, mountBottombar, SAVE_DEBOUNCE_MS, STATE_KEY, STORAGE_PREFIX,
  type StorageLike, type Widget, type WidgetOptions,
} from '../src/widget/index';
import { ensureWindowGlobal, fakeContainer, fakeWidgetDocument, type FakeDocument, type FakeElement } from './helpers/fake-dom-widget';

beforeAll(ensureWindowGlobal);

const IST = 'Asia/Kolkata';
const ist = (y: number, m: number, d: number, hh = 0, mm = 0): number => zonedWallClockToUtcSeconds(y, m, d, hh, mm, 0, IST);
const NSE = new SessionCalendar({ timezone: IST, sessions: ['0915-1530:23456'] });
const SECONDS: Record<string, number> = { '1m': 60, '5m': 300, '15m': 900, '1h': 3600, '1d': 86400, '1w': 604800 };

/**
 * A seeded random walk on NSE hours: every weekday from 1 September 2025, one
 * bar per interval step inside 09:15 to 15:30, or one bar a day at the open.
 */
function sessionBars(interval: string, from: number, to: number, seed = 7): Bar[] {
  const step = SECONDS[interval] ?? 86400;
  const out: Bar[] = [];
  let state = seed;
  let price = 1500;
  const next = (): number => { state = (state * 1103515245 + 12345) % 2147483648; return state / 2147483648; };
  for (let day = 1; day <= 45; day++) {
    const open = ist(2025, 9, day, 9, 15);
    const weekday = new Date((open + 5.5 * 3600) * 1000).getUTCDay();
    if (weekday === 0 || weekday === 6) continue;
    const close = ist(2025, 9, day, 15, 30);
    for (let t = open; t < close; t += step >= 86400 ? close : step) {
      const o = price;
      price = Math.max(1, price * (1 + (next() - 0.5) * 0.004));
      if (t < from || t > to) continue;
      out.push({ time: t, open: o, high: Math.max(o, price) * 1.001, low: Math.min(o, price) * 0.999, close: price, volume: 1000 + Math.round(next() * 5000) });
    }
  }
  return out;
}

/** Weekly bars from October 2005 to September 2025, a seeded walk: twenty years, more than a plot is wide. */
function weeklyBars(from: number, to: number): Bar[] {
  const out: Bar[] = [];
  let state = 11;
  let price = 1200;
  const next = (): number => { state = (state * 1103515245 + 12345) % 2147483648; return state / 2147483648; };
  for (let t = ist(2005, 10, 3, 9, 15); t <= ist(2025, 9, 29, 9, 15); t += 7 * 86400) {
    const o = price;
    price = Math.max(1, price * (1 + (next() - 0.49) * 0.06));
    if (t < from || t > to) continue;
    out.push({ time: t, open: o, high: Math.max(o, price) * 1.01, low: Math.min(o, price) * 0.99, close: price, volume: 1e6 + Math.round(next() * 5e6) });
  }
  return out;
}
const WEEKS = weeklyBars(-Infinity, Infinity).length;

function recordingFeed(requests: BarsRequest[]): DataFeed {
  return {
    getBars: async request => {
      requests.push(request);
      return sessionBars(request.interval, request.from ?? -Infinity, request.to ?? Infinity, request.symbol.length);
    },
  };
}

class MemoryStorage implements StorageLike {
  public readonly map = new Map<string, string>();
  public getItem(k: string): string | null { return this.map.get(k) ?? null; }
  public setItem(k: string, v: string): void { this.map.set(k, v); }
  public removeItem(k: string): void { this.map.delete(k); }
}

/** Wednesday 1 October 2025, 15:30 IST: the close of a full session. */
let nowMs = ist(2025, 10, 1, 15, 30) * 1000;
const live: Widget[] = [];
afterEach(() => {
  for (const w of live.splice(0)) if (!w.isDestroyed) w.destroy();
  vi.useRealTimers();
  nowMs = ist(2025, 10, 1, 15, 30) * 1000;
});

interface Made { w: Widget; doc: FakeDocument; root: FakeElement }

function make(opts: WidgetOptions = {}, doc: FakeDocument = fakeWidgetDocument()): Made {
  const container = fakeContainer(doc);
  const w = createWidget(container as unknown as HTMLElement, {
    document: doc as unknown as Document, pixelRatio: () => 1,
    raf: { schedule: (cb: () => void) => { cb(); return 1; }, cancel: () => {} },
    symbol: 'NIFTY', exchange: 'NSE', interval: '1d', now: () => nowMs, lookbackBars: 60,
    ...opts,
  });
  w.chart.applySize(800, 600);
  live.push(w);
  return { w, doc, root: w.root as unknown as FakeElement };
}

const flush = async (): Promise<void> => { for (let i = 0; i < 40; i++) await Promise.resolve(); };
const bar = (root: FakeElement): FakeElement => root.querySelector('.oac-bottombar')!;
const rangeButton = (root: FakeElement, id: string): FakeElement => root.querySelector(`.oac-bottombar__range[data-range="${id}"]`)!;
const scaleButton = (root: FakeElement, id: string): FakeElement => root.querySelector(`.oac-bottombar__icon[data-scale="${id}"]`)!;
const axis = (w: Widget) => w.chart.priceAxisState(w.chart.primaryPaneIndex(), 'right')!;

describe('the frame', () => {
  it('puts the bar under the chart and above the status line, on by default', () => {
    const { root } = make();
    const order = root.children.map(c => c.className.split(' ')[0]);
    expect(order.indexOf('oac-bottombar')).toBe(order.indexOf('oac-stage') + 1);
    expect(order.indexOf('oac-statusline')).toBe(order.indexOf('oac-bottombar') + 1);
    expect(root.classList.contains('has-bottombar')).toBe(true);
    expect(bar(root).getAttribute('role')).toBe('toolbar');
    expect(root.querySelectorAll('.oac-bottombar__range').map(b => b.textContent)).toEqual(['1D', '5D', '1M', '3M', '6M', 'YTD', '1Y', '5Y', 'All']);
  });

  it('leaves the bar out, and Go to in the top bar, with the option off', () => {
    const { root } = make({ bottombar: false });
    expect(root.querySelector('.oac-bottombar')).toBeNull();
    expect(root.classList.contains('has-bottombar')).toBe(false);
    expect(root.querySelector('.oac-topbar__goto')).not.toBeNull();
  });

  it('names a range apart from an interval of the same text, before and after its tip shows', () => {
    const { root } = make();
    const day = rangeButton(root, '1D');
    expect(day.textContent).toBe('1D');
    expect(day.getAttribute('aria-label')).toBe('Range 1D');
    day.focus();
    // A shown tip writes its title back as the name: the title is the name.
    expect(day.getAttribute('aria-label')).toBe('Range 1D');
    const tip = root.querySelector('.oac-tip')!;
    expect(tip.textContent).toContain('Range 1D');
    expect(tip.querySelector('.oac-tip__sub')!.textContent).toBe('One trading session');
    rangeButton(root, '5D').focus();
    expect(root.querySelector('.oac-tip__sub')!.textContent).toBe('5 trading sessions');
  });

  it('takes a host list of ranges, and none leaves the range buttons out', () => {
    const custom = make({ ranges: [{ id: 'wk', label: 'Week', interval: '15m', unit: 'session', count: 5 }] }).root;
    expect(custom.querySelectorAll('.oac-bottombar__range').map(b => b.textContent)).toEqual(['Week']);
    expect(make({ ranges: [] }).root.querySelector('.oac-bottombar__ranges')).toBeNull();
  });

  it('gives a grid cell no bar of its own', () => {
    const doc = fakeWidgetDocument();
    const grid = createChartGrid(fakeContainer(doc) as unknown as HTMLElement, { document: doc as unknown as Document, preset: '1x2' });
    try {
      expect(grid.cells()).toHaveLength(2);
      for (const cell of grid.cells()) expect((cell.widget.root as unknown as FakeElement).querySelector('.oac-bottombar')).toBeNull();
    } finally { grid.destroy(); }
  });
});

describe('preset ranges', () => {
  it('sets the interval, fetches one NSE session at one minute and fits it in view', async () => {
    const requests: BarsRequest[] = [];
    const { w, root } = make({ feed: recordingFeed(requests), sessionCalendar: NSE });
    await flush();
    rangeButton(root, '1D').click();
    await flush();
    expect(w.interval()).toBe('1m');
    expect(w.range()).toBe('1D');
    const last = requests[requests.length - 1];
    expect(last).toMatchObject({ interval: '1m', from: ist(2025, 10, 1, 9, 15), to: ist(2025, 10, 1, 15, 30) });
    expect(w.series.getData()).toHaveLength(375);
    const view = w.chart.getVisibleLogicalRange();
    expect(view.from).toBeCloseTo(-0.5, 6);
    expect(view.to).toBeCloseTo(374.5, 6);
    expect(rangeButton(root, '1D').getAttribute('aria-pressed')).toBe('true');
    expect(rangeButton(root, '5D').getAttribute('aria-pressed')).toBe('false');
    expect(root.querySelector('.oac-statusline__msg')!.textContent).toContain('1D:');
  });

  it('walks five sessions back across the weekend', async () => {
    const requests: BarsRequest[] = [];
    const { w } = make({ feed: recordingFeed(requests), sessionCalendar: NSE });
    await flush();
    expect(await w.setRange('5D')).toMatchObject({ status: 'placed', from: ist(2025, 9, 25, 9, 15) });
    expect(requests[requests.length - 1]).toMatchObject({ interval: '5m', from: ist(2025, 9, 25, 9, 15) });
    expect(w.series.getData()).toHaveLength(5 * 75);
  });

  it('never fetches less than an ordinary load', async () => {
    const requests: BarsRequest[] = [];
    // An hour into the session a day is 45 minutes; the ordinary lookback reaches further.
    nowMs = ist(2025, 10, 1, 10, 0) * 1000;
    const { w } = make({ feed: recordingFeed(requests), sessionCalendar: NSE, lookbackBars: 500 });
    await flush();
    await w.setRange('1D');
    expect(requests[requests.length - 1]).toMatchObject({ interval: '1m', from: ist(2025, 10, 1, 10, 0) - 500 * 60 });
  });

  it('leaves the range on a manual interval change, and the next load is the ordinary lookback', async () => {
    const requests: BarsRequest[] = [];
    const { w, root } = make({ feed: recordingFeed(requests), sessionCalendar: NSE });
    await flush();
    await w.setRange('1D');
    w.setInterval('5m');
    await flush();
    expect(w.range()).toBeNull();
    expect(rangeButton(root, '1D').getAttribute('aria-pressed')).toBe('false');
    const now = ist(2025, 10, 1, 15, 30);
    expect(requests[requests.length - 1]).toMatchObject({ interval: '5m', from: now - 60 * 300, to: now });
  });

  it("does not come back when the interval returns to the range's by hand", async () => {
    const { w } = make({ feed: recordingFeed([]), sessionCalendar: NSE });
    await flush();
    await w.setRange('1D');
    w.setInterval('5m');
    w.setInterval('1m');
    expect(w.range()).toBeNull();
  });

  it('keeps the range across a symbol change and places it on the new instrument', async () => {
    const requests: BarsRequest[] = [];
    const { w } = make({ feed: recordingFeed(requests), sessionCalendar: NSE });
    await flush();
    await w.setRange('1D');
    w.setSymbol('INFY');
    await flush();
    await flush();
    expect(w.range()).toBe('1D');
    expect(requests[requests.length - 1]).toMatchObject({ symbol: 'INFY', interval: '1m', from: ist(2025, 10, 1, 9, 15) });
    const view = w.chart.getVisibleLogicalRange();
    expect(view.to - view.from).toBeCloseTo(375, 6);
  });

  it('asks the source for all its history on the interval already in force, and keeps the latest bars in view', async () => {
    const requests: BarsRequest[] = [];
    const feed: DataFeed = { getBars: async (r) => { requests.push(r); return weeklyBars(r.from ?? -Infinity, r.to ?? Infinity); } };
    const { w } = make({ feed, interval: '1w' });
    await flush();
    expect(w.series.getData()).toHaveLength(60);
    const result = await w.setRange('ALL');
    await flush();
    // Every bar the source has, not the ordinary lookback already loaded.
    expect(w.series.getData()).toHaveLength(WEEKS);
    const bars = w.series.getData();
    // Twenty years is wider than the plot: the oldest bars give way, the last price stays.
    expect(result).toMatchObject({ status: 'partial', clipped: true, to: bars[bars.length - 1].time });
    expect(w.chart.getVisibleLogicalRange().to).toBeCloseTo(bars.length - 0.5, 6);
    expect(result.from).toBeGreaterThan(bars[0].time);
  });

  it('keeps the latest bars in view when a range from another interval is wider than the plot', async () => {
    const feed: DataFeed = { getBars: async r => weeklyBars(r.from ?? -Infinity, r.to ?? Infinity) };
    const { w } = make({ feed, interval: '1d' });
    await flush();
    const result = await w.setRange('ALL');
    const bars = w.series.getData();
    expect(w.interval()).toBe('1w');
    expect(bars).toHaveLength(WEEKS);
    expect(result).toMatchObject({ status: 'partial', clipped: true, to: bars[bars.length - 1].time });
    const view = w.chart.getVisibleLogicalRange();
    expect(view.to).toBeCloseTo(bars.length - 0.5, 6);
    expect(result.from).toBe(w.chart.dataLayer.indexToTime(Math.ceil(view.from + 0.5)));
  });

  it('refuses an unknown range without touching the chart', async () => {
    const { w } = make();
    expect(await w.setRange('nope')).toEqual({ status: 'invalid' });
    expect(w.interval()).toBe('1d');
    expect(w.range()).toBeNull();
  });

  it('counts the dates of the bars when the widget has no calendar', async () => {
    const requests: BarsRequest[] = [];
    // Saturday: the last session is Friday's, whatever the clock says.
    nowMs = ist(2025, 10, 4, 12, 0) * 1000;
    const { w } = make({ feed: recordingFeed(requests) });
    await flush();
    expect(await w.setRange('1D')).toMatchObject({ status: 'placed', from: ist(2025, 10, 3, 9, 15) });
  });
});

describe('the session calendar', () => {
  it('applies a per-instrument calendar on the first symbol and on every change', () => {
    const us = new SessionCalendar({ timezone: 'America/New_York', sessions: ['0930-1600:23456'] });
    const asked: string[] = [];
    const { w } = make({ sessionCalendar: ({ symbol, exchange }) => { asked.push(`${exchange}:${symbol}`); return exchange === 'NSE' ? NSE : us; } });
    expect(w.chart.dataLayer.sessionCalendar).toBe(NSE);
    w.setSymbol('AAPL', 'NASDAQ');
    expect(w.chart.dataLayer.sessionCalendar).toBe(us);
    expect(asked).toEqual(['NSE:NIFTY', 'NASDAQ:AAPL']);
  });

  it('leaves the chart\'s calendar to the host without the option', () => {
    const { w } = make();
    w.chart.setSessionCalendar(NSE);
    w.setSymbol('INFY');
    expect(w.chart.dataLayer.sessionCalendar).toBe(NSE);
  });

  it('attaches session shading by default and not with the option off', () => {
    const shades = (w: Widget): number => w.chart.panes().flatMap(p => p.primitives()).filter(p => p instanceof SessionShade).length;
    expect(shades(make().w)).toBe(1);
    expect(shades(make({ sessionShading: false }).w)).toBe(0);
  });
});

describe('the market status and the clock', () => {
  it('reads the status from the calendar and follows it past the close', () => {
    vi.useFakeTimers();
    nowMs = ist(2025, 10, 1, 15, 25) * 1000;
    const { w, root } = make({ sessionCalendar: NSE });
    const status = root.querySelector('.oac-bottombar__status')!;
    expect(status.hidden).toBe(false);
    expect(status.dataset.phase).toBe('regular');
    // A status region: a valid holder of its full reading as a name, and a phase change is announced.
    expect(status.getAttribute('role')).toBe('status');
    expect(status.getAttribute('aria-label')).toBe('Market open, closes 15:30');
    expect(status.querySelector('b')!.textContent).toBe('Market open');
    expect(status.querySelector('.oac-bottombar__detail')!.textContent).toBe('closes 15:30');
    expect(root.querySelector('.oac-bottombar__time')!.textContent).toBe('15:25:00');
    expect(root.querySelector('.oac-bottombar__clock small')!.textContent).toBe('UTC+5:30');
    nowMs = ist(2025, 10, 1, 15, 31) * 1000;
    vi.advanceTimersByTime(1100);
    expect(status.dataset.phase).toBe('closed');
    expect(status.querySelector('b')!.textContent).toBe('Market closed');
    expect(status.querySelector('.oac-bottombar__detail')!.textContent).toBe('opens Thu 09:15');
    expect(root.querySelector('.oac-bottombar__time')!.textContent).toBe('15:31:00');
    // The settings dialog's "Session state" switch hides it.
    w.chart.setStatusLineOptions({ marketStatus: false });
    expect(status.hidden).toBe(true);
  });

  it('shows no status without a calendar, and none from a calendar that cannot answer', () => {
    expect(make().root.querySelector('.oac-bottombar__status')!.hidden).toBe(true);
    const broken = { sessionFrom: () => null, phaseSpans: (): never => { throw new Error('a window the clock change removes'); } };
    expect(make({ sessionCalendar: broken }).root.querySelector('.oac-bottombar__status')!.hidden).toBe(true);
  });

  it('opens the timezone choice from the clock and saves the zone picked', () => {
    vi.useFakeTimers();
    const store = new MemoryStorage();
    const { w, root } = make({ persist: 'bar', storage: store });
    const clock = root.querySelector('.oac-bottombar__clock')!;
    expect(clock.getAttribute('aria-label')).toBe('Timezone: Asia/Kolkata');
    clock.click();
    const menu = root.querySelector('.oac-menu')!;
    const rows = menu.querySelectorAll('.oac-menu__row');
    expect(rows.find(r => r.getAttribute('aria-checked') === 'true')!.querySelector('.oac-menu__label')!.textContent).toBe('Asia/Kolkata');
    rows.find(r => r.querySelector('.oac-menu__label')!.textContent === 'America/New_York')!.click();
    expect(w.chart.timezone()).toBe('America/New_York');
    expect(root.querySelector('.oac-bottombar__time')!.textContent).toBe('06:00:00');
    expect(root.querySelector('.oac-bottombar__clock small')!.textContent).toBe('UTC-4');
    vi.advanceTimersByTime(SAVE_DEBOUNCE_MS + 1);
    const saved = JSON.parse(store.map.get(`${STORAGE_PREFIX}bar:${STATE_KEY}`)!);
    expect(saved.chart.timezone).toBe('America/New_York');
  });
});

describe('the price scale toggles', () => {
  it('drive the price scale and follow it', async () => {
    vi.useFakeTimers();
    const { w, root } = make();
    w.series.setData(sessionBars('1d', -Infinity, Infinity));
    vi.advanceTimersByTime(1100);
    expect(scaleButton(root, 'auto').getAttribute('aria-pressed')).toBe('true');
    // The axis menu and the settings say the same.
    expect(scaleButton(root, 'auto').getAttribute('aria-label')).toBe('Auto-fit to the data');
    scaleButton(root, 'log').click();
    await flush();
    expect(axis(w).mode).toBe('logarithmic');
    expect(scaleButton(root, 'log').getAttribute('aria-pressed')).toBe('true');
    scaleButton(root, 'percent').click();
    await flush();
    expect(axis(w).mode).toBe('percentage');
    expect(scaleButton(root, 'log').getAttribute('aria-pressed')).toBe('false');
    expect(scaleButton(root, 'percent').getAttribute('aria-pressed')).toBe('true');
    scaleButton(root, 'percent').click();
    await flush();
    expect(axis(w).mode).toBe('linear');
    // Each mode is a step on the chart's timeline, and an undo shows at once.
    w.history.undo();
    expect(axis(w).mode).toBe('percentage');
    expect(scaleButton(root, 'percent').getAttribute('aria-pressed')).toBe('true');
    w.chart.setPriceAxisOptions(w.chart.primaryPaneIndex(), 'right', { mode: 'logarithmic' });
    expect(scaleButton(root, 'log').getAttribute('aria-pressed')).toBe('true');
    scaleButton(root, 'auto').click();
    expect(axis(w).autoFit).toBe(false);
    expect(scaleButton(root, 'auto').getAttribute('aria-pressed')).toBe('false');
    // Resetting the view turns auto-fit back on with no event of its own; the next tick shows it.
    w.chart.resetScale();
    vi.advanceTimersByTime(1100);
    expect(scaleButton(root, 'auto').getAttribute('aria-pressed')).toBe('true');
  });

  it('take a mode before any data, which the bars then land in', () => {
    const { w, root } = make();
    expect(scaleButton(root, 'log').getAttribute('aria-disabled')).toBe('false');
    scaleButton(root, 'log').click();
    w.series.setData(sessionBars('1d', -Infinity, Infinity));
    expect(axis(w).mode).toBe('logarithmic');
    expect(scaleButton(root, 'log').getAttribute('aria-pressed')).toBe('true');
  });
});

describe('the phone layout', () => {
  it('lists the bar\'s controls in the More sheet', async () => {
    const requests: BarsRequest[] = [];
    const { w, root } = make({ mobile: 'always', feed: recordingFeed(requests), sessionCalendar: NSE });
    await flush();
    root.querySelector('[data-mobile-action="more"]')!.click();
    const sheet = root.querySelector('.oac-mobile-sheet')!;
    expect(sheet.querySelector('.oac-mobile-sheet__note')!.textContent).toContain('Market closed');
    expect(sheet.querySelector('.oac-mobile-sheet__note')!.textContent).toContain('15:30 UTC+5:30');
    expect(sheet.querySelectorAll('[data-mobile-action="range"]').map(b => b.dataset.range)).toEqual(['1D', '5D', '1M', '3M', '6M', 'YTD', '1Y', '5Y', 'ALL']);
    expect(sheet.querySelectorAll('[data-mobile-action="scale"]').map(b => b.dataset.scale)).toEqual(['auto', 'log', 'percent']);
    sheet.querySelector('[data-mobile-action="scale"][data-scale="log"]')!.click();
    expect(axis(w).mode).toBe('logarithmic');
    expect(root.querySelector('[data-mobile-action="scale"][data-scale="log"]')!.getAttribute('aria-pressed')).toBe('true');
    root.querySelector('[data-mobile-action="range"][data-range="5D"]')!.click();
    await flush();
    expect(w.range()).toBe('5D');
    root.querySelector('[data-mobile-action="more"]')!.click();
    expect(root.querySelector('[data-mobile-action="range"][data-range="5D"]')!.getAttribute('aria-pressed')).toBe('true');
    root.querySelector('[data-mobile-action="timezone"]')!.click();
    root.querySelector('[data-mobile-action="pick-zone"][data-zone="Europe/London"]')!.click();
    expect(w.chart.timezone()).toBe('Europe/London');
  });

  it('keeps the bar in the phone layout of a widget with no top bar, which has no More sheet to take it', () => {
    const { root } = make({ mobile: 'always', topbar: false });
    expect(root.querySelector('[data-mobile-action="more"]')).toBeNull();
    expect(bar(root).classList.contains('is-kept')).toBe(true);
    expect(bar(make({ mobile: 'always' }).root).classList.contains('is-kept')).toBe(false);
  });

  it('leaves the rows out with the bar off', () => {
    const { root } = make({ mobile: 'always', bottombar: false });
    root.querySelector('[data-mobile-action="more"]')!.click();
    expect(root.querySelector('[data-mobile-action="range"]')).toBeNull();
    expect(root.querySelector('.oac-mobile-sheet__note')).toBeNull();
  });
});

describe('the status line without a bar', () => {
  it('says the market status from the calendar when the bar is off', () => {
    vi.useFakeTimers();
    nowMs = ist(2025, 10, 1, 15, 29) * 1000;
    const { root } = make({ bottombar: false, sessionCalendar: NSE });
    const market = root.querySelector('.oac-statusline__market')!;
    expect(market.hidden).toBe(false);
    expect(market.textContent).toBe('Market open · closes 15:30');
    nowMs = ist(2025, 10, 1, 15, 31) * 1000;
    vi.advanceTimersByTime(61_000);
    expect(market.textContent).toBe('Market closed · opens Thu 09:15');
  });

  it('leaves it to the bar when there is one', () => {
    const { root } = make({ sessionCalendar: NSE });
    expect(root.querySelector('.oac-statusline__market')!.hidden).toBe(true);
  });
});

describe('a bar over a host\'s own chart', () => {
  it('follows a target getter, so one bar serves whichever chart is focused', () => {
    vi.useFakeTimers();
    const a = make({ sessionCalendar: NSE });
    const b = make();
    b.w.chart.setTimezone('Europe/London');
    let focused: Widget = a.w;
    const host = a.doc.createElement('div') as unknown as HTMLElement;
    const handle = mountBottombar(a.w.context, host, { target: () => focused, ranges: [], now: () => nowMs });
    const el = host as unknown as FakeElement;
    try {
      const time = el.querySelector('.oac-bottombar__time')!;
      expect(time.textContent).toBe('15:30:00');
      expect(el.querySelector('.oac-bottombar__status')!.hidden).toBe(false);
      focused = b.w;
      handle.refresh();
      expect(time.textContent).toBe('11:00:00');
      expect(el.querySelector('.oac-bottombar__status')!.hidden).toBe(true);
      handle.controls.toggleScale('log');
      expect(axis(b.w).mode).toBe('logarithmic');
      expect(axis(a.w).mode).toBe('linear');
    } finally { handle.destroy(); }
  });

  it('closes its open menu and acts on nothing once destroyed', () => {
    const { w, doc } = make({ bottombar: false });
    const root = w.root as unknown as FakeElement;
    const host = doc.createElement('div');
    root.appendChild(host);
    const handle = mountBottombar(w.context, host as unknown as HTMLElement);
    host.querySelector('.oac-bottombar__clock')!.click();
    expect(root.querySelector('.oac-menu')).not.toBeNull();
    handle.destroy();
    // The menu lives in the host's overlay layer, which outlives the bar.
    expect(root.querySelector('.oac-menu')).toBeNull();
    handle.controls.setTimezone('Europe/London');
    handle.controls.toggleScale('log');
    expect(w.chart.timezone()).toBe('Asia/Kolkata');
    expect(axis(w).mode).toBe('linear');
  });

  it('stops its clock when destroyed', () => {
    vi.useFakeTimers();
    const { w, doc } = make({ bottombar: false, statusline: false, sessionShading: false });
    const before = vi.getTimerCount();
    const host = doc.createElement('div') as unknown as HTMLElement;
    const handle = mountBottombar(w.context, host);
    expect(vi.getTimerCount()).toBe(before + 1);
    handle.destroy();
    expect(vi.getTimerCount()).toBe(before);
    expect((host as unknown as FakeElement).children).toHaveLength(0);
  });
});
