import { describe, it, expect } from 'vitest';
import { TimeScale } from '../src/scale/time-scale';
import { getChartType } from '../src/model/chart-type-registry';
import { darkTheme, lightTheme } from '../src/theme';
import { Chart } from '../src/core/chart';
import { makeCtx, RecordingContext } from './helpers/fake-ctx';
import type { Bar } from '../src/model/bar';
import { PriceScale } from '../src/scale/price-scale';
import { drawLastPriceLine, drawLastPriceTag } from '../src/render/axis';
import { drawCrosshair } from '../src/render/crosshair';

const di = (x: number, close: number): { x: number; bar: Bar } => ({ x, bar: { time: x, open: close, high: close, low: close, close } });
const bar = (time: number, c: number): Bar => ({ time, open: c, high: c + 1, low: c - 1, close: c });

function recordingDoc(): Document {
  const make = (tag: string): Record<string, unknown> => {
    const el: Record<string, unknown> = {
      tagName: tag.toUpperCase(), style: {}, children: [],
      appendChild(c: unknown) { (el.children as unknown[]).push(c); return c; },
      remove() {}, getBoundingClientRect: () => ({ left: 0, top: 0, width: 800, height: 600 }),
      addEventListener() {}, removeEventListener() {}, setAttribute() {}, getAttribute: () => null, hasAttribute: () => false,
    };
    if (tag === 'canvas') { el.width = 0; el.height = 0; el.getContext = () => new RecordingContext() as unknown as CanvasRenderingContext2D; }
    return el;
  };
  return { createElement: (t: string) => make(t) } as unknown as Document;
}
function makeChart(opts: Record<string, unknown> = {}): Chart {
  const doc = recordingDoc();
  const container = doc.createElement('div') as unknown as Record<string, unknown>;
  container.clientWidth = 800; container.clientHeight = 600;
  return new Chart(container as unknown as HTMLElement, {
    document: doc, pixelRatio: () => 1, raf: { schedule: () => 0, cancel: () => {} }, ...opts,
  });
}

// Parity gaps to replace a third-party charting lib in OpenAlgo.
// Task 3: timeScale.setVisibleLogicalRange (preserve zoom across a data reload).

describe('Task 3: setVisibleLogicalRange', () => {
  it('restores a saved logical window after a reload changes base + zoom', () => {
    const ts = new TimeScale();
    ts.setWidth(600);
    ts.setBaseIndex(199);
    ts.fitContent(200);
    const before = ts.getVisibleLogicalRange();

    // Simulate a full-history reconcile: more bars, refit (jumps to default view).
    ts.setBaseIndex(499);
    ts.fitContent(500);
    expect(ts.visibleRange().to).not.toBeCloseTo(before.to, 1);

    // Restore the saved window.
    ts.setVisibleLogicalRange(before);
    const after = ts.getVisibleLogicalRange();
    expect(after.to).toBeCloseTo(before.to, 3);
    expect(after.from).toBeCloseTo(before.from, 3);
  });

  it('ignores a non-positive span and fires the change handler on apply', () => {
    const ts = new TimeScale();
    ts.setWidth(400);
    ts.setBaseIndex(99);
    ts.fitContent(100);
    let fired = 0;
    ts.setChangeHandler(() => { fired += 1; });
    ts.setVisibleLogicalRange({ from: 50, to: 50 }); // zero span -> no-op
    expect(fired).toBe(0);
    ts.setVisibleLogicalRange({ from: 40, to: 90 }); // valid
    expect(fired).toBe(1);
    expect(ts.visibleRange().to).toBeCloseTo(90, 3);
  });
});

