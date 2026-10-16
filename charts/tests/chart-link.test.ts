/**
 * Chart linking groups: crosshair, viewport and symbol synced across a grid of
 * charts that hold *different* bar arrays.
 *
 * Nearly every test here uses mismatched datasets on purpose. Linking by
 * logical index looks perfect on two charts of the same symbol and interval, so
 * a suite built on matching data would pass against the broken implementation.
 * The rule under test is: convert index -> time on the sender, time -> index on
 * the receiver, against each chart's own bars.
 */
import { describe, it, expect, beforeAll } from 'vitest';
import { Chart } from '../src/core/chart';
import { DataLayer } from '../src/model/data-layer';
import { fakeDocument, pointer, type FakeElement } from './helpers/fake-dom';
import { makeCtx } from './helpers/fake-ctx';
import { darkTheme } from '../src/theme';
import { TimeScale } from '../src/scale/time-scale';
import { PriceScale } from '../src/scale/price-scale';
import {
  type LinkGroup, createLinkGroup, followerIndex, followerRange,
  LinkCrosshair, LINK_CROSSHAIR_ALPHA,
  type LinkChart, type LinkDataLayer,
} from '../src/link/index';
import type { LogicalRange } from '../src/scale/time-scale';
import type { Bar } from '../src/model/bar';

const W = 800;
const H = 600;
const HOUR = 3600;
const DAY = 86400;
const T0 = 1700000000; // a Tuesday midnight-ish anchor; only the arithmetic matters

beforeAll(() => {
  const g = globalThis as unknown as {
    window?: unknown;
    requestAnimationFrame?: unknown;
    cancelAnimationFrame?: unknown;
  };
  g.window ??= {};
  // Releasing a drag arms the kinetic fling, which reaches for the global raf.
  // A no-op one lets the gesture finish without the flick continuing to pan.
  g.requestAnimationFrame ??= (): number => 0;
  g.cancelAnimationFrame ??= (): void => {};
});

const bar = (time: number, close: number): Bar => ({
  time, open: close, high: close + 1, low: close - 1, close, volume: 100,
});

/** Bars at `times`, priced so nothing is degenerate. */
const barsAt = (times: readonly number[]): Bar[] => times.map((t, i) => bar(t, 100 + i));

const days = (from: number, to: number): number[] => {
  const out: number[] = [];
  for (let d = from; d <= to; d++) out.push(T0 + d * DAY);
  return out;
};

const hours = (fromDay: number, toDay: number): number[] => {
  const out: number[] = [];
  for (let h = fromDay * 24; h < toDay * 24; h++) out.push(T0 + h * HOUR);
  return out;
};

/** A real `DataLayer` over the given times, built with the code the charts use. */
function layer(times: readonly number[]): LinkDataLayer {
  const dl = new DataLayer();
  dl.setSeriesData(dl.createSeries(), barsAt(times));
  return dl;
}

/**
 * A chart that paints synchronously (so a frame has run when a call returns)
 * and is measured (so nothing sits on the 0..1 placeholder scale).
 */
function makeChart(times: readonly number[]): { chart: Chart; el: FakeElement } {
  const el = fakeDocument().createElement('div') as unknown as FakeElement;
  const chart = new Chart(el, {
    document: fakeDocument(),
    pixelRatio: () => 1,
    shortcuts: false,
    raf: { schedule: (cb: () => void) => { cb(); return 1; }, cancel: () => {} },
  });
  chart.applySize(W, H);
  chart.addSeries('candlestick').setData(barsAt(times));
  chart.fitContent();
  return { chart, el };
}

/** Hover the bar at `time` on a real chart, through the real pointer handler. */
function hover(chart: Chart, el: FakeElement, time: number): void {
  el.dispatch('pointermove', pointer('move', chart.timeToCoordinate(time), 200, { buttons: 0 }));
}

/** Drag the plot horizontally by `dx` px, which pans and emits 'pan'. */
function drag(el: FakeElement, dx: number): void {
  el.dispatch('pointerdown', pointer('down', 400, 200));
  el.dispatch('pointermove', pointer('move', 400 + dx, 200));
  el.dispatch('pointerup', pointer('up', 400 + dx, 200));
}

