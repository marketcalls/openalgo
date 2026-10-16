import { afterEach, describe, expect, it } from 'vitest';
import { Chart, type ChartOptions } from '../src/core/chart';
import { fakeDocument } from './helpers/fake-dom';

const charts: Chart[] = [];
afterEach(() => { for (const chart of charts.splice(0)) chart.destroy(); });

function fixture(options: Partial<ChartOptions> = {}) {
  let now = 0;
  let id = 0;
  const queue = new Map<number, () => void>();
  const doc = fakeDocument();
  const chart = new Chart(doc.createElement('div'), {
    document: doc, pixelRatio: () => 1, shortcuts: false, now: () => now,
    raf: { schedule: cb => { queue.set(++id, cb); return id; }, cancel: key => { queue.delete(key); } },
    ...options,
  });
  charts.push(chart);
  const tick = (ms = 16) => {
    now += ms;
    const due = [...queue.entries()];
    for (const [key, cb] of due) if (queue.delete(key)) cb();
  };
  const settle = () => { for (let i = 0; i < 120 && queue.size; i++) tick(); };
  chart.applySize(800, 600);
  const series = chart.addSeries('candlestick');
  series.setData(Array.from({ length: 500 }, (_, i) => ({ time: 1700000000 + i * 60, open: 23800, high: i === 392 ? 24200 : 23810, low: 23790, close: 23805 })));
  chart.setVisibleLogicalRange({ from: 400, to: 499 });
  settle();
  const wheel = (deltaY: number, extra: Record<string, unknown> = {}) => {
    (chart as unknown as { _onWheel: (e: unknown) => void })._onWheel({
      clientX: 400, clientY: 200, deltaX: 0, deltaY, deltaMode: 0, preventDefault() {}, ...extra,
    });
  };
  return { chart, series, tick, settle, wheel, queue };
}

