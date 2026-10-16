/**
 * Cheaper hit testing (`Pane.hitTestPrimitives`): a primitive that declares a
 * hit box (`IPrimitive.hitBounds`) is asked only where the pointer is inside
 * it, the boxes are kept while nothing they follow changes, and the walk stops
 * at an exact hit in the front band.
 *
 * The claim that matters is that none of this changes an answer. Every scene
 * here is hit-tested at a grid of points through the pane and through a
 * reference that asks every primitive and ranks them the way the pane always
 * has, and the two must agree at every point: drawings past the last candle,
 * pinned to the viewport, a text label, a selected drawing's handles, and
 * primitives in every band, the series band included.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Chart } from '../src/core/chart';
import type { Pane, PaneRenderContext } from '../src/core/pane';
import { DrawingController } from '../src/draw/index';
import type { IPrimitive, PrimitiveHit, PrimitiveHost, PrimitiveRenderContext, ZOrder } from '../src/primitives/primitive';
import type { Bar } from '../src/model/bar';
import type { SeriesApi } from '../src/model/series';
import { fakeDocument } from './helpers/fake-dom';

const T0 = 1_700_000_000;
const cleanups: (() => void)[] = [];
afterEach(() => { cleanups.splice(0).reverse().forEach((fn) => fn()); vi.unstubAllGlobals(); });

const data: Bar[] = Array.from({ length: 120 }, (_, i) => {
  const c = 100 + Math.sin(i / 6) * 4;
  return { time: T0 + i * 60, open: c - 0.5, high: c + 1, low: c - 1, close: c };
});

interface Internals {
  _panes: Pane[];
  _renderContext(index: number): PaneRenderContext;
}

/** The chart's first pane and the context the pointer path hit-tests it with. */
function paneOf(chart: Chart): { pane: Pane; ctx: () => PaneRenderContext } {
  const internals = chart as unknown as Internals;
  return { pane: internals._panes[0], ctx: () => internals._renderContext(0) };
}

/**
 * A host primitive standing for one annotation: a segment between two price
 * and time points, answering within `grab` px of it, with the box outside
 * which it cannot answer. Counts what it is asked.
 */
class Segment implements IPrimitive {
  public tests = 0;
  public bounds = 0;
  /** Times it was asked about a point outside its own box. */
  public outside = 0;
  public host: PrimitiveHost | null = null;
  public constructor(
    public readonly id: string,
    public t0: number, public p0: number, public t1: number, public p1: number,
    private readonly _z: ZOrder = 'top', private readonly _bounded = true, private readonly _grab = 5,
  ) {
    if (!_bounded) (this as { hitBounds?: unknown }).hitBounds = undefined;
  }
  public zOrder(): ZOrder { return this._z; }
  public draw(): void {}
  public attached(host: PrimitiveHost): void { this.host = host; }
  private _project(rc: PrimitiveRenderContext): [number, number, number, number] {
    return [
      rc.timeScale.indexToX(rc.dataLayer.timeToIndexFloat(this.t0)), rc.priceScale.priceToY(this.p0),
      rc.timeScale.indexToX(rc.dataLayer.timeToIndexFloat(this.t1)), rc.priceScale.priceToY(this.p1),
    ];
  }
  public hitBounds(rc: PrimitiveRenderContext): { left: number; top: number; right: number; bottom: number } | null {
    this.bounds++;
    return this._box(rc);
  }
  private _box(rc: PrimitiveRenderContext): { left: number; top: number; right: number; bottom: number } {
    const [x0, y0, x1, y1] = this._project(rc);
    // Half a pixel wider than the grab radius: `hitTest` rounds the distance,
    // so it answers out to grab + 0.5, and a box has to hold all of that.
    const g = this._grab + 0.5;
    return { left: Math.min(x0, x1) - g, top: Math.min(y0, y1) - g, right: Math.max(x0, x1) + g, bottom: Math.max(y0, y1) + g };
  }
  public hitTest(x: number, y: number, rc: PrimitiveRenderContext): PrimitiveHit | null {
    this.tests++;
    const box = this._box(rc);
    if (this._bounded && !(x >= box.left && x <= box.right && y >= box.top && y <= box.bottom)) this.outside++;
    const [x0, y0, x1, y1] = this._project(rc);
    const dx = x1 - x0, dy = y1 - y0, len = dx * dx + dy * dy;
    const t = len === 0 ? 0 : Math.max(0, Math.min(1, ((x - x0) * dx + (y - y0) * dy) / len));
    // Whole pixels, so neighbouring segments tie often and the tie rules are exercised.
    const d = Math.round(Math.hypot(x - (x0 + t * dx), y - (y0 + t * dy)));
    return d <= this._grab ? { externalId: this.id, zOrder: this._z, distance: d } : null;
  }
}