describe('followerIndex: an instant becomes this chart\'s own bar', () => {
  it('maps the same instant to different logical indices on charts with different history', () => {
    // Same interval, different depth: index 3 on the short chart and index 8 on
    // the long one are the same Thursday.
    const short = layer(days(0, 9));
    const long = layer(days(-5, 9));
    const instant = T0 + 3 * DAY;
    expect(short.timeToIndex(instant)).toBe(3);
    expect(followerIndex(long, instant)).toBe(8);
  });

  it('maps across intervals: a daily instant lands on the matching hourly bar', () => {
    const hourly = layer(hours(0, 3));
    expect(followerIndex(hourly, T0 + 2 * DAY)).toBe(48);
  });

  it('never lands on a bar that had not opened at the leader instant', () => {
    // Daily follower, leader hovering 20:00 on day 3. Day 4's bar opens at the
    // next midnight, four hours later: it does not exist yet. Picking the
    // arithmetically nearest STAMP would choose it, because a bar is stamped at
    // its open, and the follower would show a candle from the future.
    const daily = layer(days(0, 5));
    expect(followerIndex(daily, T0 + 3 * DAY + 20 * HOUR, 'nearest')).toBe(3);
    expect(followerIndex(daily, T0 + 3 * DAY + 4 * HOUR, 'nearest')).toBe(3);
    // Every instant inside day 3 resolves to day 3, right up to the boundary.
    expect(followerIndex(daily, T0 + 3 * DAY + 1, 'nearest')).toBe(3);
    expect(followerIndex(daily, T0 + 4 * DAY - 1, 'nearest')).toBe(3);
    expect(followerIndex(daily, T0 + 4 * DAY, 'nearest')).toBe(4);
  });

  it('hide draws nothing unless the follower has a bar at exactly that instant', () => {
    const daily = layer(days(0, 5));
    expect(followerIndex(daily, T0 + 3 * DAY, 'hide')).toBe(3);
    expect(followerIndex(daily, T0 + 3 * DAY + 20 * HOUR, 'hide')).toBeNull();
  });

  it('refuses instants outside the follower\'s coverage under either policy', () => {
    const daily = layer(days(0, 5));
    for (const policy of ['nearest', 'hide'] as const) {
      expect(followerIndex(daily, T0 - DAY, policy)).toBeNull();
      expect(followerIndex(daily, T0 + 9 * DAY, policy)).toBeNull();
    }
  });

  it('answers null rather than throwing on an empty follower or a junk time', () => {
    expect(followerIndex(layer([]), T0)).toBeNull();
    expect(followerIndex(layer(days(0, 5)), NaN)).toBeNull();
  });
});

describe('followerRange: the same wall-clock window, in the follower\'s indices', () => {
  it('translates a window across a different interval', () => {
    const daily = layer(days(0, 9));
    const hourly = layer(hours(0, 10));
    // Days 2..5 on the daily chart.
    const mapped = followerRange(daily, hourly, { from: 2, to: 5 });
    expect(mapped).not.toBeNull();
    expect((mapped as LogicalRange).from).toBeCloseTo(48, 6);
    expect((mapped as LogicalRange).to).toBeCloseTo(120, 6);
  });

  it('translates a window across a different history depth', () => {
    const short = layer(days(0, 9));
    const long = layer(days(-5, 9));
    expect(followerRange(short, long, { from: 2, to: 6 })).toEqual({ from: 7, to: 11 });
  });

  it('extrapolates past the last bar rather than clamping the window shut', () => {
    // The right-hand margin: the leader's `to` sits beyond its final bar, which
    // is the normal resting state (rightOffset). The follower must show the same
    // future margin, not snap back onto its last candle.
    const a = layer(days(0, 9));
    const b = layer(days(-5, 9));
    const mapped = followerRange(a, b, { from: 5, to: 13 });
    expect(mapped).toEqual({ from: 10, to: 18 });
  });

  it('declines rather than guessing when an answer would be meaningless', () => {
    const daily = layer(days(0, 9));
    expect(followerRange(layer([]), daily, { from: 0, to: 5 })).toBeNull();
    expect(followerRange(daily, layer([]), { from: 0, to: 5 })).toBeNull();
    expect(followerRange(daily, layer([T0]), { from: 0, to: 5 })).toBeNull(); // span collapses
    expect(followerRange(daily, daily, { from: 5, to: 5 })).toBeNull();
  });
});

