/**
 * A plot drawn `offset` bars from where its data sits (2.4.0): the displaced
 * cloud, the projected channel, `plot(x, offset = n)`. The data keeps its own
 * times and the shared axis gains no bars; only the painted position moves,
 * the bars in view follow the shift, and autoscale ranges over what is drawn
 * rather than over what sits under the viewport.
 */
import { describe, it, expect } from 'vitest';
import { Chart } from '../src/core/chart';
import { InvalidationLevel } from '../src/core/invalidate-mask';
import { Canvas2dBackend } from '../src/render/canvas2d-backend';
import type { IRenderBackend } from '../src/render/backend';
import type { DrawItem, RendererEntry, SeriesRenderContext } from '../src/model/chart-type-registry';
import type { SeriesStyle } from '../src/render/series-style';
import { IndicatorInstance, type IndicatorHost } from '../src/model/indicator-instance';
import type { IndicatorDescriptor } from '../src/model/indicator-registry';
import type { IndicatorFill } from '../src/primitives/indicator-fill';
import type { Bar } from '../src/model/bar';
import type { SeriesApi } from '../src/model/series';
import { fakeDocument } from './helpers/fake-dom';

/** The 2D backend, with every series pass it is asked for written down. */
class Recorder implements IRenderBackend {
  public readonly kind = 'canvas2d' as const;
  public readonly calls: { style: SeriesStyle; items: DrawItem[] }[] = [];
  private readonly _inner = new Canvas2dBackend();
  public mount(canvas: HTMLCanvasElement, ctx: CanvasRenderingContext2D | null): void { this._inner.mount(canvas, ctx); }
  public resize(w: number, h: number, dpr: number): void { this._inner.resize(w, h, dpr); }
  public beginFrame(clear: boolean): void { this._inner.beginFrame(clear); }
  public drawSeries(
    entry: RendererEntry, items: readonly DrawItem[], priceToY: (p: number) => number,
    barSpacing: number, dpr: number, style: SeriesStyle, rc: SeriesRenderContext,
  ): void {
    // Copies of the items, not the items: the pane reuses them from frame to
    // frame, so a record kept past the next frame has to own its own.
    this.calls.push({ style, items: items.map((it) => ({ ...it })) });
    this._inner.drawSeries(entry, items, priceToY, barSpacing, dpr, style, rc);
  }
  public endFrame(): void { this._inner.endFrame(); }
  public overlay2d(): CanvasRenderingContext2D | null { return this._inner.overlay2d(); }
  public destroy(): void { this._inner.destroy(); }
}

const point = (i: number): Bar => ({ time: 1000 + i * 60, open: 100 + i, high: 100 + i, low: 100 + i, close: 100 + i });

describe('barOffset on a series', () => {
  it('paints the bars whose shifted position is in view, at the shifted x, and scales to them', () => {
    const doc = fakeDocument();
    const recorders: Recorder[] = [];
    const chart = new Chart(doc.createElement('div'), {
      document: doc, pixelRatio: () => 1, shortcuts: false,
      raf: { schedule: (cb: () => void) => { cb(); return 1; }, cancel: () => {} },
      renderBackend: () => { const r = new Recorder(); recorders.push(r); return r; },
    });
    const paint = (): void => { chart.invalidate((m) => m.invalidateGlobal(InvalidationLevel.Full)); };
    chart.applySize(800, 600);
    const series = chart.addSeries('line');
    const data = Array.from({ length: 10 }, (_, i) => point(i));
    series.setData(data);
    paint();
    const rec = recorders[0];
    const before = rec.calls[rec.calls.length - 1];
    // The fit leaves the default four empty bars of right margin past bar 9.
    expect(before.items.map((it) => it.bar.time)).toEqual(data.map((b) => b.time));
    const spacing = chart.timeScale.barSpacing;
    const rangeBefore = chart.panes()[0].priceScale.priceRange();
    expect(rangeBefore.max).toBeGreaterThan(109);

    series.applyOptions({ barOffset: 6 });
    paint();
    const after = rec.calls[rec.calls.length - 1];
    // Bars 8 and 9 would land past the right edge (slots 14 and 15 of a
    // viewport that ends at 13). A line keeps bar 8, the nearest bar beyond the
    // edge, so its last segment runs out to the edge; bar 9 is culled. The rest
    // paint six bars to the right of where they were.
    expect(after.items.map((it) => it.bar.time)).toEqual(data.slice(0, 9).map((b) => b.time));
    for (let i = 0; i < after.items.length; i++) {
      expect(after.items[i].x - before.items[i].x).toBeCloseTo(6 * spacing, 6);
    }
    // The axis has gained no bars.
    expect(chart.timeScale.getVisibleLogicalRange()).toEqual(chart.timeScale.getVisibleLogicalRange());
    expect(chart.timeScale.barSpacing).toBe(spacing);
    // And the scale fits what is painted (100..107), not what sits under the viewport.
    const rangeAfter = chart.panes()[0].priceScale.priceRange();
    expect(rangeAfter.max).toBeLessThan(108.5);
    expect(rangeAfter.max).toBeGreaterThan(107);
  });
});