/** A filled box that answers with distance zero anywhere inside it. */
class Box implements IPrimitive {
  public tests = 0;
  public constructor(public readonly id: string, private readonly _r: [number, number, number, number], private readonly _z: ZOrder) {}
  public zOrder(): ZOrder { return this._z; }
  public draw(): void {}
  public hitBounds(): { left: number; top: number; right: number; bottom: number } {
    const [l, t, r, b] = this._r;
    return { left: l, top: t, right: r, bottom: b };
  }
  public hitTest(x: number, y: number): PrimitiveHit | null {
    this.tests++;
    const [l, t, r, b] = this._r;
    return x >= l && x <= r && y >= t && y <= b ? { externalId: this.id, zOrder: this._z, distance: 0 } : null;
  }
}

/** Records the context a primitive with no binding is asked with, which every unbound one shares. */
class Probe implements IPrimitive {
  public rc: PrimitiveRenderContext | null = null;
  public zOrder(): ZOrder { return 'top'; }
  public draw(): void {}
  public hitTest(_x: number, _y: number, rc: PrimitiveRenderContext): null { this.rc = rc; return null; }
}

const RANK: Record<ZOrder, number> = { bottom: 0, normal: 2, top: 3 };

/**
 * The ranking `hitTestPrimitives` has always applied, with every primitive
 * asked and no early stop: over the series first, then the nearest, then the
 * higher band, the first of exact ties winning. The scenes bind no primitive
 * to a scale, so every one is asked with the probe's context.
 */
function reference(pane: Pane, ctx: PaneRenderContext, rc: PrimitiveRenderContext, x: number, y: number): PrimitiveHit | null {
  let best: PrimitiveHit | null = null, bestRank = 0;
  const series = pane.series();
  for (const p of pane.primitives()) {
    if (!p.hitTest) continue;
    let hit = p.hitTest(x, y, rc);
    if (hit === null) continue;
    const painter = hit.paintedBy ?? p;
    const entry = pane.primitiveStackAbove(painter);
    const after = entry === null ? undefined : ctx.stackSlot?.(entry);
    const at = after === undefined ? -1 : series.indexOf(after);
    if (at >= 0) hit = { ...hit, paintedBy: painter };
    const rank = at >= 0 ? 1 + (at + 1) / (series.length + 1) : RANK[painter === p ? hit.zOrder : painter.zOrder()];
    const side = +(rank >= 2) - +(bestRank >= 2);
    if (best === null || side > 0 || side === 0 && (hit.distance < best.distance || hit.distance === best.distance && rank > bestRank)) {
      best = hit; bestRank = rank;
    }
  }
  return best;
}

const summary = (hit: PrimitiveHit | null): unknown =>
  hit === null ? null : { id: hit.externalId, key: hit.hoverKey, d: hit.distance, z: hit.zOrder, cursor: hit.cursor, painter: hit.paintedBy ?? null };