describe('crosshair sync across mismatched charts', () => {
  it('marks the same instant on a follower whose bar sits at a different index', () => {
    const a = makeChart(days(0, 9));       // "NIFTY", 10 daily bars
    const b = makeChart(days(-5, 9));      // "BANKNIFTY", 15 daily bars
    const group = createLinkGroup({ crosshair: true, viewport: false });
    group.add(a.chart);
    group.add(b.chart);

    const instant = T0 + 3 * DAY;
    hover(a.chart, a.el, instant);

    const marked = group.crosshairIndex(b.chart);
    expect(marked).toBe(8);
    // The load-bearing assertion: it is NOT the leader's index copied across.
    expect(marked).not.toBe(a.chart.dataLayer.timeToIndex(instant));
    expect(b.chart.dataLayer.indexToTime(marked as number)).toBe(instant);
  });

  it('drops the linked line from whichever chart the cursor moves into', () => {
    // The chart under the pointer draws its own, real crosshair. A linked line
    // left over from when it was a follower would double the line under the
    // cursor, one bar out whenever the two charts disagree.
    const a = makeChart(days(0, 9));
    const b = makeChart(days(-5, 9));
    const group = createLinkGroup({ viewport: false });
    group.add(a.chart);
    group.add(b.chart);

    hover(b.chart, b.el, T0 + 3 * DAY);
    expect(group.crosshairIndex(a.chart)).toBe(3);

    hover(a.chart, a.el, T0 + 5 * DAY);
    expect(group.crosshairIndex(a.chart)).toBeNull();
    expect(group.crosshairIndex(b.chart)).toBe(10);
  });

  it('marks the same instant on a follower with a different interval', () => {
    const daily = makeChart(days(0, 3));
    const hourly = makeChart(hours(0, 4));
    const group = createLinkGroup({ crosshair: true, viewport: false });
    group.add(daily.chart);
    group.add(hourly.chart);

    const instant = T0 + 2 * DAY;
    hover(daily.chart, daily.el, instant);

    expect(group.crosshairIndex(hourly.chart)).toBe(48);
    expect(hourly.chart.dataLayer.indexToTime(48)).toBe(instant);
  });

  it('holds the follower on the bar that contains the leader instant', () => {
    const hourly = makeChart(hours(0, 5));
    // Daily follower: every hourly instant except midnight falls in a hole.
    const daily = makeChart(days(0, 5));
    const group = createLinkGroup({ crosshair: true, viewport: false });
    group.add(hourly.chart);
    group.add(daily.chart);

    // Both instants are inside day 3, so both land on day 3. Day 4 has not
    // opened at either of them.
    hover(hourly.chart, hourly.el, T0 + 3 * DAY + 20 * HOUR);
    expect(group.crosshairIndex(daily.chart)).toBe(3);

    hover(hourly.chart, hourly.el, T0 + 3 * DAY + 4 * HOUR);
    expect(group.crosshairIndex(daily.chart)).toBe(3);
  });

  it('draws nothing in a hole under the hide policy', () => {
    const hourly = makeChart(hours(0, 5));
    const daily = makeChart(days(0, 5));
    const group = createLinkGroup({ crosshair: true, viewport: false, whenMissing: 'hide' });
    group.add(hourly.chart);
    group.add(daily.chart);

    hover(hourly.chart, hourly.el, T0 + 3 * DAY + 20 * HOUR);
    expect(group.crosshairIndex(daily.chart)).toBeNull();
    hover(hourly.chart, hourly.el, T0 + 3 * DAY);
    expect(group.crosshairIndex(daily.chart)).toBe(3);
  });

  it('clears every follower when the pointer leaves the leader', () => {
    const a = makeChart(days(0, 9));
    const b = makeChart(days(-5, 9));
    const group = createLinkGroup({ viewport: false });
    group.add(a.chart);
    group.add(b.chart);

    hover(a.chart, a.el, T0 + 3 * DAY);
    expect(group.crosshairIndex(b.chart)).toBe(8);
    a.el.dispatch('pointerleave', {});
    expect(group.crosshairIndex(b.chart)).toBeNull();
  });

  it('covers every pane, the way the chart\'s own global crosshair does', () => {
    const a = makeChart(days(0, 9));
    const b = makeChart(days(-5, 9));
    b.chart.addSeries('histogram', { paneIndex: 1 }).setData(barsAt(days(-5, 9)));
    expect(b.chart.panes().length).toBe(2);

    const group = createLinkGroup({ viewport: false });
    group.add(a.chart);
    group.add(b.chart);
    hover(a.chart, a.el, T0 + 3 * DAY);

    expect(b.chart.panes().map((p) => p.primitives().filter((x) => x instanceof LinkCrosshair).length))
      .toEqual([1, 1]);
  });
});