describe('Task 5: dashed / dotted line series', () => {
  const rc = { plotHeight: 100, maxVolume: 0, theme: darkTheme };
  const items = [di(0, 1), di(10, 2), di(20, 1.5)];
  it('applies a dash pattern for a dashed line and none for solid', () => {
    const dashed = makeCtx();
    getChartType('line').draw(dashed.ctx, items, (v) => v, 8, 1, { lineStyle: 'dashed' }, rc);
    expect(dashed.rec.ops.some((o) => o.type === 'setLineDash' && o.args.length > 0)).toBe(true);

    const solid = makeCtx();
    getChartType('line').draw(solid.ctx, items, (v) => v, 8, 1, {}, rc);
    // solid only ever sets an empty dash
    expect(solid.rec.ops.filter((o) => o.type === 'setLineDash').every((o) => o.args.length === 0)).toBe(true);
  });
  it('dotted uses a tighter pattern than dashed', () => {
    const dotted = makeCtx();
    getChartType('line').draw(dotted.ctx, items, (v) => v, 8, 1, { lineStyle: 'dotted' }, rc);
    const set = dotted.rec.ops.find((o) => o.type === 'setLineDash' && o.args.length > 0);
    expect(set?.args[0]).toBe(1); // dotted dash length
  });
});

describe('Task 2: series.applyOptions / remove / visible', () => {
  it('applyOptions recolors and toggles visibility', () => {
    const chart = makeChart();
    const a = chart.addSeries('line');
    a.setData([bar(100, 1), bar(160, 2)]);
    a.applyOptions({ color: '#ff0000', visible: false });
    const rec = chart.panes()[0].series()[0];
    expect(rec.style.color).toBe('#ff0000');
    expect(rec.style.visible).toBe(false);
  });
  it('remove() detaches the series and frees its data', () => {
    const chart = makeChart();
    const a = chart.addSeries('line'); a.setData([bar(100, 1), bar(160, 2)]);
    const b = chart.addSeries('line'); b.setData([bar(100, 3), bar(160, 4)]);
    const c = chart.addSeries('line'); c.setData([bar(100, 5), bar(160, 6)]);
    expect(chart.panes()[0].series().length).toBe(3);
    b.remove(); // remove the middle one
    const left = chart.panes()[0].series();
    expect(left.length).toBe(2);
    // the remaining two are a and c (b gone), and a repaint does not throw
    expect(() => a.applyOptions({ color: '#0f0' })).not.toThrow();
    expect(left[0].style.color).toBe('#0f0');
  });
});

describe('Task 1a: independent per-series price scales + overlay', () => {
  const immediate = { raf: { schedule: (cb: () => void) => { cb(); return 1; }, cancel: () => {} } };
  it('a hidden overlay scale does not move the right price axis (volume overlay)', () => {
    const chart = makeChart(immediate);
    const price = chart.addSeries('candlestick');
    price.setData([bar(100, 100), bar(160, 110)]);
    const ps = price.priceScale();
    const yTop = ps.priceToY(110);
    const yBot = ps.priceToY(100);

    const vol = chart.addSeries('histogram', { priceScaleId: '' });
    vol.setData([{ time: 100, open: 0, high: 0, low: 0, close: 5000 }, { time: 160, open: 0, high: 0, low: 0, close: 9000 }]);

    expect(ps.priceToY(110)).toBeCloseTo(yTop, 3); // unchanged by huge volume values
    expect(ps.priceToY(100)).toBeCloseTo(yBot, 3);
    expect(vol.priceScale()).not.toBe(ps); // a separate overlay scale
  });
  it('left and right scales autoscale independently', () => {
    const chart = makeChart(immediate);
    const r = chart.addSeries('line', { priceScaleId: 'right' });
    r.setData([bar(100, 10), bar(160, 20)]);
    const l = chart.addSeries('line', { priceScaleId: 'left' });
    l.setData([bar(100, 1000), bar(160, 2000)]);
    const rs = r.priceScale();
    const ls = l.priceScale();
    expect(rs).not.toBe(ls);
    expect(rs.priceToY(20)).toBeLessThan(rs.priceToY(10)); // higher price -> smaller y
    expect(ls.priceToY(2000)).toBeLessThan(ls.priceToY(1000));
    // right scale is unaffected by the left series' huge magnitudes
    expect(rs.priceToY(20)).toBeCloseTo(ls.priceToY(2000), 0);
  });
  it('series.priceScale().setOptions pins the overlay to the bottom via margins', () => {
    const chart = makeChart(immediate);
    chart.addSeries('candlestick').setData([bar(100, 100), bar(160, 110)]);
    const vol = chart.addSeries('histogram', { priceScaleId: '' });
    vol.priceScale().setOptions({ marginTop: 0.8, marginBottom: 0 });
    expect(vol.priceScale().options.marginTop).toBe(0.8);
    expect(vol.priceScale().options.marginBottom).toBe(0);
  });
});

