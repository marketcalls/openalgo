import { describe, expect, it } from 'vitest';
import { Pane, type PaneRenderContext } from '../src/core/pane';
import { DataLayer } from '../src/model/data-layer';
import { createSeriesRecord, type PriceScaleId } from '../src/model/series';
import { TimeScale } from '../src/scale/time-scale';
import { PriceScale } from '../src/scale/price-scale';
import { drawLastPriceTag, drawSeriesValueTag, type BarCountdownOptions, type PlotLayout } from '../src/render/axis';
import type { SeriesStyle } from '../src/render/series-style';
import { SvgContext } from '../src/render/svg-export';
import { darkTheme } from '../src/theme';
import { fakeDocument } from './helpers/fake-dom';
import { RecordingContext, type Op } from './helpers/fake-ctx';

const layout: PlotLayout = { plotWidth: 600, plotHeight: 400, plotLeft: 56, priceAxisWidth: 56, timeAxisHeight: 0 };
const countdown: BarCountdownOptions = { visible: true, lastBarTime: 1000, intervalSec: 60, now: () => 1020 };

class FontContext extends RecordingContext {
  public override measureText(text: string): { width: number } {
    const size = Number(this.font.split(' ').find(part => part.endsWith('px'))?.slice(0, -2) ?? 10);
    return { width: text.length * size * 0.6 };
  }
}

function scale(height = 400): PriceScale {
  const result = new PriceScale();
  result.setHeight(height); result.setPriceRange({ min: 90, max: 110 });
  return result;
}

function rectBefore(rec: RecordingContext, label: string): Op | undefined {
  const index = rec.ops.findIndex(op => op.type === 'fillText' && op.text === label);
  if (index < 0) return undefined;
  return rec.ops.slice(0, index).reverse().find(op => op.type === 'fillRect');
}

function paneFixture(specs: { id: PriceScaleId; value: number; style?: SeriesStyle }[], showCountdown = false) {
  const pane = new Pane(fakeDocument()), dataLayer = new DataLayer(), timeScale = new TimeScale({ barSpacing: 30 });
  for (const spec of specs) {
    const id = dataLayer.createSeries();
    dataLayer.setSeriesData(id, [0, 1, 2].map(index => ({ time: 1000 + index * 60,
      open: spec.value, high: spec.value, low: spec.value, close: spec.value })));
    const record = createSeriesRecord(id, 'line', { color: '#2277cc', ...spec.style }, spec.id);
    pane.addSeries(record);
    // The first series is the chart's price source, as a chart's first price
    // series is, and the pane holding the source is the one with the countdown.
    if (spec === specs[0]) pane.setSourceSeries(record);
  }
  pane.resize(712, 400, 1);
  timeScale.setBaseIndex(dataLayer.baseIndex); timeScale.setWidth(600);
  const context: PaneRenderContext = { timeScale, dataLayer, dpr: 1, priceAxisWidth: 56, leftAxisWidth: 56,
    timeAxisHeight: 0, showTimeAxis: false, conflate: false, conflationFactor: 1, theme: darkTheme,
    showVertGrid: false, showHorzGrid: false, barCountdown: showCountdown ? countdown : undefined };
  for (const id of ['right', 'left', '', 'overlay:hidden'] as const) {
    const target = pane.scaleFor(id);
    target.setHeight(400); target.setPriceRange({ min: 90, max: 110 });
    target.setPriceFormatter(value => `${id === 'left' ? 'L' : id === 'right' ? 'R' : 'H'}:${value.toFixed(2)}`);
  }
  const rec = new FontContext();
  const paint = () => { rec.ops = []; pane.paintBase(context, rec as unknown as CanvasRenderingContext2D); return rec; };
  return { pane, context, rec, paint };
}