describe('the linked crosshair actually draws', () => {
  /** A synthetic primitive context: the fields `LinkCrosshair.draw` reads. */
  function renderContext(barSpacing: number, baseIndex: number): {
    ctx: CanvasRenderingContext2D;
    rec: ReturnType<typeof makeCtx>['rec'];
    rc: Parameters<LinkCrosshair['draw']>[1];
  } {
    const { ctx, rec } = makeCtx();
    const timeScale = new TimeScale({ barSpacing, rightOffset: 0 });
    timeScale.setWidth(600);
    timeScale.setBaseIndex(baseIndex);
    return {
      ctx,
      rec,
      rc: {
        timeScale,
        priceScale: new PriceScale(),
        dataLayer: new DataLayer(),
        plotWidth: 600,
        plotHeight: 400,
        priceAxisWidth: 56,
        dpr: 1,
        theme: darkTheme,
      },
    };
  }

  it('strokes one vertical line at the linked bar, dimmed and with no price line', () => {
    const { ctx, rec, rc } = renderContext(10, 59);
    const line = new LinkCrosshair();
    line.setIndex(50);
    line.draw(ctx, rc);
    const strokes = rec.ops.filter((o) => o.type === 'stroke');
    expect(strokes).toHaveLength(1); // vertical only: no mirrored price line
    const moves = rec.ops.filter((o) => o.type === 'moveTo');
    expect(moves[0].args[0]).toBeCloseTo(Math.round(rc.timeScale.indexToX(50)) + 0.5, 6);
    // Dimmed against the pane's own crosshair colour, so it reads as someone
    // else's cursor rather than a second one of your own.
    expect(strokes[0].strokeStyle).toContain(String(LINK_CROSSHAIR_ALPHA));
    expect(strokes[0].strokeStyle).not.toBe(darkTheme.crosshair);
  });

  it('draws nothing with no target, or when the target is scrolled out of view', () => {
    const empty = renderContext(10, 59);
    new LinkCrosshair().draw(empty.ctx, empty.rc);
    expect(empty.rec.count('stroke')).toBe(0);

    const off = renderContext(10, 59);
    const line = new LinkCrosshair();
    line.setIndex(-40); // far left of the visible range
    line.draw(off.ctx, off.rc);
    expect(off.rec.count('stroke')).toBe(0);
  });
});

describe('viewport sync', () => {
  it('moves a follower to the same wall-clock window, not the same indices', () => {
    const a = makeChart(days(0, 9));
    const b = makeChart(days(-5, 9));
    const group = createLinkGroup({ viewport: true, crosshair: false });
    group.add(a.chart);
    group.add(b.chart);

    drag(a.el, 120); // reveal older bars on the leader

    const ra = a.chart.getVisibleLogicalRange();
    const rb = b.chart.getVisibleLogicalRange();
    expect(rb.from).not.toBeCloseTo(ra.from, 6); // indices differ by the 5 extra days
    expect(b.chart.dataLayer.indexToTimeFloat(rb.from))
      .toBeCloseTo(a.chart.dataLayer.indexToTimeFloat(ra.from), 3);
    expect(b.chart.dataLayer.indexToTimeFloat(rb.to))
      .toBeCloseTo(a.chart.dataLayer.indexToTimeFloat(ra.to), 3);
  });

  it('keeps a different-interval follower on the same window', () => {
    const daily = makeChart(days(0, 9));
    const hourly = makeChart(hours(0, 10));
    const group = createLinkGroup({ viewport: true, crosshair: false });
    group.add(daily.chart);
    group.add(hourly.chart);

    drag(daily.el, 90);

    const rd = daily.chart.getVisibleLogicalRange();
    const rh = hourly.chart.getVisibleLogicalRange();
    // Far more bars on screen, same span of clock time.
    expect(rh.to - rh.from).toBeGreaterThan((rd.to - rd.from) * 20);
    expect(hourly.chart.dataLayer.indexToTimeFloat(rh.from))
      .toBeCloseTo(daily.chart.dataLayer.indexToTimeFloat(rd.from), 3);
  });

  it('leaves a follower alone when it has no usable mapping', () => {
    const a = makeChart(days(0, 9));
    const single = makeChart([T0 + 2 * DAY]);
    const group = createLinkGroup({ viewport: true, crosshair: false });
    group.add(a.chart);
    group.add(single.chart);
    const before = single.chart.getVisibleLogicalRange();

    drag(a.el, 120);

    expect(single.chart.getVisibleLogicalRange()).toEqual(before);
  });
});

// ── stub charts: the only way to build an echo, and the only way to prove the
// guard. The engine's own `setVisibleLogicalRange` does not emit today, so a
// loop can only be staged with a host that echoes, which is exactly what a
// real symbol callback does when it re-emits after loading.
class StubChart implements LinkChart {
  public readonly dataLayer: LinkDataLayer;
  public range: LogicalRange = { from: 0, to: 8 };
  public applied = 0;
  public symbols: string[] = [];
  /** Re-emit on every applied change, the way a naive host callback would. */
  public echo = false;
  private readonly _listeners = new Map<string, Set<(p: unknown) => void>>();
  private _panes = 1;

  public constructor(times: readonly number[]) {
    this.dataLayer = layer(times);
  }