describe('Task 1b: reserved left-axis column', () => {
  const immediate = { raf: { schedule: (cb: () => void) => { cb(); return 1; }, cancel: () => {} } };
  it('reserves a left-axis column (shrinks the plot) when a left scale is used, and frees it on remove', () => {
    const chart = makeChart(immediate);
    chart.addSeries('line').setData([bar(100, 1), bar(160, 2)]);
    const widthNoLeft = chart.timeScale.width;

    const left = chart.addSeries('line', { priceScaleId: 'left' });
    left.setData([bar(100, 10), bar(160, 20)]);
    expect(chart.timeScale.width).toBeLessThan(widthNoLeft); // left column reserved

    left.remove();
    expect(chart.timeScale.width).toBe(widthNoLeft); // column freed
  });
});

describe('Task 4: per-series priceFormat', () => {
  const immediate = { raf: { schedule: (cb: () => void) => { cb(); return 1; }, cancel: () => {} } };
  it('a custom formatter formats the series axis (currency)', () => {
    const chart = makeChart(immediate);
    const s = chart.addSeries('line', { priceFormat: { type: 'custom', formatter: (v) => 'Rs ' + v.toFixed(2) } });
    s.setData([bar(100, 10), bar(160, 20)]);
    expect(s.priceScale().format(15)).toBe('Rs 15.00');
  });
  it('volume format is compact', () => {
    const chart = makeChart(immediate);
    const v = chart.addSeries('histogram', { priceScaleId: '', priceFormat: { type: 'volume' } });
    expect(v.priceScale().format(1_500_000)).toBe('1.50M');
    expect(v.priceScale().format(12_300)).toBe('12.30K');
  });
  it('price precision derives from minMove', () => {
    const chart = makeChart(immediate);
    const s = chart.addSeries('line', { priceFormat: { type: 'price', minMove: 0.05 } });
    expect(s.priceScale().format(100.123)).toBe('100.12');
  });
});

describe('Task 6: chart.applyOptions (runtime theme / grid)', () => {
  const immediate = { raf: { schedule: (cb: () => void) => { cb(); return 1; }, cancel: () => {} } };
  it('swaps theme and grid live without recreating the chart', () => {
    const chart = makeChart(immediate);
    chart.addSeries('line').setData([bar(100, 1), bar(160, 2)]);
    expect(chart.gridOptions().vertLines).toBe(true);
    chart.applyOptions({ theme: lightTheme, grid: { vertLines: false } });
    expect(chart.gridOptions().vertLines).toBe(false);
    expect(chart.gridOptions().horzLines).toBe(true);
    // theme swap applies without throwing and repaints
    expect(() => chart.setTheme(darkTheme)).not.toThrow();
  });
});

describe('Task 7: cosmetic parity', () => {
  const immediate = { raf: { schedule: (cb: () => void) => { cb(); return 1; }, cancel: () => {} } };
  it('no-arg fitContent() fits all bars without throwing', () => {
    const chart = makeChart(immediate);
    const s = chart.addSeries('line');
    s.setData(Array.from({ length: 50 }, (_, i) => bar(100 + i * 60, 10 + i)));
    expect(() => chart.fitContent()).not.toThrow();
    const r = chart.getVisibleLogicalRange();
    expect(r.to - r.from).toBeGreaterThan(40); // ~50 bars visible
  });
  it('transparent theme skips the background fill', () => {
    const chart = makeChart(immediate);
    chart.addSeries('line').setData([bar(100, 1), bar(160, 2)]);
    const rec = (chart.panes()[0].base as unknown as { ctx: RecordingContext }).ctx;
    rec.ops.length = 0;
    chart.setTheme({ ...darkTheme, background: 'transparent' });
    // background fillRect covers the full pane; with transparent it must be absent
    const full = rec.ops.filter((o) => o.type === 'fillRect' && o.args[0] === 0 && o.args[1] === 0);
    expect(full.length).toBe(0);
  });
  it('dotted grid style sets a dash on the grid stroke', () => {
    const chart = makeChart(immediate);
    chart.addSeries('line').setData([bar(100, 1), bar(160, 2)]);
    const rec = (chart.panes()[0].base as unknown as { ctx: RecordingContext }).ctx;
    rec.ops.length = 0;
    chart.setTheme({ ...darkTheme, gridStyle: 'dotted' });
    expect(rec.ops.some((o) => o.type === 'setLineDash' && o.args.length > 0)).toBe(true);
  });
});