function mount(ratio: () => number = () => 1): { chart: Chart; draw: DrawingController; series: SeriesApi; flush: () => void } {
  vi.stubGlobal('window', {});
  const doc = fakeDocument();
  // Frames run only when a test flushes them: the chart is measured once, and
  // after that hit testing has to be right from the state alone, whatever was
  // or was not painted since it changed.
  const pending: (() => void)[] = [];
  const flush = (): void => { for (let guard = 0; guard < 8 && pending.length > 0; guard++) pending.splice(0).forEach((cb) => cb()); };
  const chart = new Chart(doc.createElement('div'), {
    document: doc, shortcuts: false, timeNavigator: false, pixelRatio: ratio,
    raf: { schedule: (cb: () => void) => { pending.push(cb); return pending.length; }, cancel: () => {} },
  });
  chart.applySize(800, 500);
  const series = chart.addSeries('candlestick');
  series.setData(data);
  chart.setVisibleLogicalRange({ from: 10, to: 125 });
  const draw = new DrawingController(chart);
  flush();
  // Measured: a scale still on its 0..1 placeholder would put every price off the plot.
  expect(chart.panes()[0].priceScale.priceRange().max).toBeGreaterThan(100);
  cleanups.push(() => draw.destroy(), () => chart.destroy());
  return { chart, draw, series, flush };
}

/** Every point of a grid over the plot, pane against reference; the ids answered. */
function expectSameAnswers(chart: Chart, label: string, step = 5): Set<string> {
  const { pane, ctx } = paneOf(chart);
  const context = ctx();
  const probe = pane.primitives().find((p) => p instanceof Probe) as Probe;
  pane.hitTestPrimitives(-1000, -1000, context);
  const rc = probe.rc as PrimitiveRenderContext;
  const ids = new Set<string>();
  for (let x = 0; x <= chart.timeScale.width; x += step) {
    for (let y = 0; y <= pane.priceScale.height; y += step) {
      const hit = pane.hitTestPrimitives(x, y, context);
      if (hit !== null) ids.add(hit.externalId);
      expect(summary(hit), `${label} at ${x},${y}`).toEqual(summary(reference(pane, context, rc, x, y)));
    }
  }
  return ids;
}