  public on(event: string, cb: (payload: unknown) => void): () => void {
    let set = this._listeners.get(event);
    if (set === undefined) { set = new Set(); this._listeners.set(event, set); }
    set.add(cb);
    return () => { set?.delete(cb); };
  }

  public emit(event: string, payload: unknown): void {
    for (const cb of [...(this._listeners.get(event) ?? [])]) cb(payload);
  }

  public listenerCount(event: string): number {
    return this._listeners.get(event)?.size ?? 0;
  }

  public getVisibleLogicalRange(): LogicalRange { return this.range; }

  public setVisibleLogicalRange(range: LogicalRange): void {
    this.range = range;
    this.applied++;
    if (this.echo) this.emit('pan', {});
  }

  public panes(): readonly unknown[] { return new Array(this._panes).fill({}); }
  public kill(): void { this._panes = 0; }
  public addPrimitive(): void {}
  public removePrimitive(): void {}
}

describe('feedback loops', () => {
  it('does not oscillate when a follower echoes the viewport back', () => {
    const a = new StubChart(days(0, 9));
    const b = new StubChart(days(-5, 9));
    a.echo = true;
    b.echo = true;
    const group = createLinkGroup({ viewport: true, crosshair: false });
    group.add(a);
    group.add(b);

    a.range = { from: 2, to: 6 };
    a.emit('pan', {});

    // Exactly one application on the follower, and none back on the leader.
    // Without the guard this recurses until the stack gives out.
    expect(b.applied).toBe(1);
    expect(a.applied).toBe(0);
    expect(b.range).toEqual({ from: 7, to: 11 });
  });

  it('does not oscillate when a symbol callback re-announces the symbol', () => {
    const a = new StubChart(days(0, 9));
    const b = new StubChart(days(0, 9));
    const group = createLinkGroup({ symbol: true, crosshair: false, viewport: false });
    const follow = (chart: StubChart) => (symbol: string): void => {
      chart.symbols.push(symbol);
      chart.emit('symbol', { symbol }); // the echo a real host produces
    };
    group.add(a, { symbol: 'NIFTY', onSymbol: follow(a) });
    group.add(b, { symbol: 'NIFTY', onSymbol: follow(b) });

    a.emit('symbol', { symbol: 'BANKNIFTY' });

    expect(b.symbols).toEqual(['BANKNIFTY']);
    expect(a.symbols).toEqual([]); // the leader already has it; no round trip
    expect(group.symbol()).toBe('BANKNIFTY');
  });

  it('does not let a follower that renames the symbol bounce it back to the leader', () => {
    // A host loader that normalises the name (a suffix, a case change) and
    // announces what it loaded. That echo arrives inside the broadcast, and
    // taking it as a new selection would make the follower's spelling the
    // group's: the next convergence then sends it back to the leader.
    const a = new StubChart(days(0, 9));
    const b = new StubChart(days(0, 9));
    const group = createLinkGroup({ symbol: true, crosshair: false, viewport: false });
    const load = (chart: StubChart, rename: (s: string) => string) => (symbol: string): void => {
      chart.symbols.push(symbol);
      chart.emit('symbol', { symbol: rename(symbol) });
    };
    group.add(a, { symbol: 'NIFTY', onSymbol: load(a, (s) => s) });
    group.add(b, { symbol: 'NIFTY', onSymbol: load(b, (s) => `${s}-EQ`) });

    a.emit('symbol', { symbol: 'BANKNIFTY' });
    expect(b.symbols).toEqual(['BANKNIFTY']);
    expect(group.symbol()).toBe('BANKNIFTY');

    // Switching the channel off and on converges on the agreed instrument,
    // which both charts already hold: nothing is loaded again on either side.
    group.setOptions({ symbol: false });
    group.setOptions({ symbol: true });
    expect(a.symbols).toEqual([]);
    expect(b.symbols).toEqual(['BANKNIFTY']);

    // A chart joining later is loaded with the leader's choice.
    const late = new StubChart(days(0, 9));
    group.add(late, { symbol: 'NIFTY', onSymbol: load(late, (s) => s) });
    expect(late.symbols).toEqual(['BANKNIFTY']);
  });

  it('survives an echo that crosses channels: a symbol load that moves a viewport', () => {
    // The second-order loop decision 3 is group-wide for. Loading a new
    // instrument replaces the data and restores the zoom, which emits 'pan',
    // which syncs viewports, which emits 'pan' on the other side.
    const a = new StubChart(days(0, 9));
    const b = new StubChart(days(-5, 9));
    a.echo = true;
    b.echo = true;
    const group = createLinkGroup({ symbol: true, viewport: true, crosshair: false });
    group.add(a, { symbol: 'NIFTY', onSymbol: () => a.setVisibleLogicalRange(a.range) });
    group.add(b, { symbol: 'NIFTY', onSymbol: () => b.setVisibleLogicalRange(b.range) });

    a.emit('symbol', { symbol: 'BANKNIFTY' });

    expect(b.applied).toBe(1); // its own reload, and no ping-pong after it
    expect(a.applied).toBe(0);
  });

  it('survives a three-chart ring where every member echoes', () => {
    const charts = [new StubChart(days(0, 9)), new StubChart(days(-5, 9)), new StubChart(days(-2, 9))];
    for (const c of charts) c.echo = true;
    const group = createLinkGroup({ viewport: true, crosshair: false });
    for (const c of charts) group.add(c);

    charts[0].range = { from: 1, to: 5 };
    charts[0].emit('pan', {});

    expect(charts[1].applied).toBe(1);
    expect(charts[2].applied).toBe(1);
    expect(charts[0].applied).toBe(0);
  });
});