describe('Gap 1: title / priceLineVisible / lastValueVisible', () => {
  const immediate = { raf: { schedule: (cb: () => void) => { cb(); return 1; }, cancel: () => {} } };
  const layout = { plotWidth: 200, plotHeight: 100, priceAxisWidth: 60, timeAxisHeight: 20, plotLeft: 0 };
  const ps = () => { const s = new PriceScale(); s.setHeight(100); s.autoscale(10, 20); return s; };

  it('draws the last-price line and its tag separately', () => {
    const lineOnly = makeCtx();
    drawLastPriceLine(lineOnly.ctx, ps(), 15, true, layout, 1);
    expect(lineOnly.rec.ops.some((o) => o.type === 'stroke')).toBe(true);
    expect(lineOnly.rec.ops.some((o) => o.type === 'fillRect')).toBe(false); // no tag box

    const tagOnly = makeCtx();
    drawLastPriceTag(tagOnly.ctx, ps(), 15, true, layout, 1);
    expect(tagOnly.rec.ops.some((o) => o.type === 'fillRect')).toBe(true);
    expect(tagOnly.rec.ops.some((o) => o.type === 'stroke')).toBe(false); // no line
  });

  it('priceLineVisible:false hides the last-price line on the pane (default shows it)', () => {
    const off = makeChart(immediate);
    off.addSeries('candlestick', { style: { priceLineVisible: false } }).setData([bar(100, 10), bar(160, 20)]);
    const recOff = (off.panes()[0].base as unknown as { ctx: RecordingContext }).ctx;
    const lineOff = recOff.ops.some((o) => o.type === 'setLineDash' && o.args[0] === 3 && o.args[1] === 3);
    expect(lineOff).toBe(false);

    const on = makeChart(immediate);
    on.addSeries('candlestick').setData([bar(100, 10), bar(160, 20)]);
    const recOn = (on.panes()[0].base as unknown as { ctx: RecordingContext }).ctx;
    const lineOn = recOn.ops.some((o) => o.type === 'setLineDash' && o.args[0] === 3 && o.args[1] === 3);
    expect(lineOn).toBe(true);
  });
});

describe('Gap 2: crosshair line styling', () => {
  it('drawCrosshair applies the given dash pattern', () => {
    const g = makeCtx();
    drawCrosshair(g.ctx, 50, 25, 200, 100, 1, '#fff', 2, [1, 3]);
    const dash = g.rec.ops.find((o) => o.type === 'setLineDash' && o.args.length > 0);
    expect(dash?.args).toEqual([1, 3]);
  });
});

describe('Gap 3: tickMarkType hint in timeFormatter', () => {
  const immediate = { raf: { schedule: (cb: () => void) => { cb(); return 1; }, cancel: () => {} } };
  it('a custom timeFormatter receives a boundary hint', () => {
    const seen = new Set<string>();
    const chart = makeChart({ ...immediate, timeFormatter: (t: number, tm?: string) => { if (tm) seen.add(tm); return String(t); } });
    const bars: Bar[] = [];
    let t = 1703030400; // 2023-12-20 UTC, spans into 2024
    for (let i = 0; i < 45; i++) { bars.push(bar(t, 100 + i)); t += 86400; }
    chart.addSeries('candlestick').setData(bars);
    chart.fitContent();
    expect(seen.size).toBeGreaterThan(0);
    expect(seen.has('day')).toBe(true);
  });
});