describe('the hit-test prefilter', () => {
  it('answers exactly as asking every primitive does, drawings and every band included', () => {
    const { chart, draw } = mount();
    chart.addPrimitive(new Probe(), 0);
    const last = data[data.length - 1].time;
    // Drawings: inside the data, past the last candle, pinned to the viewport,
    // a text label, one behind the series and one in the series band.
    const trend = draw.add({ tool: 'trend-line', paneIndex: 0, style: {}, points: [{ time: T0 + 20 * 60, price: 98 }, { time: T0 + 60 * 60, price: 103 }] });
    const future = draw.add({ tool: 'trend-line', paneIndex: 0, style: {}, points: [{ time: last + 60, price: 101 }, { time: last + 5 * 60, price: 104 }] });
    const pinned = draw.add({ tool: 'rectangle', paneIndex: 0, style: {}, points: [], space: 'viewport', viewportPoints: [{ x: 0.1, y: 0.1 }, { x: 0.3, y: 0.25 }] });
    const label = draw.add({ tool: 'text', paneIndex: 0, style: {}, points: [{ time: T0 + 40 * 60, price: 99 }], text: { value: 'Label here' } });
    const behind = draw.add({ tool: 'rectangle', paneIndex: 0, style: {}, zIndex: -1, points: [{ time: T0 + 70 * 60, price: 97 }, { time: T0 + 90 * 60, price: 102 }] });
    // Up where nothing in front of the series reaches, so it answers somewhere.
    const banded = draw.add({ tool: 'trend-line', paneIndex: 0, style: {}, points: [{ time: T0 + 12 * 60, price: 104.5 }, { time: T0 + 25 * 60, price: 104.5 }] });
    expect(draw.placeInStack(banded.id, { entry: chart.seriesStack(0)[0] }, 'above')).toBe(true);
    // Host primitives in every band, bounded and not, overlapping one another.
    const w = chart.timeScale.width;
    for (let i = 0; i < 30; i++) {
      const a = data[15 + ((i * 7) % 90)], b = data[18 + ((i * 11) % 90)];
      const z: ZOrder = i % 3 === 0 ? 'top' : i % 3 === 1 ? 'normal' : 'bottom';
      chart.addPrimitive(new Segment(`seg${i}`, a.time, a.low, b.time, b.high, z, i % 4 !== 0), 0);
    }
    chart.addPrimitive(new Box('box-top', [w * 0.4, 100, w * 0.5, 180], 'top'), 0);
    chart.addPrimitive(new Box('box-top-again', [w * 0.45, 150, w * 0.55, 220], 'top'), 0);
    chart.addPrimitive(new Box('box-normal', [w * 0.2, 200, w * 0.6, 260], 'normal'), 0);
    // Behind the series, over the lower right: an exact hit there loses to
    // anything in front and ties are broken by distance behind.
    chart.addPrimitive(new Box('box-bottom', [w * 0.5, 150, w, 500], 'bottom'), 0);
    const slotted = new Box('box-slotted', [w * 0.1, 250, w * 0.3, 400], 'bottom');
    chart.addPrimitive(slotted, 0);
    expect(chart.setPrimitiveStackAbove(slotted, chart.seriesStack(0)[0])).toBe(true);
    // A price line: a built-in primitive with no box, asked on every move.
    chart.addPriceLine({ id: 'level', price: 100, color: '#2962ff', cursor: 'ns-resize' }, 0);

    const initial = expectSameAnswers(chart, 'initial');
    // The grid reached every kind of drawing and every band of primitive.
    for (const d of [trend, future, pinned, label, behind, banded]) expect(initial, d.id).toContain(`draw:${d.id}`);
    for (const id of ['box-top', 'box-top-again', 'box-normal', 'box-bottom', 'box-slotted', 'level']) expect(initial, id).toContain(id);
    expect([...initial].filter((id) => id.startsWith('seg')).length).toBeGreaterThan(5);
    // A selected drawing shows grab handles, which outrank its body.
    draw.select(trend.id);
    expect(expectSameAnswers(chart, 'selected')).toContain(`draw:${trend.id}#0`);
    // Moved without a frame in between: scrolled, zoomed, rescaled, resized.
    chart.timeScale.setRightOffset(chart.timeScale.rightOffset - 7);
    expectSameAnswers(chart, 'scrolled');
    chart.timeScale.setBarSpacing(chart.timeScale.barSpacing * 1.3);
    expectSameAnswers(chart, 'zoomed');
    const scale = chart.panes()[0].priceScale;
    scale.setPriceRange({ min: 95, max: 108 });
    scale.setAutoScale(false);
    expectSameAnswers(chart, 'rescaled');
    chart.applySize(640, 420);
    expectSameAnswers(chart, 'resized');
    // Six sweeps of a few thousand points each, pane and reference both.
  }, 60_000);

  it('asks only the primitives whose box holds the point, and measures the boxes once', () => {
    const { chart } = mount();
    // Five hundred short annotations across the bars in view, two bars long
    // and a little off the price, the way a busy chart carries them.
    const segments: Segment[] = [];
    for (let i = 0; i < 500; i++) {
      const at = 10 + ((i * 37) % 108);
      const a = data[at], b = data[at + 2];
      const s = new Segment(`s${i}`, a.time, a.low + (i % 5) * 0.4, b.time, b.high - (i % 3) * 0.4);
      segments.push(s);
      chart.addPrimitive(s, 0);
    }
    const { pane, ctx } = paneOf(chart);
    const context = ctx();
    const probe = new Probe();
    chart.addPrimitive(probe, 0);
    pane.hitTestPrimitives(-1000, -1000, ctx());
    const rc = probe.rc as PrimitiveRenderContext;
    const points: [number, number][] = [];
    for (let i = 0; i < 200; i++) points.push([(i * 97) % chart.timeScale.width, (i * 61) % pane.priceScale.height]);
    let inside = 0;
    for (const [x, y] of points) {
      for (const s of segments) {
        const box = s.hitBounds(rc);
        s.bounds--;
        if (box !== null && x >= box.left && x <= box.right && y >= box.top && y <= box.bottom) inside++;
      }
    }
    for (const s of segments) { s.tests = 0; s.bounds = 0; }
    for (const [x, y] of points) pane.hitTestPrimitives(x, y, context);
    const asked = segments.reduce((n, s) => n + s.tests, 0);
    const measured = segments.reduce((n, s) => n + s.bounds, 0);
    // A point asks only segments whose box holds it (fewer when an exact hit
    // ends the walk), a handful on average, and never all five hundred.
    expect(segments.reduce((n, s) => n + s.outside, 0)).toBe(0);
    expect(asked).toBeLessThanOrEqual(inside);
    expect(asked).toBeGreaterThan(inside / 2);
    expect(asked / points.length).toBeLessThan(25);
    expect(measured).toBe(0);
    // Nothing moved: another sweep measures nothing either.
    for (const [x, y] of points) pane.hitTestPrimitives(x, y, context);
    expect(segments.reduce((n, s) => n + s.bounds, 0)).toBe(0);
    // A scroll lets them all go, and the next move measures each once.
    chart.timeScale.setRightOffset(chart.timeScale.rightOffset - 1);
    for (const [x, y] of points) pane.hitTestPrimitives(x, y, ctx());
    expect(segments.reduce((n, s) => n + s.bounds, 0)).toBe(500);
    chart.destroy();
  });

  it('measures again after anything a box follows changes, frame or no frame', () => {
    let ratio = 1;
    const { chart, series } = mount(() => ratio);
    const seg = new Segment('one', data[40].time, 100, data[50].time, 101);
    chart.addPrimitive(seg, 0);
    const { pane, ctx } = paneOf(chart);
    const at = (): number => { pane.hitTestPrimitives(10, 10, ctx()); return seg.bounds; };
    let n = at();
    const changed = (label: string, change: () => void): void => {
      change();
      const next = at();
      expect(next, label).toBe(n + 1);
      n = next;
      // And only once for it.
      expect(at(), `${label}, twice`).toBe(n);
    };
    changed('scroll', () => chart.timeScale.setRightOffset(chart.timeScale.rightOffset - 3));
    changed('zoom', () => chart.timeScale.setBarSpacing(chart.timeScale.barSpacing * 1.5));
    changed('price range', () => { const s = chart.panes()[0].priceScale; s.setAutoScale(false); s.setPriceRange({ min: 90, max: 110 }); });
    changed('size', () => chart.applySize(700, 450));
    changed('new bar', () => series.update({ ...data[data.length - 1], time: data[data.length - 1].time + 60 }));
    changed('its own update', () => { seg.p1 = 104; seg.host?.requestUpdate(); });
    changed('another primitive', () => chart.addPrimitive(new Segment('two', data[5].time, 1, data[6].time, 2), 0));
    // What the render context carries besides the scales: a box may grow its
    // handles under the pointer, snap to device pixels, or leave room for the
    // axis tag on whichever side the axis sits.
    const input = (chart as unknown as { _input: { _hoverId: string | null } })._input;
    changed('hover', () => { input._hoverId = 'one'; });
    changed('hover gone', () => { input._hoverId = null; });
    changed('pixel ratio', () => { ratio = 2; });
    changed('axis side', () => { expect(chart.setPriceAxisPlacement(0, 'right', 'left')).toBe(true); });
    chart.destroy();
  });

  it('finds a primitive where it moved to, before any frame paints it there', () => {
    const { chart } = mount();
    const seg = new Segment('mover', data[30].time, 99, data[35].time, 99);
    chart.addPrimitive(seg, 0);
    const { pane, ctx } = paneOf(chart);
    const y = (p: number): number => pane.priceScale.priceToY(p);
    const x = chart.timeScale.indexToX(32);
    expect(pane.hitTestPrimitives(x, y(99), ctx())?.externalId).toBe('mover');
    seg.p0 = 103; seg.p1 = 103;
    seg.host?.requestUpdate();
    expect(pane.hitTestPrimitives(x, y(99), ctx())).toBeNull();
    expect(pane.hitTestPrimitives(x, y(103), ctx())?.externalId).toBe('mover');
    chart.destroy();
  });

  it('finds a primitive that answers from its last frame where the next frame puts it', () => {
    const { chart, flush } = mount();
    // Records where it drew and answers from that, the way the price line and
    // the legend do, box included.
    let drawn: [number, number] | null = null;
    const recorded: IPrimitive = {
      zOrder: () => 'top',
      draw: (_ctx, rc) => { drawn = [rc.timeScale.indexToX(60), rc.priceScale.priceToY(100)]; },
      hitBounds: () => (drawn === null ? null : { left: drawn[0] - 4, top: drawn[1] - 4, right: drawn[0] + 4, bottom: drawn[1] + 4 }),
      hitTest: (x, y) => (drawn !== null && Math.abs(x - drawn[0]) <= 4 && Math.abs(y - drawn[1]) <= 4
        ? { externalId: 'recorded', zOrder: 'top', distance: 0 } : null),
    };
    chart.addPrimitive(recorded, 0);
    flush();
    const { pane, ctx } = paneOf(chart);
    const [x0, y0] = drawn as unknown as [number, number];
    expect(pane.hitTestPrimitives(x0, y0, ctx())?.externalId).toBe('recorded');
    // Scrolled, not yet painted: it still answers where it was drawn, box and all.
    chart.timeScale.setRightOffset(chart.timeScale.rightOffset - 10);
    expect(pane.hitTestPrimitives(x0, y0, ctx())?.externalId).toBe('recorded');
    // The frame moves it, and the box measured before that frame goes with it.
    flush();
    const [x1, y1] = drawn as unknown as [number, number];
    expect(x1).not.toBe(x0);
    expect(pane.hitTestPrimitives(x1, y1, ctx())?.externalId).toBe('recorded');
    expect(pane.hitTestPrimitives(x0, y0, ctx())).toBeNull();
  });

  it('never asks a primitive whose box says nothing of it can be hit', () => {
    const { chart } = mount();
    const hidden = new Box('hidden', [0, 0, 800, 500], 'top');
    (hidden as unknown as { hitBounds: () => null }).hitBounds = () => null;
    chart.addPrimitive(hidden, 0);
    const { pane, ctx } = paneOf(chart);
    expect(pane.hitTestPrimitives(100, 100, ctx())).toBeNull();
    expect(hidden.tests).toBe(0);
    chart.destroy();
  });

  it('stops at an exact hit in the front band, and keeps the first of two', () => {
    const { chart } = mount();
    const first = new Box('first', [100, 100, 200, 200], 'top');
    const second = new Box('second', [150, 150, 250, 250], 'top');
    chart.addPrimitive(first, 0);
    chart.addPrimitive(second, 0);
    const { pane, ctx } = paneOf(chart);
    expect(pane.hitTestPrimitives(175, 175, ctx())?.externalId).toBe('first');
    expect(second.tests).toBe(0);
    // Only the second holds this point, so it is asked and answers.
    expect(pane.hitTestPrimitives(225, 225, ctx())?.externalId).toBe('second');
    expect(second.tests).toBe(1);
  });

  it('keeps walking past a near miss or an exact hit behind the front band', () => {
    const { chart } = mount();
    const { pane, ctx } = paneOf(chart);
    const x = chart.timeScale.indexToX(45);
    const y = pane.priceScale.priceToY(100);
    // In front, three pixels off: the walk goes on past it.
    const near = new Segment('near', data[40].time, 100, data[50].time, 100, 'top', true, 5);
    const exactBottom = new Box('exact-bottom', [0, 0, 800, 500], 'bottom');
    const exactTop = new Box('exact-top', [x - 1, y + 2, x + 1, y + 4], 'top');
    chart.addPrimitive(near, 0);
    chart.addPrimitive(exactBottom, 0);
    chart.addPrimitive(exactTop, 0);
    // An exact hit in the front band after both wins, and the walk reached it.
    expect(pane.hitTestPrimitives(x, y + 3, ctx())?.externalId).toBe('exact-top');
    expect(exactBottom.tests).toBe(1);
    // An exact hit behind the series still loses to the near miss in front.
    expect(pane.hitTestPrimitives(x + 20, y + 3, ctx())?.externalId).toBe('near');
    expect(exactBottom.tests).toBe(2);
    // And an exact hit over the series in the normal band beats it on distance.
    const exactNormal = new Box('exact-normal', [x + 15, y, x + 25, y + 6], 'normal');
    chart.addPrimitive(exactNormal, 0);
    expect(pane.hitTestPrimitives(x + 20, y + 3, ctx())?.externalId).toBe('exact-normal');
  });
});
