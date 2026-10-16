/**
 * Integration wiring for the 1.3.0 additions.
 *
 * Three things are under test here, and only the first is about linking:
 *
 * 1. A `LinkGroup` driving two **real** `Chart` instances that hold different
 *    data (an hourly leader inside a daily follower's history), because the
 *    naive implementation of every channel works perfectly on two charts of the
 *    same symbol and interval and is wrong everywhere else.
 * 2. The signals the group needs the core to be honest about: a viewport event
 *    on every viewport mutation, not only on a gesture, and an explicit
 *    destruction flag instead of an inference from an empty pane list.
 * 3. That every new public symbol is reachable from the package entry. A module
 *    nobody can import has shipped here twice.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { Chart } from '../src/core/chart';
import { fakeDocument, pointer } from './helpers/fake-dom';
import type { RecordingContext } from './helpers/fake-ctx';
import type { Bar } from '../src/model/bar';
import type { IPrimitive, PrimitiveHost, ZOrder } from '../src/primitives/primitive';
import {
  createLinkGroup, LinkGroup, LinkCrosshair, LINK_CROSSHAIR_ALPHA,
  followerIndex, followerRange,
  withBarCache, BarCache, barCacheKey, barCloseSec,
  registerInterval, unregisterInterval, registeredIntervals, resolveInterval,
  tryResolveInterval, isKnownInterval, bucketStartOf, nextBucketStart,
  isTimeBucketed, UnknownIntervalError,
  type InvalidationLevel, ShortcutManager, BUILTIN_COMMANDS, isReservedCombo,
} from '../src/index';
import type {
  LinkChart, LinkOptions, LinkMemberOptions, ResolvedLinkOptions,
  LinkDataLayer, LinkMissingPolicy,
  BarCacheOptions, BarCacheStore, BarCacheStats, CachedBars, CachedBarsRequest, MaybePromise,
  IntervalDescriptor, Bucketing, IntervalBucketing, CalendarBucketing,
  TickCountBucketing, VolumeBucketing, CalendarUnit, TickBarOptions,
} from '../src/index';

const HOUR = 3600;
const DAY = 86400;
/** A Monday 00:00 UTC, so "day N" below is a real calendar day apart. */
const T0 = 1700438400;

const bar = (time: number, value: number): Bar => ({
  time, open: value, high: value + 1, low: value - 1, close: value,
});

/**
 * A chart that paints synchronously, so a frame has run (and every primitive
 * has drawn) by the time a call returns. Without `applySize` every price scale
 * sits on its 0..1 placeholder and nothing here would be measuring anything.
 */
function makeChart(): { chart: Chart; el: HTMLElement } {
  const el = fakeDocument().createElement('div');
  const chart = new Chart(el, {
    document: fakeDocument(),
    pixelRatio: () => 1,
    shortcuts: { scope: 'global' },
    raf: { schedule: (cb: () => void) => { cb(); return 1; }, cancel: () => {} },
  });
  chart.applySize(800, 600);
  return { chart, el };
}

function loaded(bars: readonly Bar[]): { chart: Chart; el: HTMLElement } {
  const made = makeChart();
  made.chart.addSeries('candlestick').setData(bars);
  made.chart.fitContent();
  return made;
}

/** Dispatch a real pointer move at a container x, driving the crosshair path. */
function hoverAt(el: HTMLElement, x: number, y = 200): void {
  (el as unknown as { dispatch(t: string, e: unknown): void })
    .dispatch('pointermove', pointer('move', x, y, { buttons: 0 }));
}

const rec = (ctx: CanvasRenderingContext2D): RecordingContext => ctx as unknown as RecordingContext;

/** 20 daily bars, days 0..19. */
const dailyBars = Array.from({ length: 20 }, (_, d) => bar(T0 + d * DAY, 100 + d));
/** 48 hourly bars covering days 5 and 6 only: a different interval and depth. */
const hourlyBars = Array.from({ length: 48 }, (_, h) => bar(T0 + 5 * DAY + h * HOUR, 500 + h));
/** Five days at two resolutions, for windows both charts can actually hold. */
const fourHourBars = Array.from({ length: 30 }, (_, i) => bar(T0 + i * 4 * HOUR, 300 + i));
const deepHourlyBars = Array.from({ length: 120 }, (_, i) => bar(T0 + i * HOUR, 400 + i));

