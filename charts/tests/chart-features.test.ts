import { describe, it, expect } from 'vitest';
import { Chart } from '../src/core/chart';
import { Pane, type PaneRenderContext } from '../src/core/pane';
import { TimeScale } from '../src/scale/time-scale';
import { DataLayer } from '../src/model/data-layer';
import { createSeriesRecord } from '../src/model/series';
import { darkTheme } from '../src/theme';
import { fakeDocument } from './helpers/fake-dom';
import { RecordingContext } from './helpers/fake-ctx';
import type { Bar } from '../src/model/bar';

const bar = (time: number, c: number): Bar => ({ time, open: c, high: c + 2, low: c - 2, close: c, volume: 100 });

// A fake document whose canvases each keep their own recording context on `__rec`,
// so a composited output canvas can be inspected after takeScreenshot().
function recordingDoc(): Document {
  const make = (tag: string): Record<string, unknown> => {
    const el: Record<string, unknown> = {
      tagName: tag.toUpperCase(), style: {}, children: [],
      appendChild(c: unknown) { (el.children as unknown[]).push(c); return c; },
      remove() {},
      getBoundingClientRect: () => ({ left: 0, top: 0, width: 800, height: 600 }),
      addEventListener() {}, removeEventListener() {},
      setAttribute() {}, getAttribute: () => null, hasAttribute: () => false,
    };
    if (tag === 'canvas') {
      el.width = 0; el.height = 0;
      const rec = new RecordingContext();
      const drawImage = rec.drawImage.bind(rec);
      rec.drawImage = (image: unknown, x: number, y: number): void => {
        const source = image as HTMLCanvasElement;
        if (source.width === 0 || source.height === 0) throw new Error('Cannot composite an empty canvas');
        drawImage(image, x, y);
      };
      el.__rec = rec;
      el.getContext = () => rec as unknown as CanvasRenderingContext2D;
    }
    return el;
  };
  return { createElement: (t: string) => make(t) } as unknown as Document;
}

describe('takeScreenshot composites every layer', () => {
  it('exports only the visible pane when maximized and resumes the full stack when restored', () => {
    const doc = recordingDoc();
    const chart = new Chart(doc.createElement('div'), {
      document: doc, pixelRatio: () => 2,
      raf: { schedule: (cb) => { cb(); return 1; }, cancel: () => {} },
    });
    chart.applySize(800, 600);
    chart.addSeries('candlestick').setData([bar(1000, 10), bar(1060, 11)]);
    chart.addSeries('line', { paneIndex: 1 }).setData([bar(1000, 10), bar(1060, 11)]);
    chart.maximizePane(1);
    expect(chart.panes()[0].base.element.height).toBe(0);
    const shot = chart.takeScreenshot() as unknown as { width: number; height: number; __rec: RecordingContext };
    expect([shot.width, shot.height]).toEqual([1600, 1200]);
    expect(shot.__rec.ops.filter((op) => op.type === 'drawImage').map((op) => op.args)).toEqual([[0, 0], [0, 0]]);
    chart.maximizePane(1);
    const restored = chart.takeScreenshot() as unknown as { __rec: RecordingContext };
    expect(restored.__rec.count('drawImage')).toBe(4);
    chart.applySize(0, 0);
    const hidden = chart.takeScreenshot() as unknown as { __rec: RecordingContext };
    expect(hidden.__rec.count('drawImage')).toBe(0);
    chart.destroy();
  });

  it('flattens all panes (base + overlay) into one device-px canvas', () => {
    const doc = recordingDoc();
    const container = doc.createElement('div') as unknown as Record<string, unknown>;
    container.clientWidth = 800; container.clientHeight = 600;
    const chart = new Chart(container as unknown as HTMLElement, {
      document: doc, pixelRatio: () => 2, raf: { schedule: () => 0, cancel: () => {} },
    });
    chart.addSeries('candlestick').setData([bar(1000, 10), bar(1060, 11)]);
    chart.addSeries('histogram', { paneIndex: 1 }).setData([{ time: 1000, open: 0, high: 5, low: 0, close: 5 }]);

    const shot = chart.takeScreenshot() as unknown as { width: number; height: number; __rec: RecordingContext };
    expect(shot.width).toBe(1600);  // 800 media px * dpr 2
    expect(shot.height).toBe(1200); // 600 media px * dpr 2
    // 2 panes × (base + top overlay) = 4 drawImage calls
    expect(shot.__rec.count('drawImage')).toBe(4);
  });
});

