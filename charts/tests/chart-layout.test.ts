/**
 * Chart layout and the things a host hangs off one axis: the post-construction
 * re-measure, the context menu's axis targets, and the per-axis calls a
 * price-axis menu acts through.
 */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { Chart, PRICE_SCALE_MODES } from '../src/core/chart';
import type { ContextMenuEvent } from '../src/core/chart';
import { fakeDocument, pointer, type FakeElement } from './helpers/fake-dom';
import type { RecordingContext } from './helpers/fake-ctx';
import type { Bar } from '../src/model/bar';
import type { SeriesApi } from '../src/model/series';

const BARS: Bar[] = Array.from({ length: 40 }, (_, i) => {
  const c = 100 + Math.sin(i / 4) * 5;
  return { time: 1700000000 + i * 60, open: c - 0.5, high: c + 1, low: c - 1, close: c, volume: 100 + i };
});

interface Harness {
  chart: Chart;
  el: FakeElement;
  /** Resize the container the way the browser would, without telling the chart. */
  size(width: number, height: number): void;
  /** Run every frame the chart has asked for, including ones those frames ask for. */
  flush(): void;
}

/**
 * A chart on a container whose measurements the test controls, and whose frames
 * it runs by hand: the re-measure this file is about happens on a frame, so a
 * synchronous scheduler would run it before the container has "settled".
 */
function deferred(width: number, height: number): Harness {
  const doc = fakeDocument();
  const el = doc.createElement('div') as unknown as FakeElement;
  const frames: (() => void)[] = [];
  const size = (w: number, h: number): void => { Object.assign(el, { clientWidth: w, clientHeight: h }); };
  size(width, height);
  const chart = new Chart(el, {
    document: doc,
    pixelRatio: () => 1,
    shortcuts: false,
    timeNavigator: false,
    raf: { schedule: (cb) => frames.push(cb), cancel: () => {} },
  });
  return {
    chart,
    el,
    size,
    flush: (): void => {
      for (let guard = 0; frames.length > 0 && guard < 20; guard++) (frames.shift() as () => void)();
    },
  };
}

interface Mounted {
  chart: Chart;
  el: FakeElement;
  series: SeriesApi;
}

/** The usual mount: measured container, synchronous frames (see tests/compare.test.ts). */
function mount(): Mounted {
  const doc = fakeDocument();
  const el = doc.createElement('div') as unknown as FakeElement;
  Object.assign(el, { clientWidth: 800, clientHeight: 600 });
  const chart = new Chart(el, {
    document: doc,
    pixelRatio: () => 1,
    shortcuts: false,
    timeNavigator: false,
    raf: { schedule: (cb) => { cb(); return 1; }, cancel: () => {} },
  });
  chart.applySize(800, 600);
  const series = chart.addSeries('candlestick');
  series.setData(BARS);
  return { chart, el, series };
}

const span = (r: { min: number; max: number }): number => r.max - r.min;
const mid = (r: { min: number; max: number }): number => (r.min + r.max) / 2;

describe('time-axis drag direction', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('expands spacing to the left and compresses to the right without panning', () => {
    vi.stubGlobal('window', {});
    const { chart, el } = mount();
    const spacing = chart.timeScale.barSpacing;
    const zoom = vi.fn();
    chart.on('zoom', zoom);
    const offset = chart.timeScale.rightOffset;
    el.dispatch('pointerdown', pointer('down', 400, 590));
    el.dispatch('pointermove', pointer('move', 300, 590));
    expect(chart.timeScale.barSpacing).toBeGreaterThan(spacing);
    expect(chart.timeScale.rightOffset).toBe(offset);
    expect(zoom).toHaveBeenCalled();
    el.dispatch('pointermove', pointer('move', 400, 590));
    expect(chart.timeScale.barSpacing).toBeCloseTo(spacing);
    el.dispatch('pointermove', pointer('move', 500, 590));
    expect(chart.timeScale.barSpacing).toBeLessThan(spacing);
    expect(chart.timeScale.rightOffset).toBe(offset);
    el.dispatch('pointerup', pointer('up', 500, 590));
    const released = chart.timeScale.barSpacing;
    el.dispatch('pointermove', pointer('move', 600, 590, { buttons: 0 }));
    expect(chart.timeScale.barSpacing).toBe(released);
    chart.destroy();
  });
});