describe('left-axis tag geometry', () => {
  it.each([1, 2])('keeps long price and countdown text inside the left column at dpr %s', dpr => {
    const rec = new FontContext(), priceScale = scale();
    priceScale.setPriceFormatter(() => 'LONG:123456789.0123');
    drawLastPriceTag(rec as unknown as CanvasRenderingContext2D, priceScale, 100, true, layout, dpr,
      undefined, { countdown, side: 'left' });
    const box = rec.ops.find(op => op.type === 'fillRect')!;
    expect(box).toBeDefined();
    expect(box.args[0]).toBeGreaterThanOrEqual(-layout.plotLeft * dpr);
    expect(box.args[0] + box.args[2]).toBeLessThanOrEqual(0);
    const texts = rec.ops.filter(op => op.type === 'fillText');
    expect(texts.map(op => op.text)).toEqual(['LONG:123456789.0123', '00:00:40']);
    for (const text of texts) {
      const size = Number(/([\d.]+)px/.exec(text.font!)![1]);
      expect(text.args[0]).toBeGreaterThanOrEqual(box.args[0]);
      expect(text.args[0] + text.text!.length * size * 0.6).toBeLessThanOrEqual(box.args[0] + box.args[2] + 0.001);
    }
  });

  it.each([90, 110])('keeps the whole left tag within the pane at price %s', price => {
    const rec = new FontContext();
    drawSeriesValueTag(rec as unknown as CanvasRenderingContext2D, scale(), price, '#cc5500', layout, 1, undefined, 'left');
    const box = rec.ops.find(op => op.type === 'fillRect')!;
    expect(box.args[0] + box.args[2]).toBeLessThanOrEqual(0);
    expect(box.args[1]).toBeGreaterThanOrEqual(0);
    expect(box.args[1] + box.args[3]).toBeLessThanOrEqual(layout.plotHeight);
  });

  it('omits a left tag when there is no column or not enough vertical room', () => {
    for (const tiny of [{ ...layout, plotLeft: 0 }, { ...layout, plotHeight: 10 }]) {
      const rec = new FontContext();
      drawLastPriceTag(rec as unknown as CanvasRenderingContext2D, scale(tiny.plotHeight), 100, true,
        tiny, 1, undefined, { countdown, side: 'left' });
      expect(rec.ops.some(op => op.type === 'fillRect' || op.type === 'fillText')).toBe(false);
    }
  });

  it('fits oversized fonts vertically within each left tag row', () => {
    const rec = new FontContext(), priceScale = scale();
    priceScale.setPriceFormatter(() => '1');
    drawLastPriceTag(rec as unknown as CanvasRenderingContext2D, priceScale, 100, true, layout, 1,
      { textColor: '#ffffff', lineColor: '#888888', font: '48px sans-serif' }, { countdown, side: 'left' });
    for (const text of rec.ops.filter(op => op.type === 'fillText')) {
      expect(Number(/([\d.]+)px/.exec(text.font!)![1])).toBeLessThanOrEqual(12);
    }
  });
});