describe('wheel navigation', () => {
  it('scales tiny movement proportionally and keeps a coarse notch compatible', () => {
    const tiny = fixture({ animZoom: false });
    const coarse = fixture({ animZoom: false });
    const spacing = tiny.chart.timeScale.barSpacing;
    tiny.wheel(-1); coarse.wheel(-100);
    expect(tiny.chart.timeScale.barSpacing / spacing).toBeCloseTo(1.0009535561, 9);
    expect(coarse.chart.timeScale.barSpacing / spacing).toBeCloseTo(1.1, 9);
  });

  it('ignores zero and invalid input without interrupting a zoom', () => {
    const f = fixture(); const spacing = f.chart.timeScale.barSpacing;
    f.wheel(-100); f.wheel(0); f.wheel(NaN); f.settle();
    expect(f.chart.timeScale.barSpacing).toBeCloseTo(spacing * 1.1, 9);
  });

  it.each([{ deltaX: 80 }, { deltaY: 80, shiftKey: true }, { deltaX: 80, deltaY: 3 }])('pans horizontal gestures without changing spacing: %j', extra => {
    const f = fixture(); const spacing = f.chart.timeScale.barSpacing;
    const before = f.chart.getVisibleLogicalRange();
    f.wheel(0, extra); f.settle();
    expect(f.chart.timeScale.barSpacing).toBe(spacing);
    expect(f.chart.getVisibleLogicalRange().from).toBeGreaterThan(before.from);
  });

  it('normalizes line and page wheel units', () => {
    const pixel = fixture({ animZoom: false }); const line = fixture({ animZoom: false });
    pixel.wheel(-48); line.wheel(-3, { deltaMode: 1 });
    expect(line.chart.timeScale.barSpacing).toBeCloseTo(pixel.chart.timeScale.barSpacing, 10);
    const page = fixture({ animZoom: false }); const pagePixels = fixture({ animZoom: false });
    page.wheel(-0.1, { deltaMode: 2 }); pagePixels.wheel(-60);
    expect(page.chart.timeScale.barSpacing).toBeCloseTo(pagePixels.chart.timeScale.barSpacing, 10);
  });

  it('uses the price axis under the pointer and preserves its price anchor', () => {
    const f = fixture(); const scale = f.chart.panes()[0].priceScale;
    const spacing = f.chart.timeScale.barSpacing; const before = scale.priceRange();
    const price = scale.yToPrice(200);
    f.wheel(-100, { clientX: 790 }); f.settle();
    expect(f.chart.timeScale.barSpacing).toBe(spacing);
    expect(scale.priceRange().max - scale.priceRange().min).toBeLessThan(before.max - before.min);
    expect(scale.priceToY(price)).toBeCloseTo(200, 8);
    expect(scale.autoScale).toBe(false);
  });

  it('retains a pending large zoom when tiny input arrives or the cursor moves', () => {
    const f = fixture(); const spacing = f.chart.timeScale.barSpacing;
    f.wheel(-100); f.tick(); f.wheel(-1, { clientX: 450 }); f.settle();
    expect(f.chart.timeScale.barSpacing / spacing).toBeCloseTo(1.1010489117, 8);
  });

  it('rapid opposite input returns to the original spacing', () => {
    const f = fixture(); const spacing = f.chart.timeScale.barSpacing;
    for (let i = 0; i < 4; i++) { f.wheel(-100); f.tick(); }
    for (let i = 0; i < 4; i++) { f.wheel(100); f.tick(); }
    f.settle(); expect(f.chart.timeScale.barSpacing).toBeCloseTo(spacing, 9);
  });

  it('does not let an old glide overwrite a programmatic viewport', () => {
    const f = fixture(); f.wheel(-100); f.tick();
    f.chart.setVisibleLogicalRange({ from: 100, to: 199 });
    const before = f.chart.getVisibleLogicalRange(); f.settle();
    expect(f.chart.getVisibleLogicalRange()).toEqual(before);
  });

  it('keeps the cursor anchor correct when a left price axis is visible', () => {
    const f = fixture({ animZoom: false });
    const left = f.chart.addSeries('line', { priceScaleId: 'left' });
    left.setData(f.series.getData().map(bar => ({ time: bar.time, value: 1000 })));
    f.settle();
    const rightBefore = f.chart.panes()[0].priceScale.priceRange();
    const before = left.priceScale().priceRange();
    f.wheel(-100, { clientX: 10 }); f.settle();
    expect(left.priceScale().priceRange().max - left.priceScale().priceRange().min).toBeLessThan(before.max - before.min);
    expect(f.chart.panes()[0].priceScale.priceRange()).toEqual(rightBefore);
    const leftWidth = 800 - 56 - f.chart.timeScale.width;
    const index = f.chart.timeScale.xToIndex(400 - leftWidth);
    f.wheel(-100); f.settle();
    expect(f.chart.timeScale.indexToX(index) + leftWidth).toBeCloseTo(400, 8);
  });

  it('does not accumulate hidden zoom beyond the spacing limit', () => {
    const f = fixture();
    for (let i = 0; i < 60; i++) f.wheel(-100);
    f.wheel(100); f.settle();
    expect(f.chart.timeScale.barSpacing).toBeCloseTo(80 / 1.1, 8);
  });

  it('cancels a pending zoom when replacing primary data or resetting', () => {
    const f = fixture(); f.wheel(-100);
    f.series.setData(f.series.getData());
    const spacing = f.chart.timeScale.barSpacing; f.settle();
    expect(f.chart.timeScale.barSpacing).toBe(spacing);
    f.wheel(-100); f.chart.resetScale();
    const range = f.chart.getVisibleLogicalRange(); f.settle();
    expect(f.chart.getVisibleLogicalRange()).toEqual(range);
  });

  it('honors a viewport replacement inside a zoom event callback', () => {
    const f = fixture();
    f.chart.on('zoom', () => f.chart.setVisibleLogicalRange({ from: 100, to: 199 }));
    f.wheel(-100); f.settle();
    expect(f.chart.getVisibleLogicalRange()).toEqual({ from: 100, to: 199 });
  });

  it('stops inertial pan when a host replaces the viewport during a pan event', () => {
    const f = fixture();
    const off = f.chart.on('pan', () => {
      off();
      f.chart.setVisibleLogicalRange({ from: 100, to: 199 });
    });
    (f.chart as unknown as { _startKinetic: (velocity: number) => void })._startKinetic(0.5);
    f.tick(); f.settle();
    expect(f.chart.getVisibleLogicalRange()).toEqual({ from: 100, to: 199 });
  });

  it('leaves no queued animation after destruction', () => {
    const f = fixture(); f.wheel(-100); f.tick(); f.chart.destroy();
    f.settle(); expect(f.queue.size).toBe(0);
  });

  it('eases the price projection when zoom reveals an extreme and settles exactly', () => {
    const f = fixture({ animZoom: false, animAutoscale: true });
    const scale = f.chart.panes()[0].priceScale;
    const before = scale.priceToY(23800);
    f.wheel(200, { clientX: 730 }); f.tick();
    const first = scale.priceToY(23800); f.settle();
    const last = scale.priceToY(23800);
    expect(Math.abs(last - before)).toBeGreaterThan(100);
    expect(Math.abs(first - before)).toBeLessThan(Math.abs(last - before) * 0.4);
    expect(scale.priceRange()).toEqual({ min: 23738.75, max: 24251.25 });
  });
});