beforeEach(() => {
  vi.stubGlobal('window', {}); // Chart._attachInput bails when window is undefined
});
afterEach(() => {
  vi.unstubAllGlobals();
});

describe('the engine can convert an instant a chart has no bar for', () => {
  it('round-trips time to a fractional logical index and back, inside a gap and outside coverage', () => {
    const { chart } = loaded(dailyBars);
    const layer = chart.dataLayer;

    // Midday on day 3: no bar has that second, and a link group needs a number
    // for it or it cannot place a leader's cursor at all.
    const noon = T0 + 3 * DAY + 12 * HOUR;
    expect(layer.timeToIndex(noon)).toBeUndefined();
    const fractional = layer.timeToIndexFloat(noon);
    expect(fractional).toBeCloseTo(3.5, 9);
    expect(layer.indexToTimeFloat(fractional)).toBeCloseTo(noon, 6);

    // Past the last bar the axis extrapolates at the edge spacing rather than
    // clamping, so a window scrolled into the empty margin still has a time.
    const future = T0 + 25 * DAY;
    expect(layer.timeToIndexFloat(future)).toBeCloseTo(25, 9);
    expect(layer.indexToTimeFloat(25)).toBeCloseTo(future, 6);

    chart.destroy();
  });

  it('a real Chart satisfies the structural contracts the link group is written against', () => {
    const { chart } = loaded(dailyBars);
    // Compile-time: the group takes these shapes, not the Chart class, and a
    // drift in either signature has to fail here rather than in a host.
    const asLinkChart: LinkChart = chart;
    const asLinkLayer: LinkDataLayer = chart.dataLayer;
    expect(asLinkChart.panes().length).toBeGreaterThan(0);
    expect(asLinkLayer.length).toBe(dailyBars.length);
    chart.destroy();
  });
});