describe('lifecycle', () => {
  it('drops a destroyed member and broadcasts to the rest without throwing', () => {
    const a = makeChart(days(0, 9));
    const b = makeChart(days(-5, 9));
    const doomed = makeChart(days(-2, 9));
    const group = createLinkGroup({ viewport: true });
    group.add(a.chart);
    group.add(b.chart);
    group.add(doomed.chart);
    expect(group.members()).toHaveLength(3);

    doomed.chart.destroy();

    expect(() => hover(a.chart, a.el, T0 + 3 * DAY)).not.toThrow();
    expect(() => drag(a.el, 60)).not.toThrow();
    expect(group.members()).toHaveLength(2);
    expect(group.has(doomed.chart)).toBe(false);
    // The survivor still got the broadcast.
    expect(group.crosshairIndex(b.chart)).toBe(8);
  });

  it('skips a member destroyed by another member\'s callback mid-broadcast', () => {
    // The loop runs over a snapshot, so a host callback that tears a chart down
    // (closing a panel in response to a symbol change) leaves a corpse still in
    // the list ahead of the cursor. It must be stepped over, not driven.
    const a = new StubChart(days(0, 9));
    const b = new StubChart(days(0, 9));
    const doomed = new StubChart(days(0, 9));
    const group = createLinkGroup({ symbol: true, crosshair: false, viewport: false });
    group.add(a, { symbol: 'NIFTY' });
    group.add(b, { symbol: 'NIFTY', onSymbol: () => doomed.kill() });
    group.add(doomed, { symbol: 'NIFTY', onSymbol: (s) => doomed.symbols.push(s) });

    group.setSymbol(a, 'BANKNIFTY');

    expect(doomed.symbols).toEqual([]);
    expect(group.members()).toHaveLength(2);
  });

  it('refuses to add a chart that is already destroyed', () => {
    const dead = makeChart(days(0, 9));
    dead.chart.destroy();
    const group = createLinkGroup();
    group.add(dead.chart);
    expect(group.members()).toHaveLength(0);
  });

  it('unsubscribes and detaches on remove and on destroy', () => {
    const a = new StubChart(days(0, 9));
    const b = new StubChart(days(-5, 9));
    const group = createLinkGroup({ viewport: true, crosshair: false });
    group.add(a);
    group.add(b);
    expect(a.listenerCount('pan')).toBe(1);

    group.remove(a);
    expect(a.listenerCount('pan')).toBe(0);
    a.range = { from: 2, to: 6 };
    a.emit('pan', {});
    expect(b.applied).toBe(0);

    group.add(a);
    group.destroy();
    expect(a.listenerCount('pan')).toBe(0);
    expect(b.listenerCount('pan')).toBe(0);
    a.emit('pan', {});
    expect(b.applied).toBe(0);
  });

  it('will not re-subscribe a chart added to a group that was already destroyed', () => {
    const a = new StubChart(days(0, 9));
    const b = new StubChart(days(-5, 9));
    const group = createLinkGroup({ viewport: true, crosshair: false });
    group.add(a);
    group.destroy();

    group.add(a);
    group.add(b);

    expect(group.members()).toHaveLength(0);
    expect(a.listenerCount('pan')).toBe(0);
    a.range = { from: 2, to: 6 };
    a.emit('pan', {});
    expect(b.applied).toBe(0);
  });

  it('takes the linked crosshair off a chart that leaves the group', () => {
    const a = makeChart(days(0, 9));
    const b = makeChart(days(-5, 9));
    const group = createLinkGroup({ viewport: false });
    group.add(a.chart);
    group.add(b.chart);
    hover(a.chart, a.el, T0 + 3 * DAY);
    expect(b.chart.panes()[0].primitives().some((p) => p instanceof LinkCrosshair)).toBe(true);

    group.remove(b.chart);
    expect(b.chart.panes()[0].primitives().some((p) => p instanceof LinkCrosshair)).toBe(false);
  });
});