describe('per-axis current value labels', () => {
  it('draws the left readout countdown and secondary value with their own fills', () => {
    const { paint } = paneFixture([{ id: 'left', value: 100.25 },
      { id: 'left', value: 104.25, style: { color: '#cc5500' } }], true);
    const rec = paint();
    expect(rectBefore(rec, 'L:100.25')?.fillStyle).toBe(darkTheme.lastPriceUp);
    expect(rectBefore(rec, 'L:104.25')?.fillStyle).toBe('#cc5500');
    expect(rec.ops.filter(op => op.text === '00:00:40')).toHaveLength(1);
    for (const label of ['L:100.25', 'L:104.25']) {
      const box = rectBefore(rec, label)!;
      expect(box.args[0] + box.args[2]).toBeLessThanOrEqual(0);
    }
  });

  it.each(['right', 'left'] as const)('labels both source scales when the readout is %s', first => {
    const second = first === 'right' ? 'left' : 'right';
    const { paint } = paneFixture([{ id: first, value: 100.25 },
      { id: second, value: 100.25, style: { color: '#aa44cc' } }], true);
    const rec = paint();
    const left = rectBefore(rec, 'L:100.25')!, right = rectBefore(rec, 'R:100.25')!;
    expect(left).toBeDefined(); expect(right).toBeDefined();
    expect(left.args[0] + left.args[2]).toBeLessThanOrEqual(0);
    expect(right.args[0]).toBeGreaterThanOrEqual(layout.plotWidth);
    expect(rec.ops.filter(op => op.text === '00:00:40')).toHaveLength(1);
    expect((first === 'left' ? right : left).fillStyle).toBe('#aa44cc');
  });

  it('resolves collisions within one axis without suppressing the same price on the other axis', () => {
    const { paint } = paneFixture([{ id: 'left', value: 100.25 },
      { id: 'left', value: 100.3, style: { color: '#aa44cc' } },
      { id: 'right', value: 100.3, style: { color: '#cc5500' } }]);
    const rec = paint();
    expect(rec.ops.some(op => op.text === 'L:100.30')).toBe(false);
    expect(rectBefore(rec, 'R:100.30')?.fillStyle).toBe('#cc5500');
    const primary = rectBefore(rec, 'L:100.25')!;
    const ticks = rec.ops.filter(op => op.type === 'fillText' && op.text?.startsWith('L:') && op.fillStyle === darkTheme.axisText);
    expect(ticks.length).toBeGreaterThan(2);
    for (const tick of ticks) expect(Math.abs(tick.args[1] - (primary.args[1] + primary.args[3] / 2))).toBeGreaterThanOrEqual(primary.args[3] / 2 + 8 + 2);
  });

  it('uses the edge-clamped countdown band to suppress nearby left ticks and value tags', () => {
    const { paint } = paneFixture([{ id: 'left', value: 110 },
      { id: 'left', value: 109, style: { color: '#aa44cc' } }], true);
    const rec = paint(), primary = rectBefore(rec, 'L:110.00')!;
    expect(primary?.args[1]).toBe(0);
    expect(primary.args[3]).toBe(28);
    expect(rec.ops.some(op => op.text === 'L:109.00')).toBe(false);
    const ticks = rec.ops.filter(op => op.type === 'fillText' && op.text?.startsWith('L:') && op.fillStyle === darkTheme.axisText);
    expect(ticks.every(op => op.args[1] >= 38)).toBe(true);
  });

  it('hides disabled, invisible, transparent and nonfinite secondary sources', () => {
    const { paint } = paneFixture([{ id: 'right', value: 100.25 },
      { id: 'left', value: 91.25, style: { visible: false } },
      { id: 'left', value: 94.25, style: { lastValueVisible: false } },
      { id: 'left', value: 97.25, style: { color: 'transparent' } },
      { id: 'left', value: Number.NaN }]);
    const rec = paint();
    for (const label of ['L:91.25', 'L:94.25', 'L:97.25', 'L:NaN']) expect(rec.ops.some(op => op.text === label)).toBe(false);
  });

  it('does not label hidden scales and still labels a visible non-readout source', () => {
    const { paint } = paneFixture([{ id: 'overlay:hidden', value: 100.25 },
      { id: '', value: 105.25 }, { id: 'left', value: 97.25, style: { color: '#cc5500' } }], true);
    const rec = paint();
    expect(rec.ops.some(op => op.text?.startsWith('H:') || op.text === '00:00:40')).toBe(false);
    expect(rectBefore(rec, 'L:97.25')?.fillStyle).toBe('#cc5500');
  });

  it('keeps repeated pane paint passes stable', () => {
    const { paint } = paneFixture([{ id: 'left', value: 100.25 }, { id: 'right', value: 104.25 }], true);
    const first = paint().ops.map(op => ({ ...op, args: [...op.args] }));
    expect(paint().ops).toEqual(first);
  });

  it('exports both axis tags and one countdown through the same vector paint path', () => {
    const { pane, context } = paneFixture([{ id: 'left', value: 100.25 }, { id: 'right', value: 104.25 }], true);
    const svg = new SvgContext(712, 400, { strict: true });
    pane.paintBase(context, svg.asCanvasContext());
    const output = svg.toString();
    expect(svg.unsupported).toEqual([]);
    expect(output).toContain('L:100.25');
    expect(output).toContain('R:104.25');
    expect(output.match(/00:00:40/g)).toHaveLength(1);
  });
});