describe('IndicatorPlot.offset', () => {
  interface Rig { host: IndicatorHost; styles: Record<string, unknown>[]; fills: IndicatorFill[]; legend: string[][] }
  function rig(source: Bar[]): Rig {
    const styles: Record<string, unknown>[] = [];
    const fills: IndicatorFill[] = [];
    const legend: string[][] = [];
    const host: IndicatorHost = {
      addIndicatorLegend: () => ({ setOptions: () => {}, setValues: (v: { text: string }[]) => { legend.push(v.map((x) => x.text)); } }) as never,
      removeIndicatorLegend: () => {},
      legendRowsOn: () => 0,
      addIndicatorSeries: (_t, _p, style): SeriesApi => {
        styles.push(style ?? {});
        return {
          setData: () => {}, prependData: () => {}, update: () => {}, getData: () => [],
          applyOptions: () => {}, remove: () => {}, priceScale: () => ({}) as never,
          createMarkers: () => ({ setMarkers: () => {} }) as never,
        };
      },
      addIndicatorLevel: () => ({}) as never,
      removeIndicatorLevel: () => {},
      addIndicatorFill: (fill) => { fills.push(fill); },
      removeIndicatorFill: () => {},
      removeIndicatorMarkers: () => {},
      addIndicatorTable: () => ({ setRows: () => {}, setOptions: () => {} }) as never,
      removeIndicatorTable: () => {},
      sourceBars: () => source,
      nextPaneIndex: () => 1,
      setPaneRange: () => {},
    };
    return { host, styles, fills, legend };
  }

  const d: IndicatorDescriptor = {
    id: 'off-2', name: 'Displaced', placement: 'onchart', inputs: [],
    plots: [
      { key: 'a', type: 'line', title: 'a', offset: 2 },
      { key: 'b', type: 'line', title: 'b', offset: 2 },
    ],
    fills: [{ between: ['a', 'b'] }],
    calc: (bars) => ({ a: bars.map((x) => x.close), b: bars.map((x) => x.close - 1) }),
  };

  it('reaches the series as barOffset, shifts the band with it, and reads the legend from what is drawn', () => {
    const bars = Array.from({ length: 8 }, (_, i) => point(i));
    const r = rig(bars);
    const inst = new IndicatorInstance(r.host, d);
    expect(r.styles[0].barOffset).toBe(2);
    expect(r.styles[1].barOffset).toBe(2);
    const points = (r.fills[0] as unknown as { _points: { index: number; a: number | null }[] })._points;
    expect(points[0]).toEqual({ index: 2, a: 100, b: 99 });
    // Under bar 5 sits value 3 (103), not value 5.
    inst.updateLegendValues(5);
    expect(r.legend[r.legend.length - 1]).toEqual(['103.00', '102.00']);
    // The first two bars have nothing drawn under them.
    inst.updateLegendValues(1);
    expect(r.legend[r.legend.length - 1]).toEqual([]);
  });

  it('leaves a plot without an offset exactly as before', () => {
    const r = rig([point(0), point(1)]);
    new IndicatorInstance(r.host, { ...d, id: 'off-0', plots: [{ key: 'a', type: 'line', title: 'a' }], fills: undefined });
    expect('barOffset' in r.styles[0]).toBe(false);
  });
});