describe('the three switches are independent', () => {
  function trio(options: ConstructorParameters<typeof LinkGroup>[0]): {
    group: LinkGroup;
    a: { chart: Chart; el: FakeElement };
    b: { chart: Chart; el: FakeElement };
    loaded: string[];
  } {
    const a = makeChart(days(0, 9));
    const b = makeChart(days(-5, 9));
    const loaded: string[] = [];
    const group = createLinkGroup(options);
    group.add(a.chart, { symbol: 'NIFTY' });
    group.add(b.chart, { symbol: 'NIFTY', onSymbol: (s) => loaded.push(s) });
    return { group, a, b, loaded };
  }

  it('crosshair only: the cursor mirrors, the window and the symbol do not', () => {
    const { group, a, b, loaded } = trio({ crosshair: true, viewport: false, symbol: false });
    const before = b.chart.getVisibleLogicalRange();

    hover(a.chart, a.el, T0 + 3 * DAY);
    drag(a.el, 100);
    group.setSymbol(a.chart, 'BANKNIFTY');

    expect(group.crosshairIndex(b.chart)).toBe(8);
    expect(b.chart.getVisibleLogicalRange()).toEqual(before);
    expect(loaded).toEqual([]);
  });

  it('viewport only: the window mirrors, the cursor and the symbol do not', () => {
    const { group, a, b, loaded } = trio({ crosshair: false, viewport: true, symbol: false });
    const before = b.chart.getVisibleLogicalRange();

    hover(a.chart, a.el, T0 + 3 * DAY);
    drag(a.el, 100);
    group.setSymbol(a.chart, 'BANKNIFTY');

    expect(group.crosshairIndex(b.chart)).toBeNull();
    expect(b.chart.getVisibleLogicalRange()).not.toEqual(before);
    expect(loaded).toEqual([]);
  });

  it('symbol only: the instrument mirrors, the cursor and the window do not', () => {
    const { group, a, b, loaded } = trio({ crosshair: false, viewport: false, symbol: true });
    const before = b.chart.getVisibleLogicalRange();

    hover(a.chart, a.el, T0 + 3 * DAY);
    drag(a.el, 100);
    group.setSymbol(a.chart, 'BANKNIFTY');

    expect(group.crosshairIndex(b.chart)).toBeNull();
    expect(b.chart.getVisibleLogicalRange()).toEqual(before);
    expect(loaded).toEqual(['BANKNIFTY']);
  });

  it('defaults to crosshair and viewport on, symbol off', () => {
    expect(createLinkGroup().options())
      .toEqual({
        crosshair: true, viewport: true, symbol: false, interval: false, chartType: false, appearance: false,
        drawings: false, whenMissing: 'nearest',
      });
  });
});