describe('measuring the container', () => {
  it('lays the panes into the size the container settles at, not the one it first reported', () => {
    // A flex/grid container whose height the browser has not resolved yet when
    // the chart is constructed: the reported symptom is an empty band under the
    // chart that a refresh makes go away.
    const h = deferred(800, 120);
    expect(h.chart.panes()[0].priceScale.height).toBe(120 - 22); // pre-layout box

    h.size(800, 600); // layout settles before the next frame runs
    h.flush();

    expect(h.chart.panes()[0].priceScale.height).toBe(600 - 22);
    expect(h.chart.panes()[0].element.style.flex).toBe('0 0 600px');
  });

  it('re-measures once, not on every later frame', () => {
    const h = deferred(800, 600);
    h.flush();
    h.chart.applySize(800, 400); // a host sizing the chart itself
    h.size(800, 600); // the container is still its old self
    h.flush();
    expect(h.chart.panes()[0].priceScale.height).toBe(400 - 22);
  });

  it('leaves a host-applied size alone when the container measures nothing', () => {
    // Hidden, or not in the document yet: 0 is not a measurement to lay out to,
    // and the ResizeObserver picks the container up when it appears.
    const h = deferred(0, 0);
    h.chart.applySize(800, 600);
    h.flush();
    expect(h.chart.panes()[0].priceScale.height).toBe(600 - 22);
  });

  it('does not measure a chart that was destroyed before the frame ran', () => {
    const h = deferred(800, 120);
    h.chart.destroy();
    h.size(800, 600);
    expect(() => h.flush()).not.toThrow();
  });
});

describe('contextmenu axis targets', () => {
  afterEach(() => vi.unstubAllGlobals());

  function menuAt(m: Mounted, x: number, y: number): ContextMenuEvent {
    const seen: ContextMenuEvent[] = [];
    const off = m.chart.on('contextmenu', (p) => seen.push(p as ContextMenuEvent));
    m.el.dispatch('contextmenu', {
      clientX: x, clientY: y, defaultPrevented: false, preventDefault(): void {},
    });
    off();
    return seen[0];
  }

  it('names the side and the scale a price-axis click lands on', () => {
    vi.stubGlobal('window', {}); // _attachInput bails when window is undefined
    const m = mount();
    expect(menuAt(m, 780, 300).target).toEqual({
      kind: 'price-scale', id: null, side: 'right', scaleId: 'right',
    });

    const left = m.chart.addSeries('line', { priceScaleId: 'left' });
    left.setData(BARS.map((b) => ({ time: b.time, value: b.close * 10 })));
    expect(menuAt(m, 20, 300).target).toEqual({
      kind: 'price-scale', id: null, side: 'left', scaleId: 'left',
    });
    expect(menuAt(m, 780, 300).target.side).toBe('right');
  });

  it('targets an overlay scale only after the host exposes its column', () => {
    vi.stubGlobal('window', {});
    const m = mount();
    const vol = m.chart.addSeries('histogram', { paneIndex: 1, priceScaleId: '' });
    vol.setData(BARS.map((b) => ({ time: b.time, value: b.volume ?? 0 })));
    expect(menuAt(m, 780, 500).target).toEqual({ kind: 'empty', id: null });
    m.chart.setPriceAxisPlacement(1, '', 'right');
    const target = menuAt(m, 780, 500).target;
    expect(target.kind).toBe('price-scale');
    expect(target.side).toBe('right');
    expect(target.scaleId).toBe('');
  });

  it('reads the bottom-left corner as the time axis, which runs the full width', () => {
    vi.stubGlobal('window', {});
    const m = mount();
    const left = m.chart.addSeries('line', { priceScaleId: 'left' });
    left.setData(BARS.map((b) => ({ time: b.time, value: b.close })));
    expect(menuAt(m, 20, 595).target).toEqual({ kind: 'time-scale', id: null });
    expect(menuAt(m, 400, 595).target).toEqual({ kind: 'time-scale', id: null });
  });

  it('leaves a hit on the plot exactly as it was', () => {
    vi.stubGlobal('window', {});
    const m = mount();
    const bar = BARS[20];
    const x = m.chart.timeToCoordinate(bar.time);
    const y = m.chart.priceToCoordinate(bar.close, 0) ?? 0;
    const target = menuAt(m, x, y).target;
    expect(target).toEqual({ kind: 'series', id: null, seriesType: 'candlestick' });
  });
});