describe('price <-> coordinate conversion', () => {
  it('round-trips a price through priceToCoordinate / coordinateToPrice', () => {
    const doc = recordingDoc();
    const container = doc.createElement('div') as unknown as Record<string, unknown>;
    container.clientWidth = 800; container.clientHeight = 600;
    const chart = new Chart(container as unknown as HTMLElement, {
      document: doc, pixelRatio: () => 1, raf: { schedule: (cb) => { cb(); return 1; }, cancel: () => {} },
    });
    chart.addSeries('candlestick').setData([bar(1000, 90), bar(1060, 100), bar(1120, 110)]);
    const y = chart.priceToCoordinate(100);
    expect(y).not.toBeNull();
    expect(chart.coordinateToPrice(y as number)).toBeCloseTo(100, 6);
    expect(chart.priceToCoordinate(100, 5)).toBeNull(); // no such pane
  });

  it('resetScale re-fits and keeps prices mappable', () => {
    const doc = recordingDoc();
    const container = doc.createElement('div') as unknown as Record<string, unknown>;
    container.clientWidth = 800; container.clientHeight = 600;
    const chart = new Chart(container as unknown as HTMLElement, {
      document: doc, pixelRatio: () => 1, raf: { schedule: (cb) => { cb(); return 1; }, cancel: () => {} },
    });
    chart.addSeries('candlestick').setData([bar(1000, 90), bar(1060, 100), bar(1120, 110)]);
    expect(() => chart.resetScale()).not.toThrow();
    expect(Number.isFinite(chart.priceToCoordinate(100) as number)).toBe(true);
  });
});

describe('grid line toggle', () => {
  const dl = new DataLayer();
  const id = dl.createSeries();
  dl.setSeriesData(id, [bar(1000, 10), bar(1060, 11), bar(1120, 12)]);
  const ts = new TimeScale({ barSpacing: 30 });
  ts.setWidth(600);
  ts.setBaseIndex(dl.baseIndex);

  const context = (showVertGrid: boolean, showHorzGrid: boolean): PaneRenderContext => ({
    timeScale: ts, dataLayer: dl, dpr: 1, priceAxisWidth: 56, timeAxisHeight: 22,
    showTimeAxis: true, conflate: false, conflationFactor: 1, theme: darkTheme,
    showVertGrid, showHorzGrid,
  });

  // moveTo count: every other element is identical between renders, so the delta
  // is purely the grid lines that were (or weren't) drawn.
  function moveTos(showVertGrid: boolean, showHorzGrid: boolean): number {
    const pane = new Pane(fakeDocument());
    pane.addSeries(createSeriesRecord(id, 'candlestick'));
    pane.resize(600, 400, 1);
    pane.paintBase(context(showVertGrid, showHorzGrid));
    return (pane.base.ctx as unknown as RecordingContext).count('moveTo');
  }

  it('draws no grid lines when both are disabled, more when enabled', () => {
    const off = moveTos(false, false);
    const both = moveTos(true, true);
    const vOnly = moveTos(true, false);
    const hOnly = moveTos(false, true);
    expect(both).toBeGreaterThan(off);
    expect(vOnly).toBeGreaterThan(off);
    expect(hOnly).toBeGreaterThan(off);
    // vertical and horizontal lines add independently
    expect(both).toBe(off + (vOnly - off) + (hOnly - off));
  });

  it('exposes runtime grid state via gridOptions()', () => {
    const doc = recordingDoc();
    const container = doc.createElement('div') as unknown as Record<string, unknown>;
    container.clientWidth = 800; container.clientHeight = 600;
    const chart = new Chart(container as unknown as HTMLElement, {
      document: doc, raf: { schedule: () => 0, cancel: () => {} }, grid: { vertLines: false },
    });
    expect(chart.gridOptions()).toEqual({ vertLines: false, horzLines: true });
    chart.setGridOptions({ horzLines: false });
    expect(chart.gridOptions()).toEqual({ vertLines: false, horzLines: false });
  });
});