describe('two real charts linked by time', () => {
  it('mirrors the hovered instant onto a follower with a different interval and depth', () => {
    const leader = loaded(hourlyBars);
    const follower = loaded(dailyBars);
    const group = createLinkGroup({ viewport: false });
    group.add(leader.chart);
    group.add(follower.chart);

    // Hour 30 of the leader is day 6 + 6h. The follower's nearest bar in time is
    // day 6 (6h away), not day 7 (18h away).
    const instant = hourlyBars[30].time;
    hoverAt(leader.el, leader.chart.timeToCoordinate(instant));

    const idx = group.crosshairIndex(follower.chart);
    expect(idx).not.toBeNull();
    expect(follower.chart.dataLayer.indexToTime(idx as number)).toBe(T0 + 6 * DAY);
    // The failure this whole module exists to prevent: index 30 copied straight
    // across would land on day 30, which the follower does not even have.
    expect(idx).not.toBe(30);
    // The leader draws its own, real crosshair and must not also get a linked one.
    expect(group.crosshairIndex(leader.chart)).toBeNull();

    group.destroy();
    leader.chart.destroy();
    follower.chart.destroy();
  });

  it('draws the linked line on the follower at its own bar, on the overlay canvas', () => {
    const leader = loaded(hourlyBars);
    const follower = loaded(dailyBars);
    const group = createLinkGroup({ viewport: false });
    group.add(leader.chart);
    group.add(follower.chart);

    const pane = follower.chart.panes()[0];
    const top = rec(pane.top.ctx);
    const base = rec(pane.base.ctx);
    // One move first: attaching the primitive is a one-off base repaint, and
    // the claim under test is about the steady state, every mousemove after it.
    hoverAt(leader.el, leader.chart.timeToCoordinate(hourlyBars[10].time));
    const baseOpsBefore = base.ops.length;
    top.ops = [];

    hoverAt(leader.el, leader.chart.timeToCoordinate(hourlyBars[30].time));

    const idx = group.crosshairIndex(follower.chart) as number;
    const expectedX = Math.round(follower.chart.timeScale.indexToX(idx)) + 0.5;
    const verticals = top.ops.filter((o) => o.type === 'moveTo' && o.args[0] === expectedX && o.args[1] === 0);
    expect(verticals.length).toBeGreaterThan(0);
    // Vertical only: an instant is shared between instruments, a price is not.
    expect(top.ops.some((o) => o.type === 'moveTo' && o.args[0] === 0)).toBe(false);
    // A 'top' primitive must not drag the series redraw along with it.
    expect(base.ops.length).toBe(baseOpsBefore);

    group.destroy();
    leader.chart.destroy();
    follower.chart.destroy();
  });

  it('shows nothing for an instant outside the follower coverage', () => {
    const leader = loaded(dailyBars);
    // The follower starts where the leader is half way through its history.
    const late = Array.from({ length: 10 }, (_, d) => bar(T0 + (10 + d) * DAY, 200 + d));
    const follower = loaded(late);
    const group = createLinkGroup({ viewport: false });
    group.add(leader.chart);
    group.add(follower.chart);

    hoverAt(leader.el, leader.chart.timeToCoordinate(dailyBars[2].time));
    expect(group.crosshairIndex(follower.chart)).toBeNull();

    hoverAt(leader.el, leader.chart.timeToCoordinate(dailyBars[12].time));
    expect(group.crosshairIndex(follower.chart)).toBe(2);

    group.destroy();
    leader.chart.destroy();
    follower.chart.destroy();
  });

  it('mirrors a wall-clock window, not a logical range', () => {
    const leader = loaded(fourHourBars);
    const follower = loaded(deepHourlyBars);
    const group = createLinkGroup();
    group.add(leader.chart);
    group.add(follower.chart);

    // Leader shows its bars 3..18, i.e. T0+12h through T0+72h.
    leader.chart.setVisibleLogicalRange({ from: 3, to: 18 });

    const fr = follower.chart.getVisibleLogicalRange();
    const fLayer = follower.chart.dataLayer;
    expect(fLayer.indexToTimeFloat(fr.from)).toBeCloseTo(T0 + 12 * HOUR, 0);
    expect(fLayer.indexToTimeFloat(fr.to)).toBeCloseTo(T0 + 72 * HOUR, 0);
    // 15 four-hour bars are 60 hourly bars: copying the leader's logical range
    // across would have shown the follower 15 hours of the wrong day.
    expect(fr.to - fr.from).toBeCloseTo(60, 6);

    group.destroy();
    leader.chart.destroy();
    follower.chart.destroy();
  });

  it('follows fitContent and a keyboard pan, not only a drag or a wheel', () => {
    const leader = loaded(dailyBars);
    const follower = loaded(dailyBars.map((b) => bar(b.time, b.close * 3)));
    const group = createLinkGroup({ crosshair: false });
    group.add(leader.chart);
    group.add(follower.chart);

    // Put the two charts deliberately out of step, then use each entry point.
    follower.chart.setVisibleLogicalRange({ from: 0, to: 4 });
    leader.chart.fitContent();
    expect(follower.chart.getVisibleLogicalRange().to)
      .toBeCloseTo(leader.chart.getVisibleLogicalRange().to, 6);

    const before = follower.chart.getVisibleLogicalRange().to;
    (leader.el as unknown as { dispatch(t: string, e: unknown): void })
      .dispatch('keydown', { code: 'ArrowLeft', preventDefault(): void {}, target: null });
    expect(leader.chart.getVisibleLogicalRange().to).toBeLessThan(before);
    expect(follower.chart.getVisibleLogicalRange().to)
      .toBeCloseTo(leader.chart.getVisibleLogicalRange().to, 6);

    // resetScale is the third programmatic route, and the double-click one.
    follower.chart.setVisibleLogicalRange({ from: 0, to: 3 });
    leader.chart.resetScale();
    expect(follower.chart.getVisibleLogicalRange().to)
      .toBeCloseTo(leader.chart.getVisibleLogicalRange().to, 6);

    group.destroy();
    leader.chart.destroy();
    follower.chart.destroy();
  });

  it('does not oscillate: the follower move does not move the leader back', () => {
    const a = loaded(dailyBars);
    const b = loaded(hourlyBars);
    const group = createLinkGroup({ crosshair: false });
    group.add(a.chart);
    group.add(b.chart);

    let aEvents = 0;
    a.chart.on('pan', () => { aEvents++; });
    a.chart.on('zoom', () => { aEvents++; });
    // Span 15 of 20 bars: a much tighter window would clamp on maxBarSpacing
    // and the assertion would be about the clamp, not about the echo guard.
    const wanted = { from: 4, to: 19 };
    a.chart.setVisibleLogicalRange(wanted);

    expect(aEvents).toBe(1); // one emit, and nothing bounced back to make a second
    const after = a.chart.getVisibleLogicalRange();
    expect(after.from).toBeCloseTo(wanted.from, 6);
    expect(after.to).toBeCloseTo(wanted.to, 6);

    group.destroy();
    a.chart.destroy();
    b.chart.destroy();
  });
});

