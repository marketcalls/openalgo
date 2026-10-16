import { describe, it, expect } from 'vitest';
import { PriceScale } from '../src/scale/price-scale';
import { Chart } from '../src/core/chart';
import { RecordingContext } from './helpers/fake-ctx';
import type { Bar } from '../src/model/bar';

const bar = (time: number, c: number): Bar => ({ time, open: c, high: c + 2, low: c - 2, close: c, volume: 100 });

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
      el.__rec = rec;
      el.getContext = () => rec as unknown as CanvasRenderingContext2D;
    }
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

describe('PriceScale custom formatter', () => {
  it('uses toFixed(precision) by default', () => {
    const ps = new PriceScale({ minMove: 0.01 });
    expect(ps.format(123.456)).toBe('123.46');
  });

  it('routes through a custom formatter when set, and null restores default', () => {
    const ps = new PriceScale({ minMove: 0.01 });
    ps.setPriceFormatter((p) => '$' + p.toFixed(2));
    expect(ps.format(123.456)).toBe('$123.46');
    ps.setPriceFormatter(null);
    expect(ps.format(123.456)).toBe('123.46');
  });
});

describe('Chart.priceFormatter option', () => {
  it('applies the formatter to the pane price scale from options', () => {
    const chart = makeChart({ priceFormatter: (p: number) => '$' + p.toFixed(1) });
    chart.addSeries('candlestick').setData([bar(1000, 90), bar(1060, 100)]);
    const ps = chart.panes()[0].priceScale;
    expect(ps.format(100)).toBe('$100.0');
  });

  it('setPriceFormatter updates every pane at runtime and clears with null', () => {
    const chart = makeChart();
    chart.addSeries('candlestick').setData([bar(1000, 90), bar(1060, 100)]);
    chart.addSeries('histogram', { paneIndex: 1 }).setData([{ time: 1000, open: 0, high: 5, low: 0, close: 5 }]);
    chart.setPriceFormatter((p) => p.toFixed(0) + ' pts');
    for (const pane of chart.panes()) expect(pane.priceScale.format(50)).toBe('50 pts');
    chart.setPriceFormatter(null);
    expect(chart.panes()[0].priceScale.format(50)).not.toContain('pts');
  });
});

/**
 * 2.2.1: `percent` as a declared format, and an indicator plot naming one.
 *
 * The percent case exists because a ratio study has to choose between an axis
 * that reads correctly and a value that reads correctly, and scaling inside
 * `calc` to fix the axis silently changes the legend, the crosshair and every
 * downstream calculation. The formatter suffixes and does not scale, so the two
 * stay in agreement.
 */
describe('priceFormat: percent', () => {
  it('suffixes without scaling, at two decimals by default', () => {
    const chart = makeChart();
    chart.addSeries('line', { priceFormat: { type: 'percent' } })
      .setData([{ time: 1000, value: 62.244 }, { time: 1060, value: 63 }]);
    expect(chart.panes()[0].priceScale.format(62.244)).toBe('62.24%');
    // A 0..1 study keeps its own value rather than being multiplied to look nicer.
    expect(chart.panes()[0].priceScale.format(0.62)).toBe('0.62%');
  });

  it('honours an explicit precision', () => {
    const chart = makeChart();
    chart.addSeries('line', { priceFormat: { type: 'percent', precision: 1 } })
      .setData([{ time: 1000, value: 5 }]);
    expect(chart.panes()[0].priceScale.format(62.244)).toBe('62.2%');
  });
});

describe('IndicatorPlot.priceFormat', () => {
  const bars = Array.from({ length: 40 }, (_, i) => bar(1000 + i * 60, 100 + (i % 7)));

  it('reaches the price scale of the pane the plot lands on', async () => {
    const { registerIndicator } = await import('../src/model/indicator-registry');
    registerIndicator({
      id: 'test-pct-fmt',
      name: 'Percent Study',
      placement: 'pane',
      inputs: [],
      plots: [{
        key: 'v', type: 'line', title: 'V',
        priceFormat: { type: 'percent', precision: 2 },
      }],
      calc: (b) => ({ v: b.map((_, i) => i / 100) }),
    });

    const chart = makeChart();
    chart.addSeries('candlestick').setData(bars);
    chart.addIndicator('test-pct-fmt');
    // The study owns pane 1; pane 0 is the instrument and must be untouched.
    expect(chart.panes()[1].priceScale.format(0.62)).toBe('0.62%');
    expect(chart.panes()[0].priceScale.format(0.62)).not.toContain('%');
  });

  it('a plot that declares no format leaves its scale alone', async () => {
    const { registerIndicator } = await import('../src/model/indicator-registry');
    registerIndicator({
      id: 'test-no-fmt',
      name: 'Plain Study',
      placement: 'pane',
      inputs: [],
      plots: [{ key: 'v', type: 'line', title: 'V' }],
      calc: (b) => ({ v: b.map((_, i) => i / 100) }),
    });
    const chart = makeChart();
    chart.addSeries('candlestick').setData(bars);
    chart.addIndicator('test-no-fmt');
    expect(chart.panes()[1].priceScale.format(0.62)).not.toContain('%');
  });
});