describe('acting on one price axis', () => {
  it('reports what a menu has to tick, and what it has to grey out', () => {
    const { chart } = mount();
    expect(chart.priceAxisState(0, 'right')).toEqual({
      paneIndex: 0, scaleId: 'right', side: 'right', active: true, autoFit: true,
      inverted: false, mode: 'linear', scaled: true, lockRatio: false, movable: true,
    });
    // A side with nothing on it still answers: the row is drawn disabled.
    expect(chart.priceAxisState(0, 'left')?.active).toBe(false);
    expect(chart.priceAxisState(0, 'left')?.movable).toBe(false);
    expect(chart.priceAxisState(3, 'right')).toBeNull();
  });

  it('auto-fit, invert and the four modes act on the named axis only', () => {
    const { chart } = mount();
    const left = chart.addSeries('line', { priceScaleId: 'left' });
    left.setData(BARS.map((b) => ({ time: b.time, value: b.close * 10 })));

    chart.setPriceAxisAutoFit(0, 'left', false);
    expect(chart.priceAxisState(0, 'left')?.autoFit).toBe(false);
    expect(chart.priceAxisState(0, 'right')?.autoFit).toBe(true);

    chart.setPriceAxisOptions(0, 'left', { inverted: true });
    expect(chart.priceAxisState(0, 'left')?.inverted).toBe(true);
    expect(chart.priceAxisState(0, 'right')?.inverted).toBe(false);
    // Inverting is not a label change: higher prices now draw further down.
    const scale = chart.panes()[0].scaleFor('left');
    expect(scale.priceToY(scale.priceRange().max)).toBeGreaterThan(scale.priceToY(scale.priceRange().min));

    for (const mode of PRICE_SCALE_MODES) {
      chart.setPriceAxisOptions(0, 'left', { mode });
      expect(chart.priceAxisState(0, 'left')?.mode).toBe(mode); // one field: mutually exclusive
      expect(chart.priceAxisState(0, 'right')?.mode).toBe('linear');
    }
  });

  it('moves an axis to the other strip with its series, its range and its columns', () => {
    const { chart, series } = mount();
    const pane = chart.panes()[0];
    const moved = pane.priceScale;
    const range = moved.priceRange();
    const plotWidth = chart.timeScale.width;

    expect(chart.movePriceAxis(0, 'right', 'left')).toBe(true);

    expect(pane.usesScale('left')).toBe(true);
    expect(pane.scaleFor('left')).toBe(moved); // the axis itself moved, state and all
    expect(pane.scaleFor('left').priceRange()).toEqual(range);
    expect(series.priceScale()).toBe(moved);
    // The strip it left labels nothing, and the reserved column follows the
    // axis across rather than being taken twice.
    expect(pane.priceScale.scaled).toBe(false);
    expect(chart.timeScale.width).toBe(plotWidth);
    expect(chart.priceAxisState(0, 'right')?.active).toBe(false);

    expect(chart.movePriceAxis(0, 'left', 'right')).toBe(true);
    expect(pane.priceScale).toBe(moved);
    expect(chart.timeScale.width).toBe(plotWidth);
  });

  it('refuses a move onto an occupied side, and says so before it is asked', () => {
    const { chart } = mount();
    const left = chart.addSeries('line', { priceScaleId: 'left' });
    left.setData(BARS.map((b) => ({ time: b.time, value: b.close })));
    expect(chart.priceAxisState(0, 'right')?.movable).toBe(false);
    expect(chart.movePriceAxis(0, 'right', 'left')).toBe(false);
    expect(chart.panes()[0].usesScale('right')).toBe(true); // nothing moved
    expect(chart.movePriceAxis(0, 'right', 'right')).toBe(false);
  });

  it('draws the ladder in the strip the axis moved to, and leaves the one it left blank', () => {
    const m = mount();
    const base = m.chart.panes()[0].base.ctx as unknown as RecordingContext;
    // Price labels are the numeric ones; the time axis draws clock strings.
    const ladder = (): number[] => base.ops
      .filter((o) => o.type === 'fillText' && !Number.isNaN(Number(o.text)))
      .map((o) => o.args[0]);

    base.ops.length = 0;
    m.chart.applySize(800, 601); // repaint at the same layout
    const right = ladder();
    expect(right.length).toBeGreaterThan(0);
    expect(Math.min(...right)).toBeGreaterThan(744 - 56);

    base.ops.length = 0;
    m.chart.movePriceAxis(0, 'right', 'left');
    const left = ladder();
    expect(left.length).toBeGreaterThan(0);
    expect(Math.max(...left)).toBeLessThan(56);
  });

  it('keeps the crosshair price tag on the axis the prices are labelled in', () => {
    vi.stubGlobal('window', {});
    const m = mount();
    const top = m.chart.panes()[0].top.ctx as unknown as RecordingContext;
    m.chart.movePriceAxis(0, 'right', 'left');
    top.ops.length = 0;
    m.el.dispatch('pointermove', { clientX: 400, clientY: 300, pointerId: 1, pointerType: 'mouse', buttons: 0 });

    const labels = top.ops.filter((o) => o.type === 'fillText' && !Number.isNaN(Number(o.text)));
    expect(labels).toHaveLength(1);
    // The price the cursor is actually over, to the label's own precision,
    // not the 0..1 placeholder of the scale nothing is plotted against now.
    expect(Number(labels[0].text)).toBeCloseTo(m.chart.coordinateToPrice(300, 0) ?? 0, 1);
    expect(labels[0].args[0]).toBeLessThan(0); // drawn back into the left strip
    vi.unstubAllGlobals();
  });

  it('rescales the axis in whichever strip is dragged', () => {
    vi.stubGlobal('window', {});
    const m = mount();
    m.chart.movePriceAxis(0, 'right', 'left');
    const scale = m.chart.panes()[0].scaleFor('left');
    const before = span(scale.priceRange());

    m.el.dispatch('pointerdown', pointer('down', 20, 300));
    m.el.dispatch('pointermove', pointer('move', 20, 400));
    m.el.dispatch('pointerup', pointer('up', 20, 400));

    expect(span(scale.priceRange())).toBeGreaterThan(before); // dragged down: compress
    expect(scale.autoScale).toBe(false);
    vi.unstubAllGlobals();
  });

  it('holds the price-per-bar ratio through a zoom while it is locked', () => {
    const { chart } = mount();
    const scale = chart.panes()[0].priceScale;
    chart.setVisibleLogicalRange({ from: 0, to: 40 });
    const before = scale.priceRange();

    expect(chart.setPriceAxisLockRatio(0, 'right', true)).toBe(true);
    expect(chart.priceAxisState(0, 'right')).toMatchObject({ lockRatio: true, autoFit: false });
    expect(scale.priceRange()).toEqual(before); // locking alone moves nothing

    chart.setVisibleLogicalRange({ from: 20, to: 40 }); // bars twice as wide
    const zoomed = scale.priceRange();
    expect(span(zoomed)).toBeCloseTo(span(before) / 2, 6);
    expect(mid(zoomed)).toBeCloseTo(mid(before), 6);

    chart.setVisibleLogicalRange({ from: 0, to: 40 }); // and back
    expect(span(scale.priceRange())).toBeCloseTo(span(before), 6);
  });

  it('holds it through a change of pane height too', () => {
    const { chart } = mount();
    const scale = chart.panes()[0].priceScale;
    chart.setPriceAxisLockRatio(0, 'right', true);
    const before = scale.priceRange();
    chart.applySize(800, 1178); // twice the plot height
    expect(span(scale.priceRange())).toBeCloseTo(span(before) * 2, 6);
  });

  it('releases the lock when auto-fit is asked for, and on a view reset', () => {
    const { chart } = mount();
    chart.setPriceAxisLockRatio(0, 'right', true);
    chart.setPriceAxisAutoFit(0, 'right', true);
    expect(chart.priceAxisState(0, 'right')).toMatchObject({ lockRatio: false, autoFit: true });

    chart.setPriceAxisLockRatio(0, 'right', true);
    chart.resetScale();
    expect(chart.priceAxisState(0, 'right')).toMatchObject({ lockRatio: false, autoFit: true });
  });

  it('refuses to lock a scale nothing has measured', () => {
    const { chart } = mount();
    // An empty pane: there is no ratio to hold, and pinning it would strand the
    // axis on its placeholder with nothing left to measure it.
    expect(chart.setPriceAxisLockRatio(0, 'left', true)).toBe(false);
    expect(chart.priceAxisState(0, 'left')).toMatchObject({ lockRatio: false, scaled: false });
  });
});