describe('destruction is announced, not inferred', () => {
  it('exposes isDestroyed, emits destroy once, and drops its listeners', () => {
    const { chart } = loaded(dailyBars);
    let destroys = 0;
    let pans = 0;
    chart.on('destroy', () => { destroys++; });
    chart.on('pan', () => { pans++; });

    expect(chart.isDestroyed).toBe(false);
    chart.destroy();
    expect(chart.isDestroyed).toBe(true);
    expect(destroys).toBe(1);

    chart.destroy(); // idempotent
    expect(destroys).toBe(1);

    // Subscriptions on a corpse would otherwise retain every listener closure.
    chart.emit('pan', {});
    expect(pans).toBe(0);
  });

  it('a link group drops a destroyed member instead of calling into it', () => {
    const a = loaded(dailyBars);
    const b = loaded(dailyBars);
    const group = new LinkGroup();
    group.add(a.chart);
    group.add(b.chart);
    expect(group.members()).toHaveLength(2);

    b.chart.destroy();
    expect(b.chart.isDestroyed).toBe(true);
    // Panning the survivor must not throw against the destroyed one.
    a.chart.setVisibleLogicalRange({ from: 2, to: 8 });
    expect(group.members()).toHaveLength(1);
    expect(group.has(b.chart)).toBe(false);

    group.destroy();
    a.chart.destroy();
  });
});

describe('a top-layer primitive repaints only the overlay', () => {
  class Probe implements IPrimitive {
    public host: PrimitiveHost | null = null;
    public constructor(private readonly _z: ZOrder) {}
    public zOrder(): ZOrder { return this._z; }
    public attached(host: PrimitiveHost): void { this.host = host; }
    public detached(): void { this.host = null; }
    public draw(): void { /* nothing to draw: the invalidation level is the subject */ }
  }

  const opsAfterUpdate = (z: ZOrder): { base: number; top: number } => {
    const { chart } = loaded(dailyBars);
    const probe = new Probe(z);
    chart.addPrimitive(probe, 0);
    const pane = chart.panes()[0];
    const base = rec(pane.base.ctx);
    const top = rec(pane.top.ctx);
    const b0 = base.ops.length;
    const t0 = top.ops.length;
    probe.host?.requestUpdate();
    const out = { base: base.ops.length - b0, top: top.ops.length - t0 };
    chart.destroy();
    return out;
  };

  it('asks for a cursor repaint for top, and a light one for normal', () => {
    const top = opsAfterUpdate('top');
    expect(top.top).toBeGreaterThan(0);
    expect(top.base).toBe(0);

    const normal = opsAfterUpdate('normal');
    expect(normal.base).toBeGreaterThan(0);
  });

  it('LinkCrosshair sits on the top layer at reduced opacity', () => {
    expect(new LinkCrosshair().zOrder()).toBe('top');
    expect(LINK_CROSSHAIR_ALPHA).toBeGreaterThan(0);
    expect(LINK_CROSSHAIR_ALPHA).toBeLessThan(1);
  });
});