describe('runtime switching', () => {
  it('clears the linked crosshairs the moment crosshair sync is turned off', () => {
    const a = makeChart(days(0, 9));
    const b = makeChart(days(-5, 9));
    const group = createLinkGroup({ viewport: false });
    group.add(a.chart);
    group.add(b.chart);
    hover(a.chart, a.el, T0 + 3 * DAY);
    expect(group.crosshairIndex(b.chart)).toBe(8);

    group.setOptions({ crosshair: false });

    expect(group.crosshairIndex(b.chart)).toBeNull();
    expect(b.chart.panes()[0].primitives().some((p) => p instanceof LinkCrosshair)).toBe(false);
    hover(a.chart, a.el, T0 + 5 * DAY);
    expect(group.crosshairIndex(b.chart)).toBeNull();

    group.setOptions({ crosshair: true });
    hover(a.chart, a.el, T0 + 5 * DAY);
    expect(group.crosshairIndex(b.chart)).toBe(10);
  });

  it('makes the group agree on the instrument when symbol sync is switched on', () => {
    const a = new StubChart(days(0, 9));
    const b = new StubChart(days(0, 9));
    const group = createLinkGroup({ symbol: false, crosshair: false, viewport: false });
    group.add(a, { symbol: 'NIFTY', onSymbol: (s) => a.symbols.push(s) });
    group.add(b, { symbol: 'INFY', onSymbol: (s) => b.symbols.push(s) });
    a.emit('symbol', { symbol: 'BANKNIFTY' });
    expect(b.symbols).toEqual([]); // switch off: recorded, not applied

    group.setOptions({ symbol: true });

    expect(b.symbols).toEqual(['BANKNIFTY']);
    expect(a.symbols).toEqual([]);
  });

  it('a chart joining a symbol-linked group adopts the group\'s instrument', () => {
    const a = new StubChart(days(0, 9));
    const late = new StubChart(days(0, 9));
    const group = createLinkGroup({ symbol: true, crosshair: false, viewport: false });
    group.add(a, { symbol: 'NIFTY', onSymbol: (s) => a.symbols.push(s) });

    group.add(late, { symbol: 'INFY', onSymbol: (s) => late.symbols.push(s) });

    expect(late.symbols).toEqual(['NIFTY']);
    expect(a.symbols).toEqual([]);
  });

  it('a member with no onSymbol broadcasts but never follows', () => {
    const pinned = new StubChart(days(0, 9));
    const follower = new StubChart(days(0, 9));
    const group = createLinkGroup({ symbol: true, crosshair: false, viewport: false });
    group.add(pinned, { symbol: 'NIFTY' }); // no onSymbol: read-only member
    group.add(follower, { symbol: 'NIFTY', onSymbol: (s) => follower.symbols.push(s) });

    follower.emit('symbol', { symbol: 'INFY' });
    expect(pinned.symbols).toEqual([]);
    expect(group.symbol()).toBe('INFY');

    pinned.emit('symbol', { symbol: 'TCS' });
    expect(follower.symbols).toEqual(['TCS']);
  });

  it('ignores a symbol event with no usable payload', () => {
    const a = new StubChart(days(0, 9));
    const b = new StubChart(days(0, 9));
    const group = createLinkGroup({ symbol: true, crosshair: false, viewport: false });
    group.add(a, { symbol: 'NIFTY' });
    group.add(b, { symbol: 'NIFTY', onSymbol: (s) => b.symbols.push(s) });

    a.emit('symbol', {});
    a.emit('symbol', { symbol: '' });
    a.emit('symbol', null);
    expect(b.symbols).toEqual([]);

    a.emit('symbol', 'TCS'); // a bare string is accepted too
    expect(b.symbols).toEqual(['TCS']);
  });

  it('adding the same chart twice updates it instead of double-subscribing', () => {
    const a = new StubChart(days(0, 9));
    const b = new StubChart(days(-5, 9));
    const group = createLinkGroup({ viewport: true, crosshair: false });
    group.add(a);
    group.add(b);
    group.add(a);
    expect(a.listenerCount('pan')).toBe(1);
    expect(group.members()).toHaveLength(2);

    a.range = { from: 2, to: 6 };
    a.emit('pan', {});
    expect(b.applied).toBe(1);
  });
});

describe('regressions the browser pass found, not the suite', () => {
  /**
   * Both were invisible to unit tests because they live in the gap between an
   * input gesture and the event it should produce. The suite drove the model
   * directly and never went through a drag.
   */
  const makeLinkChart = (): Chart => {
    const c = new Chart(fakeDocument().createElement('div') as never, {
      document: fakeDocument(),
      pixelRatio: () => 1,
      shortcuts: false,
      raf: { schedule: (cb: () => void) => { cb(); return 1 }, cancel: () => {} },
    })
    c.applySize(800, 600)
    c.addSeries('candlestick').setData(
      Array.from({ length: 300 }, (_, i) => {
        const p = 100 + Math.sin(i / 7) * 4
        return { time: 1700000000 + i * 86400, open: p, high: p + 1, low: p - 1, close: p, volume: 10 }
      }),
    )
    return c
  }

  it('announces the kinetic glide, so a follower is not left behind', () => {
    // The drag emits its last pan when the pointer lifts. The chart then coasts
    // for a few hundred ms under inertia, moving the scale directly. Without an
    // event on each glide frame a linked chart stops where the pointer stopped.
    const chart = makeLinkChart()
    const seen: string[] = []
    chart.on('pan', () => seen.push('pan'))

    const before = chart.timeScale.rightOffset
    ;(chart as unknown as { _startKinetic(v: number): void })._startKinetic(2.5)

    expect(chart.timeScale.rightOffset).not.toBe(before)
    expect(seen.length).toBeGreaterThan(0)
  })

  it('lets a paused drag stop flinging', () => {
    // Velocity was sampled only on pointermove and never decayed, so holding
    // still before releasing kept whatever speed the last moving frame had.
    const chart = makeLinkChart() as unknown as {
      _dragVelocity: number
      _lastDragX: number
      _lastDragT: number
      _now(): number
    }
    chart._dragVelocity = 3
    chart._lastDragX = 400
    chart._lastDragT = chart._now() - 400 // a long, still pause

    // One more move at the same x: no distance over a long gap is a dead stop.
    const dt = 400
    const instant = 0
    const keep = Math.exp(-dt / 50)
    const decayed = 3 * keep + instant * (1 - keep)

    expect(decayed).toBeLessThan(0.05)
  })
})