describe('the clipboard commands a host has to bind itself', () => {
  it('are bindable today, so no dead entry is needed in DEFAULT_KEYMAP', () => {
    // Copy/cut/paste act on the optional draw tier, which the core cannot call.
    // Listing them as built-ins would put three commands in every shortcuts
    // dialog with nothing behind them, so the host owns them. This is the proof
    // that owning them costs the host nothing but the handler.
    const combos = ['Mod+KeyC', 'Mod+KeyX', 'Mod+KeyV'];
    for (const combo of combos) {
      expect(isReservedCombo(combo), `${combo} is reserved`).toBe(false);
      expect(BUILTIN_COMMANDS.has(combo)).toBe(false);
    }
    const fired: string[] = [];
    const sc = new ShortcutManager({
      scope: 'hover', // page-level text copy is only intercepted over the chart
      isMac: false,
      customShortcuts: [
        { command: 'copyDrawing', combos: 'Mod+KeyC', onTrigger: () => { fired.push('copy'); } },
        { command: 'cutDrawing', combos: 'Mod+KeyX', onTrigger: () => { fired.push('cut'); } },
        // The draw tier's paste is async; a host handler may return a promise.
        { command: 'pasteDrawing', combos: 'Mod+KeyV', onTrigger: async () => { fired.push('paste'); } },
      ],
    });

    expect(sc.resolve({ code: 'KeyC', ctrlKey: true })).toBe('copyDrawing');
    expect(sc.resolve({ code: 'KeyX', ctrlKey: true })).toBe('cutDrawing');
    expect(sc.resolve({ code: 'KeyV', ctrlKey: true })).toBe('pasteDrawing');
    // No collision with a built-in: plain KeyC still resolves to nothing.
    expect(sc.resolve({ code: 'KeyC' })).toBeNull();

    for (const cmd of ['copyDrawing', 'cutDrawing', 'pasteDrawing']) expect(sc.runCustom(cmd)).toBe(true);
    expect(fired).toEqual(['copy', 'cut', 'paste']);
    expect(sc.list().filter((e) => e.isCustom).map((e) => e.combos[0])).toEqual(combos);
  });
});

describe('public export surface', () => {
  it('resolves every new value export from the package entry', () => {
    const values: Record<string, unknown> = {
      createLinkGroup, LinkGroup, LinkCrosshair, LINK_CROSSHAIR_ALPHA,
      followerIndex, followerRange,
      withBarCache, BarCache, barCacheKey, barCloseSec,
      registerInterval, unregisterInterval, registeredIntervals, resolveInterval,
      tryResolveInterval, isKnownInterval, bucketStartOf, nextBucketStart,
      isTimeBucketed, UnknownIntervalError,
    };
    for (const [name, value] of Object.entries(values)) {
      expect(value, `${name} is not exported from 'openalgo-charts'`).toBeDefined();
    }
    // Reachable is not the same as working: call one from each module through
    // the barrel, since a re-export of the wrong binding is still "defined".
    expect(createLinkGroup().options().whenMissing).toBe('nearest');
    expect(barCacheKey({ symbol: 'X', exchange: 'NSE', interval: '5m', from: 1, to: 2 })).toContain('5m');
    expect(barCloseSec('5m', 1_700_000_000)).toBe(1_700_000_300);
    expect(isKnownInterval('5m')).toBe(true);
    expect(isKnownInterval('bogus')).toBe(false);
    expect(() => resolveInterval('bogus')).toThrow(UnknownIntervalError);
    expect(isTimeBucketed(resolveInterval('5m').bucketing)).toBe(true);
  });

  it('accepts a wrapped feed and a registered interval through the barrel', () => {
    const feed = { getBars: async () => [] as Bar[] };
    const cached = withBarCache(feed, { ttlMs: 60_000 });
    expect(cached).toBeInstanceOf(BarCache);

    // 'Q', not '3M': codes are matched case-insensitively and the built-in
    // token grammar already reads '3m' as three minutes.
    const off = registerInterval({ code: 'Q', bucketing: { mode: 'calendar', unit: 'quarter' } });
    expect(registeredIntervals().some((d) => d.code === 'Q')).toBe(true);
    expect(tryResolveInterval('Q')?.bucketing.mode).toBe('calendar');
    off();
    expect(isKnownInterval('Q')).toBe(false);
    expect(unregisterInterval('Q')).toBe(false); // already gone
  });
});

/**
 * Compile-time only. Every type below has to resolve from the package entry:
 * an unreachable type is the same defect as an unreachable value, and tsc is
 * the only thing that can catch it.
 */
export type NewTypeSurface = [
  LinkChart, LinkOptions, LinkMemberOptions, ResolvedLinkOptions,
  LinkDataLayer, LinkMissingPolicy,
  BarCacheOptions, BarCacheStore, BarCacheStats, CachedBars, CachedBarsRequest,
  MaybePromise<number>,
  IntervalDescriptor, Bucketing, IntervalBucketing, CalendarBucketing,
  TickCountBucketing, VolumeBucketing, CalendarUnit, TickBarOptions,
  InvalidationLevel,
];
